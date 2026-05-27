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

    /**
     * M4.2 (GAPS #9): clone all <b>active</b> configs from {@code fromDate}
     * to {@code toDate}. Skip rows for which a config with the same
     * (instrumentId, strategyId, tradingSide, transactionType, tradingDate)
     * already exists on the target — prevents accidental duplicates when
     * the same morning's clone is invoked twice. Inactive (paused) source
     * configs are NOT cloned so an operator paused config doesn't silently
     * reactivate on tomorrow's clone.
     *
     * <p>Returns the count of configs actually created.
     */
    @Transactional
    public CloneSummary cloneFromDate(LocalDate fromDate, LocalDate toDate) {
        if (fromDate == null || toDate == null) {
            throw new IllegalArgumentException("fromDate and toDate are required");
        }
        if (fromDate.equals(toDate)) {
            throw new IllegalArgumentException("fromDate and toDate must differ");
        }
        List<TradeConfig> source = tradeConfigRepository.findByTradingDateAndIsActiveTrue(fromDate);
        if (source.isEmpty()) {
            return new CloneSummary(fromDate, toDate, 0, 0);
        }
        List<TradeConfig> existingTarget = tradeConfigRepository.findByTradingDate(toDate);

        int cloned = 0, skipped = 0;
        for (TradeConfig src : source) {
            // Dedupe key intentionally loose — the user can clone twice on
            // different sides / strategies; only the same shape collides.
            boolean duplicate = existingTarget.stream().anyMatch(t ->
                    java.util.Objects.equals(t.getInstrument() != null ? t.getInstrument().getId() : null,
                                             src.getInstrument() != null ? src.getInstrument().getId() : null)
                    && java.util.Objects.equals(t.getStratergyId(), src.getStratergyId())
                    && java.util.Objects.equals(t.getTradingSide(), src.getTradingSide())
                    && java.util.Objects.equals(t.getTransactionType(), src.getTransactionType()));
            if (duplicate) {
                skipped++;
                continue;
            }

            TradeConfig copy = new TradeConfig();
            copy.setInstrument(src.getInstrument());
            copy.setTradingDate(toDate);
            copy.setTradingSide(src.getTradingSide());
            copy.setTransactionType(src.getTransactionType());
            copy.setTarget(src.getTarget());
            copy.setStopLoss(src.getStopLoss());
            copy.setMaxLoss(src.getMaxLoss());
            copy.setOptionDepth(src.getOptionDepth());
            copy.setLotQuantity(src.getLotQuantity());
            copy.setStratergyId(src.getStratergyId());
            copy.setNumberOfTradesPerDay(src.getNumberOfTradesPerDay());
            copy.setNumberOfParallelTrades(src.getNumberOfParallelTrades());
            copy.setItmDepth(src.getItmDepth());
            copy.setOtmDepth(src.getOtmDepth());
            copy.setAtmDepth(src.getAtmDepth());
            copy.setIsActive(Boolean.TRUE);
            TradeConfig saved = tradeConfigRepository.save(copy);

            // Copy SMA timeframes
            List<SmaTimeframe> srcTfs = smaTimeframeRepository.findByTradeConfigId(src.getId());
            if (!srcTfs.isEmpty()) {
                TradeConfig parentRef = tradeConfigRepository.getReferenceById(saved.getId());
                List<SmaTimeframe> copies = new java.util.ArrayList<>(srcTfs.size());
                for (SmaTimeframe tf : srcTfs) {
                    SmaTimeframe ntf = new SmaTimeframe();
                    ntf.setTradeConfig(parentRef);
                    ntf.setTimePeriod(tf.getTimePeriod());
                    ntf.setSma(tf.getSma());
                    ntf.setSlope(tf.getSlope());
                    copies.add(ntf);
                }
                smaTimeframeRepository.saveAll(copies);
            }
            cloned++;
        }
        afterMutation(toDate);
        log.info("[trade-config] clone {} → {}: cloned={} skipped={}", fromDate, toDate, cloned, skipped);
        return new CloneSummary(fromDate, toDate, cloned, skipped);
    }

    /** Result of {@link #cloneFromDate(LocalDate, LocalDate)}. */
    public record CloneSummary(LocalDate fromDate, LocalDate toDate, int cloned, int skipped) {}

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
        // M4.3: active flag. Defensive default to true so a partially-filled
        // form (legacy clients) doesn't silently disable the config.
        tc.setIsActive(form.getActive() == null ? Boolean.TRUE : form.getActive());
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

        // M4.3: is_active
        v.setActive(tc.getIsActive() == null ? true : tc.getIsActive());

        List<SmaTimeframe> rows = (tc.getId() == null)
                ? List.of()
                : smaTimeframeRepository.findByTradeConfigId(tc.getId());
        v.setTimeframes(rows.stream()
                .map(r -> new SmaTimeframeDTO(r.getId(), r.getTimePeriod(), r.getSma(), r.getSlope()))
                .toList());

        // M4.4: open-trade count (across all dates) so the UI can show a
        // warning banner before edits.
        v.setOpenTradeCount(tc.getId() == null
                ? 0
                : tradeOrderRepository.countByTradeConfigIdAndStatus(tc.getId(), "OPEN"));
        return v;
    }
}
