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
import com.moneymaker.tradeconfig.dto.AutoConfigCalendarDTO;
import com.moneymaker.tradeconfig.dto.AutoDeleteRequestDTO;
import com.moneymaker.tradeconfig.dto.AutoDeleteResultDTO;
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

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

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

        List<TradeConfig> all = (date == null)
                ? tradeConfigRepository.findAll()
                : tradeConfigRepository.findByTradingDate(date);

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

    /* ---------------- auto-generated config bulk delete ---------------- */

    /** The only source this bulk API will ever touch. Never client-supplied. */
    public static final String SOURCE_AUTO = "AUTO_DOWNTREND";

    /** Writes within this gap are treated as one generation run. */
    private static final Duration RUN_GAP = Duration.ofMinutes(2);

    /**
     * Per-day counts for the bulk-delete calendar, for one {@code source}.
     * Days with no configs are simply absent from the response.
     */
    public AutoConfigCalendarDTO autoCalendar(LocalDate from, LocalDate to,
                                              AutoDeleteRequestDTO.Source source) {
        if (from == null || to == null) {
            throw new IllegalArgumentException("from and to are required");
        }
        if (to.isBefore(from)) {
            throw new IllegalArgumentException("to must not be before from");
        }

        String sourceName = (source == null ? AutoDeleteRequestDTO.Source.AUTO_DOWNTREND : source).name();

        List<AutoConfigCalendarDTO.Day> days = new ArrayList<>();
        for (Object[] row : tradeConfigRepository.autoCalendar(sourceName, from, to)) {
            days.add(new AutoConfigCalendarDTO.Day(
                    toLocalDate(row[0]),
                    toLong(row[1]),
                    toLong(row[2]),
                    toLong(row[3]),
                    toLong(row[4]),
                    toLocalDateTime(row[5])));
        }
        return new AutoConfigCalendarDTO(from, to, days);
    }

    /**
     * Groups write timestamps into generation runs.
     *
     * <p>A single detector run inserts its configs seconds apart while separate runs
     * are minutes or more apart, so clustering on a {@link #RUN_GAP} boundary
     * recovers "runs" without needing a run-id column. Newest first.</p>
     */
    public List<Map<String, Object>> autoRuns() {
        List<LocalDateTime> stamps = tradeConfigRepository.distinctUpdatedDates(SOURCE_AUTO);
        List<Map<String, Object>> runs = new ArrayList<>();

        LocalDateTime runNewest = null;
        LocalDateTime runOldest = null;
        for (LocalDateTime ts : stamps) {                 // already DESC
            if (runNewest == null) {
                runNewest = ts;
                runOldest = ts;
                continue;
            }
            if (Duration.between(ts, runOldest).compareTo(RUN_GAP) <= 0) {
                runOldest = ts;                           // same run, extend backwards
            } else {
                runs.add(describeRun(runNewest, runOldest));
                runNewest = ts;
                runOldest = ts;
            }
        }
        if (runNewest != null) {
            runs.add(describeRun(runNewest, runOldest));
        }
        return runs;
    }

    private Map<String, Object> describeRun(LocalDateTime newest, LocalDateTime oldest) {
        // Widen by a second on each side so the boundary stamps are inside the range.
        LocalDateTime from = oldest.minusSeconds(1);
        LocalDateTime to = newest.plusSeconds(1);
        List<TradeConfig> configs =
                tradeConfigRepository.findBySourceAndUpdatedDateBetween(SOURCE_AUTO, from, to);

        List<LocalDate> dates = configs.stream()
                .map(TradeConfig::getTradingDate)
                .filter(Objects::nonNull)
                .distinct()
                .sorted()
                .toList();

        Map<String, Object> run = new LinkedHashMap<>();
        run.put("updatedFrom", from);
        run.put("updatedTo", to);
        run.put("ranAt", newest);
        run.put("configs", configs.size());
        run.put("tradingDates", dates);
        return run;
    }

    /**
     * Bulk-deletes auto-generated configs and their {@code sma_timeframe} children.
     *
     * <p>Three guarantees, in order of importance:</p>
     * <ol>
     *   <li><b>MANUAL rows need an explicit opt-in.</b> {@code source} defaults to
     *       {@link #SOURCE_AUTO}, so an incomplete or malformed request can only
     *       ever reach disposable detector output. Selecting
     *       {@link AutoDeleteRequestDTO.Source#MANUAL} is the only way to touch
     *       hand-written configs, and {@code mode=UPDATED_RANGE} stays pinned to
     *       AUTO regardless — a "generation run" is a detector concept, and most
     *       MANUAL rows have no {@code updated_date} to match on anyway.</li>
     *   <li><b>{@code dryRun} reports without deleting</b>, and the UI always
     *       previews first so the confirmed number is the server's own count.</li>
     *   <li><b>Configs with trade_order rows are skipped, not deleted</b>, matching
     *       the audit protection on the single-config delete. They are reported
     *       separately rather than failing the batch — unless the caller opts in
     *       with {@code force}, which deletes those configs <i>and their trade
     *       rows</i>. That is the one path in the app that removes trade history,
     *       so it is never the default and the UI requires a separate tick.</li>
     * </ol>
     */
    @Transactional
    public AutoDeleteResultDTO deleteAuto(AutoDeleteRequestDTO request) {
        if (request == null) throw new IllegalArgumentException("request payload missing");

        List<TradeConfig> matches = switch (request.getMode()) {
            case TRADING_DATE -> {
                if (request.getDates() == null || request.getDates().isEmpty()) {
                    throw new IllegalArgumentException("dates is required when mode=TRADING_DATE");
                }
                AutoDeleteRequestDTO.Source src = request.getSource() == null
                        ? AutoDeleteRequestDTO.Source.AUTO_DOWNTREND
                        : request.getSource();
                yield tradeConfigRepository.findBySourceAndTradingDateIn(src.name(), request.getDates());
            }
            // Pinned to AUTO: runs are recovered from updated_date, which the
            // detector stamps and hand-written configs mostly leave null.
            case UPDATED_RANGE -> {
                if (request.getUpdatedFrom() == null || request.getUpdatedTo() == null) {
                    throw new IllegalArgumentException(
                            "updatedFrom and updatedTo are required when mode=UPDATED_RANGE");
                }
                yield tradeConfigRepository.findBySourceAndUpdatedDateBetween(
                        SOURCE_AUTO, request.getUpdatedFrom(), request.getUpdatedTo());
            }
        };

        boolean force = request.isForce();

        List<TradeConfig> deletable = new ArrayList<>();
        List<Integer> tradedIds = new ArrayList<>();
        for (TradeConfig tc : matches) {
            if (tradeOrderRepository.existsByTradeConfigId(tc.getId())) {
                tradedIds.add(tc.getId());
                if (force) deletable.add(tc);
            } else {
                deletable.add(tc);
            }
        }
        // Counted even when force is off, so the confirm dialog can state what an
        // opt-in would cost before the user ticks the box.
        long tradeOrders = tradedIds.isEmpty()
                ? 0L
                : tradeOrderRepository.countByTradeConfigIdIn(tradedIds);
        List<Integer> skippedIds = force ? List.of() : List.copyOf(tradedIds);

        Map<LocalDate, Long> byDate = new TreeMap<>();
        for (TradeConfig tc : deletable) {
            byDate.merge(tc.getTradingDate(), 1L, Long::sum);
        }
        List<Integer> ids = deletable.stream().map(TradeConfig::getId).toList();

        if (request.isDryRun()) {
            return new AutoDeleteResultDTO(
                    matches.size(), 0, 0, byDate, ids,
                    tradedIds.size(), tradeOrders, skippedIds.size(), skippedIds, true,
                    summary(matches.size(), deletable.size(), skippedIds.size(),
                            force ? tradeOrders : 0, true));
        }

        // Trade rows first: once the configs are gone their ids are unrecoverable,
        // so an interrupted delete must not be able to strand the ledger.
        long removedTradeOrders = 0;
        if (force && !tradedIds.isEmpty()) {
            removedTradeOrders = tradeOrderRepository.deleteByTradeConfigIdIn(tradedIds);
        }

        long removedTimeframes = 0;
        for (TradeConfig tc : deletable) {
            removedTimeframes += smaTimeframeRepository.findByTradeConfigId(tc.getId()).size();
            smaTimeframeRepository.deleteByTradeConfigId(tc.getId());
        }
        tradeConfigRepository.deleteAll(deletable);

        // Same cache refresh the single delete performs, once per affected date.
        byDate.keySet().forEach(this::afterMutation);

        log.info("[trade-config] bulk-deleted {} config(s) + {} timeframe row(s); "
                        + "force={} tradeOrdersRemoved={} skipped={} with trades; dates={}",
                deletable.size(), removedTimeframes, force, removedTradeOrders,
                skippedIds.size(), byDate.keySet());

        return new AutoDeleteResultDTO(
                matches.size(), deletable.size(), removedTimeframes, byDate, ids,
                tradedIds.size(), force ? removedTradeOrders : tradeOrders,
                skippedIds.size(), skippedIds, false,
                summary(matches.size(), deletable.size(), skippedIds.size(),
                        removedTradeOrders, false));
    }

    /**
     * @param removedTradeOrders trade rows that went (or would go) with the configs;
     *                           always 0 unless {@code force} was set.
     */
    private String summary(long matched, long deletable, long skipped,
                           long removedTradeOrders, boolean dryRun) {
        if (matched == 0) {
            return "No auto-generated configs matched the selection.";
        }
        String verb = dryRun ? "Would delete" : "Deleted";
        String base = verb + " " + deletable + " of " + matched + " matched config(s)";
        if (skipped > 0) {
            return base + "; " + skipped + " kept because trades reference them.";
        }
        if (removedTradeOrders > 0) {
            return base + " and " + removedTradeOrders + " linked trade_order row(s).";
        }
        return base + ".";
    }

    private static LocalDate toLocalDate(Object v) {
        if (v == null) return null;
        if (v instanceof java.sql.Date d) return d.toLocalDate();
        if (v instanceof LocalDate d) return d;
        return LocalDate.parse(v.toString());
    }

    private static LocalDateTime toLocalDateTime(Object v) {
        if (v == null) return null;
        if (v instanceof java.sql.Timestamp t) return t.toLocalDateTime();
        if (v instanceof LocalDateTime d) return d;
        return null;
    }

    private static long toLong(Object v) {
        return v == null ? 0L : ((Number) v).longValue();
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
        v.setSource(tc.getSource());
        v.setUpdatedDate(tc.getUpdatedDate());

        List<SmaTimeframe> rows = (tc.getId() == null)
                ? List.of()
                : smaTimeframeRepository.findByTradeConfigId(tc.getId());
        v.setTimeframes(rows.stream()
                .map(r -> new SmaTimeframeDTO(r.getId(), r.getTimePeriod(), r.getSma(), r.getSlope()))
                .toList());
        return v;
    }
}
