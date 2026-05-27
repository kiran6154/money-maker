package com.moneymaker.tradeconfig.service;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.StrategyFactory;
import com.moneymaker.tradeconfig.dto.InstrumentOptionDTO;
import com.moneymaker.tradeconfig.dto.PagedResponse;
import com.moneymaker.tradeconfig.dto.SmaTimeframeDTO;
import com.moneymaker.tradeconfig.dto.StrategyOptionDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigFormDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigViewDTO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Single owner of trade-config CRUD from the UI. Centralises three side-effects
 * that callers must not skip:
 * <ol>
 *   <li>Persist the {@link TradeConfig} + child {@link SmaTimeframe} rows.</li>
 *   <li>Invalidate {@link TradeConfigScheduler}'s in-JVM date cache so the
 *       next analysis tick refetches from the DB.</li>
 *   <li>If the config is for <i>today</i> and we are in live mode, rebuild
 *       {@link SharedData#combinedDto} immediately — otherwise the running
 *       5-min schedulers continue to operate on a stale snapshot until the
 *       next 09:16 cron / JVM restart.</li>
 * </ol>
 *
 * <p>Controllers must call this service rather than the repositories directly
 * — see {@code CLAUDE.md} invariant on trade-config writes.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TradeConfigAdminService {

    private final TradeConfigRepository tradeConfigRepository;
    private final SmaTimeframeRepository smaTimeframeRepository;
    private final InstrumentRepository instrumentRepository;
    private final TradeOrderRepository tradeOrderRepository;
    private final TradeConfigScheduler tradeConfigScheduler;
    private final StrategyFactory strategyFactory;

    @Value("${app.mode:live}")
    private String appMode;

    /* ---------------- dropdown sources ---------------- */

    public List<InstrumentOptionDTO> listInstruments() {
        return instrumentRepository.findAll().stream()
                .sorted(Comparator.comparing(Instrument::getInsName, Comparator.nullsLast(String::compareToIgnoreCase)))
                .map(i -> new InstrumentOptionDTO(i.getId(), i.getInsName()))
                .toList();
    }

    public List<StrategyOptionDTO> listStrategies() {
        return strategyFactory.availableStrategyIds().stream()
                .map(id -> new StrategyOptionDTO(id, "Strategy " + id))
                .toList();
    }

    /* ---------------- queries ---------------- */

    public PagedResponse<TradeConfigViewDTO> list(LocalDate date, int page, int pageSize) {
        int safePage = Math.max(page, 0);
        int safeSize = Math.max(pageSize, 1);

        // Defensive copy: Spring Data Repository.findAll() returns an
        // ArrayList in production, but Repository.findBy* with custom
        // queries can return immutable lists in some test setups (and
        // List.of(...) used in tests). Mutating the result directly via
        // .sort() throws UnsupportedOperationException in those cases.
        List<TradeConfig> all = new java.util.ArrayList<>((date == null)
                ? tradeConfigRepository.findAll()
                : tradeConfigRepository.findByTradingDate(date));

        all.sort(Comparator.comparing(TradeConfig::getId, Comparator.nullsLast(Integer::compareTo)).reversed());

        long total = all.size();
        int from = Math.min(safePage * safeSize, all.size());
        int to = Math.min(from + safeSize, all.size());

        List<TradeConfigViewDTO> items = all.subList(from, to).stream()
                .map(this::toView)
                .toList();

        int totalPages = (int) Math.ceil((double) total / (double) safeSize);
        return new PagedResponse<>(items, safePage, safeSize, total, totalPages);
    }

    public TradeConfigViewDTO findById(Integer id) {
        TradeConfig tc = tradeConfigRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("No trade config with id=" + id));
        return toView(tc);
    }

    /* ---------------- mutations ---------------- */

    @Transactional
    public TradeConfigViewDTO create(TradeConfigFormDTO form) {
        validate(form);
        TradeConfig tc = new TradeConfig();
        applyForm(tc, form);
        TradeConfig saved = tradeConfigRepository.save(tc);

        replaceTimeframes(saved.getId(), form.getTimeframes());

        afterMutation(saved.getTradingDate());
        log.info("[trade-config] created id={} date={} instrument={}",
                saved.getId(), saved.getTradingDate(),
                saved.getInstrument() != null ? saved.getInstrument().getInsName() : null);
        return findById(saved.getId());
    }

    @Transactional
    public TradeConfigViewDTO update(Integer id, TradeConfigFormDTO form) {
        validate(form);
        TradeConfig tc = tradeConfigRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("No trade config with id=" + id));
        LocalDate previousDate = tc.getTradingDate();
        applyForm(tc, form);
        tradeConfigRepository.save(tc);

        replaceTimeframes(id, form.getTimeframes());

        afterMutation(previousDate);
        afterMutation(tc.getTradingDate());
        log.info("[trade-config] updated id={} date={}", id, tc.getTradingDate());
        return findById(id);
    }

    @Transactional
    public void delete(Integer id) {
        TradeConfig tc = tradeConfigRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("No trade config with id=" + id));
        if (tradeOrderRepository.existsByTradeConfigId(id)) {
            throw new IllegalStateException(
                    "Cannot delete trade config " + id + " — trade_order rows reference it. " +
                    "Configs with executed trades are kept for audit.");
        }
        smaTimeframeRepository.deleteByTradeConfigId(id);
        tradeConfigRepository.deleteById(id);
        afterMutation(tc.getTradingDate());
        log.info("[trade-config] deleted id={}", id);
    }

    /* ---------------- helpers ---------------- */

    private void validate(TradeConfigFormDTO form) {
        if (form == null) throw new IllegalArgumentException("form payload missing");
        if (form.getInstrumentId() == null) throw new IllegalArgumentException("instrumentId is required");
        if (form.getTradingDate() == null) throw new IllegalArgumentException("tradingDate is required");
        if (form.getStrategyId() == null) throw new IllegalArgumentException("strategyId is required");
        if (!instrumentRepository.existsById(form.getInstrumentId())) {
            throw new IllegalArgumentException("Unknown instrumentId=" + form.getInstrumentId());
        }
        if (!strategyFactory.availableStrategyIds().contains(form.getStrategyId())) {
            throw new IllegalArgumentException("Unknown strategyId=" + form.getStrategyId());
        }
    }

    private void applyForm(TradeConfig tc, TradeConfigFormDTO form) {
        Instrument ref = instrumentRepository.getReferenceById(form.getInstrumentId());
        tc.setInstrument(ref);
        tc.setTradingDate(form.getTradingDate());
        tc.setTradingSide(form.getTradingSide());
        tc.setTransactionType(form.getTransactionType());
        tc.setTarget(form.getTarget());
        tc.setStopLoss(form.getStopLoss());
        tc.setMaxLoss(form.getMaxLoss());
        tc.setOptionDepth(form.getOptionDepth());
        tc.setLotQuantity(form.getLotQuantity());
        tc.setStratergyId(form.getStrategyId());
        tc.setNumberOfTradesPerDay(form.getNumberOfTradesPerDay());
        tc.setNumberOfParallelTrades(form.getNumberOfParallelTrades());
        tc.setItmDepth(form.getItmDepth());
        tc.setOtmDepth(form.getOtmDepth());
        tc.setAtmDepth(form.getAtmDepth());
    }

    /**
     * Wipes existing SMA rows for the config and re-inserts the submitted list.
     * Simpler than diff-merging; trade configs typically carry 1-3 timeframes
     * so the delete-all-then-insert cost is negligible and avoids subtle
     * "ghost row" bugs when the user removes a timeframe in the UI.
     */
    private void replaceTimeframes(Integer tradeConfigId, List<SmaTimeframeDTO> incoming) {
        smaTimeframeRepository.deleteByTradeConfigId(tradeConfigId);
        if (incoming == null || incoming.isEmpty()) return;
        TradeConfig parentRef = tradeConfigRepository.getReferenceById(tradeConfigId);
        List<SmaTimeframe> rows = new ArrayList<>(incoming.size());
        for (SmaTimeframeDTO dto : incoming) {
            if (dto == null) continue;
            if (dto.getTimePeriod() == null || dto.getSma() == null) continue;
            SmaTimeframe row = new SmaTimeframe();
            row.setTradeConfig(parentRef);
            row.setTimePeriod(dto.getTimePeriod());
            row.setSma(dto.getSma());
            row.setSlope(dto.getSlope());
            rows.add(row);
        }
        smaTimeframeRepository.saveAll(rows);
    }

    /**
     * Always invalidate the date-cache; if the mutation touches today's
     * configs and we're running live, rebuild {@link SharedData#combinedDto}
     * immediately so the next 5-min scheduler tick sees the new state without
     * a JVM restart.
     */
    private void afterMutation(LocalDate affectedDate) {
        tradeConfigScheduler.invalidateConfigsCache();
        if (affectedDate == null) return;
        if (!"live".equalsIgnoreCase(appMode)) return;
        if (!affectedDate.equals(LocalDate.now())) return;
        List<TradeConfigCombinedDTO> refreshed = tradeConfigScheduler.getConfigsForDate(affectedDate);
        SharedData.combinedDto = refreshed;
        log.info("[trade-config] refreshed SharedData.combinedDto for {} ({} configs)",
                affectedDate, refreshed.size());
    }

    private TradeConfigViewDTO toView(TradeConfig tc) {
        TradeConfigViewDTO v = new TradeConfigViewDTO();
        v.setId(tc.getId());
        Instrument ins = tc.getInstrument();
        v.setInstrumentId(ins != null ? ins.getId() : null);
        v.setInstrumentName(ins != null ? ins.getInsName() : null);
        v.setTradingDate(tc.getTradingDate());
        v.setTradingSide(tc.getTradingSide());
        v.setTransactionType(tc.getTransactionType());
        v.setTarget(tc.getTarget());
        v.setStopLoss(tc.getStopLoss());
        v.setMaxLoss(tc.getMaxLoss());
        v.setOptionDepth(tc.getOptionDepth());
        v.setLotQuantity(tc.getLotQuantity());
        v.setStrategyId(tc.getStratergyId());
        v.setNumberOfTradesPerDay(tc.getNumberOfTradesPerDay());
        v.setNumberOfParallelTrades(tc.getNumberOfParallelTrades());
        v.setItmDepth(tc.getItmDepth());
        v.setOtmDepth(tc.getOtmDepth());
        v.setAtmDepth(tc.getAtmDepth());

        List<SmaTimeframe> rows = (tc.getId() == null)
                ? List.of()
                : smaTimeframeRepository.findByTradeConfigId(tc.getId());
        v.setTimeframes(rows.stream()
                .map(r -> new SmaTimeframeDTO(r.getId(), r.getTimePeriod(), r.getSma(), r.getSlope()))
                .toList());
        return v;
    }
}
