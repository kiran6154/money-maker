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
import com.moneymaker.util.StrategyIds;
import com.moneymaker.util.TrailLadder;
import com.moneymaker.tradeconfig.dto.AutoConfigCalendarDTO;
import com.moneymaker.tradeconfig.dto.AutoDeleteRequestDTO;
import com.moneymaker.tradeconfig.dto.AutoDeleteResultDTO;
import com.moneymaker.tradeconfig.dto.BulkUpdatePrefillDTO;
import com.moneymaker.tradeconfig.dto.BulkUpdateRequestDTO;
import com.moneymaker.tradeconfig.dto.BulkUpdateResultDTO;
import com.moneymaker.tradeconfig.dto.CloneResultDTO;
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

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
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
    private final com.moneymaker.journal.JournalRecorder journal;

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

    /**
     * Every config in a trading-date window, oldest date first — the source for
     * the backtest page's "limit to selected configs" picker. Unpaged on
     * purpose: a picker needs the whole window at once, and a backtest window
     * is days-to-weeks, not years. {@code source} narrows to one origin
     * ({@code null} = both).
     */
    public List<TradeConfigViewDTO> listRange(LocalDate from, LocalDate to,
                                              AutoDeleteRequestDTO.Source source) {
        if (from == null || to == null) {
            throw new IllegalArgumentException("from and to are required");
        }
        if (to.isBefore(from)) {
            throw new IllegalArgumentException("to must not be before from");
        }
        return tradeConfigRepository.findByTradingDateBetween(from, to).stream()
                .filter(tc -> source == null || source.name().equals(tc.getSource()))
                .sorted(Comparator
                        .comparing(TradeConfig::getTradingDate,
                                Comparator.nullsLast(LocalDate::compareTo))
                        .thenComparing(TradeConfig::getId,
                                Comparator.nullsLast(Integer::compareTo)))
                .map(this::toView)
                .toList();
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
        return update(id, form, false);
    }

    /**
     * @param confirm the caller has seen the consequential-change warning and
     *                wants the edit anyway. Ignored when the config has no OPEN
     *                trades, which is the overwhelmingly common case.
     * @throws ConfirmationRequiredException when trades are open and the edit
     *         touches something those trades still read. See
     *         {@link #consequentialChanges(TradeConfig, TradeConfigFormDTO)}.
     */
    @Transactional
    public TradeConfigViewDTO update(Integer id, TradeConfigFormDTO form, boolean confirm) {
        validate(form);
        TradeConfig tc = tradeConfigRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("No trade config with id=" + id));

        if (!confirm) {
            long openTrades = tradeOrderRepository.countByTradeConfigIdAndStatus(id, STATUS_OPEN);
            if (openTrades > 0) {
                List<String> changes = consequentialChanges(tc, form);
                if (!changes.isEmpty()) {
                    throw new ConfirmationRequiredException(
                            "Config " + id + " has " + openTrades + " open trade(s), and this edit changes "
                                    + String.join("; ", changes)
                                    + ". Those changes affect the rest of today's behaviour on this config. "
                                    + "Re-send with confirm=true to apply.",
                            changes, openTrades);
                }
            }
        }

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
        // Deleting a config takes its trades and every reference with it
        // (user decision 2026-08-31). The one refusal: an OPEN trade, which
        // may be a live broker position - force-close it (or retire the
        // config) first.
        if (tradeOrderRepository.existsByTradeConfigIdAndStatus(id, "OPEN")) {
            throw new IllegalStateException(
                    "Cannot delete trade config " + id + " - it has OPEN trade(s), which may be a live " +
                    "broker position. Force-close them first, or retire the config instead: " +
                    "POST /api/trade-configs/" + id + "/active?value=false");
        }
        long removedTrades = tradeOrderRepository.deleteByTradeConfigIdIn(List.of(id));
        smaTimeframeRepository.deleteByTradeConfigId(id);
        journal.deleteForTradeConfigs(List.of(id));
        journal.deleteOrphanedTradeRows();
        tradeConfigRepository.deleteById(id);
        afterMutation(tc.getTradingDate());
        log.info("[trade-config] deleted id={} with {} trade row(s)", id, removedTrades);
    }

    /**
     * Retires or reinstates a config without touching its history (GAPS #7).
     *
     * <p>An inactive config is skipped by
     * {@code TradeConfigRepository.fetchCombinedByTradingDate}, so no strategy
     * scans it and no new trade opens against it. It keeps its id, its
     * {@code sma_timeframe} children and every {@code trade_order} row that
     * references it — which is exactly what hard delete cannot offer for a config
     * that has traded, and what forcing {@code tradingDate} into the past was
     * being abused to fake.</p>
     *
     * <h3>Refused while the config has OPEN trades</h3>
     * Not a nicety. Retiring drops the config out of {@code SharedData.combinedDto},
     * and {@code OrderService.findConfig} resolves an open row's config from exactly
     * that list when it needs the quantity for an <b>exit</b>. With no DTO the exit
     * is never dispatched: the ledger row is marked CLOSED while the broker position
     * stays open — the failure GAPS #1's {@code alertForceCloseExitFailed} exists to
     * shout about. Retiring is supposed to mean "open nothing further"; also meaning
     * "and strand what is open" is not a trade-off worth offering behind a
     * confirmation dialog, so this refuses and says what to do instead.
     *
     * <p>The underlying hazard is older than this method — editing a config's
     * {@code tradingDate} into the past does the same thing, and that is precisely
     * the workaround GAPS #7 exists to replace — and is filed as
     * {@code STRATEGY_ANALYSIS_TODO.md} S13. When it is fixed, this refusal can
     * relax to a warning.</p>
     *
     * <p>Reinstating is always allowed: it can only add a config back to dispatch.</p>
     */
    @Transactional
    public TradeConfigViewDTO setActive(Integer id, boolean active) {
        TradeConfig tc = tradeConfigRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("No trade config with id=" + id));

        long openTrades = tradeOrderRepository.countByTradeConfigIdAndStatus(id, STATUS_OPEN);
        if (!active && openTrades > 0) {
            throw new IllegalStateException(
                    "Cannot retire trade config " + id + " — it has " + openTrades + " open trade(s). "
                            + "A retired config leaves SharedData.combinedDto, and an exit leg is sized from "
                            + "that cached config, so those positions would be closed in the ledger without an "
                            + "order reaching the broker. Close them first (or let the 15:31 sweep close them), "
                            + "then retire.");
        }

        tc.setIsActive(active);
        tradeConfigRepository.save(tc);
        afterMutation(tc.getTradingDate());

        log.info("[trade-config] {} id={} date={}", active ? "reinstated" : "retired", id, tc.getTradingDate());
        return findById(id);
    }

    /** Ledger status for a live position — matches {@code OrderService}'s vocabulary. */
    private static final String STATUS_OPEN = "OPEN";

    /**
     * The changes that a currently-open trade would still feel, i.e. the ones
     * worth stopping the user for (GAPS #8).
     *
     * <p>The rule is one line: <b>a field is consequential unless the order
     * snapshotted it at entry.</b> The bracket did get snapshotted —
     * {@code target_at_entry} / {@code stop_loss_at_entry} (changeset 011),
     * {@code trail_ladder_at_entry} (036) — precisely so a mid-day edit could not
     * retroactively re-price an open position, so target / stop-loss / their
     * percentage forms / the max-SL cap / the ladder are all deliberately absent
     * from this list. Editing them mid-trade is safe by construction and warning
     * about it would train the operator to click through the dialog.</p>
     *
     * <p>What is <i>not</i> snapshotted, and therefore is listed:</p>
     * <ul>
     *   <li>{@code transactionType} / {@code tradingSide} — which side and which
     *       leg the rest of the day trades.</li>
     *   <li>{@code lotQuantity} — {@code trade_order.quantity} is snapshotted
     *       (029), but the placement services size an order from the <i>config</i>
     *       ({@code ZerodhaOrderPlacementService.quantity}), so an open trade
     *       would exit at a different size than it entered. That is a partial
     *       close or an accidental reversal, not a resize.</li>
     *   <li>{@code numberOfTradesPerDay} / {@code numberOfParallelTrades} — the
     *       caps the rest of the day is counted against, with trades already
     *       counting toward them.</li>
     *   <li>{@code strategyId} — {@code (trade_config_id, strategy_id)} is the
     *       identity those caps are applied against, so moving it re-buckets the
     *       open trades' accounting.</li>
     *   <li>{@code instrumentId} / {@code tradingDate} — at that point it is a
     *       different config wearing the same id.</li>
     * </ul>
     */
    private List<String> consequentialChanges(TradeConfig current, TradeConfigFormDTO form) {
        List<String> changes = new ArrayList<>();
        Integer currentInstrumentId = current.getInstrument() == null ? null : current.getInstrument().getId();

        addIfChanged(changes, "instrument", currentInstrumentId, form.getInstrumentId());
        addIfChanged(changes, "tradingDate", current.getTradingDate(), form.getTradingDate());
        addIfChanged(changes, "tradingSide", current.getTradingSide(), form.getTradingSide());
        addIfChanged(changes, "transactionType", current.getTransactionType(), form.getTransactionType());
        addIfChanged(changes, "lotQuantity", current.getLotQuantity(), form.getLotQuantity());
        addIfChanged(changes, "numberOfTradesPerDay",
                current.getNumberOfTradesPerDay(), form.getNumberOfTradesPerDay());
        addIfChanged(changes, "numberOfParallelTrades",
                current.getNumberOfParallelTrades(), form.getNumberOfParallelTrades());
        // Null = "keep current" (see apply), so only a real value can differ.
        if (form.getMaxParallelPerSide() != null) {
            addIfChanged(changes, "maxParallelPerSide",
                    current.getMaxParallelPerSide(), form.getMaxParallelPerSide());
        }
        addIfChanged(changes, "strategyId", current.getStratergyId(), form.getStrategyId());
        return changes;
    }

    private static void addIfChanged(List<String> into, String field, Object before, Object after) {
        if (!Objects.equals(before, after)) {
            into.add(field + ": " + before + " -> " + after);
        }
    }

    /* ---------------- bulk clone: one trading day to another (GAPS #9) ---------------- */

    /**
     * Copies every runnable config from one trading date to another, with their
     * {@code sma_timeframe} children.
     *
     * <p>This is the most-skipped step in real ops: a user with eight configs was
     * otherwise recreating them by hand every morning, or running
     * {@code INSERT … SELECT … WHERE trading_date='yesterday'} against the
     * database — which bypasses this service and therefore the cache-invalidation
     * contract, so the configs exist but the running pipeline cannot see them
     * until the next restart.</p>
     *
     * <h3>Three decisions worth knowing</h3>
     * <ul>
     *   <li><b>Dry run by default.</b> Same shape as {@code deleteAuto}: a caller
     *       who omits the flag gets a preview, and the UI confirms against the
     *       server's own count rather than its own guess.</li>
     *   <li><b>Retired configs are not cloned.</b> {@code is_active=false} means
     *       "do not run this"; carrying it to a new day as active would resurrect
     *       exactly what someone retired. Reported separately so the number is
     *       explained rather than just missing.</li>
     *   <li><b>Clones are stamped {@code MANUAL}, whatever the source was.</b> A
     *       clone is a human action. Keeping {@code AUTO_DOWNTREND} would hand the
     *       row to the detector's dedupe key, which treats "a config already exists
     *       for this (day, strategy)" as "I already generated" — so cloning an AUTO
     *       config forward would silently suppress the detector's own output for
     *       that day. Stamping MANUAL keeps the two populations separate, which is
     *       what the bulk-delete panel and the calendar both assume.</li>
     * </ul>
     *
     * <h3>Idempotency</h3>
     * Re-running is safe. A source config is skipped when {@code toDate} already
     * carries an equivalent one — same instrument, trading side, transaction type
     * and primary strategy. That tuple is not a database key (nothing stops two
     * genuinely different configs sharing it), so this is a deliberate
     * best-effort: clone twice and you get one set, but a hand-built config that
     * happens to match is treated as already-cloned and reported as skipped rather
     * than silently doubled. Doubling configs doubles positions, so the failure
     * this leans toward is the recoverable one.
     */
    @Transactional
    public CloneResultDTO cloneDay(LocalDate fromDate, LocalDate toDate, boolean dryRun) {
        if (fromDate == null || toDate == null) {
            throw new IllegalArgumentException("fromDate and toDate are required");
        }
        if (fromDate.equals(toDate)) {
            throw new IllegalArgumentException("fromDate and toDate are the same day (" + fromDate
                    + ") — a clone onto itself would only duplicate every config");
        }

        List<TradeConfig> source = tradeConfigRepository.findByTradingDate(fromDate);
        Set<String> existing = new HashSet<>();
        for (TradeConfig tc : tradeConfigRepository.findByTradingDate(toDate)) {
            existing.add(identityKey(tc));
        }

        int skippedRetired = 0;
        int skippedExisting = 0;
        int timeframesCopied = 0;
        List<Integer> created = new ArrayList<>();

        for (TradeConfig tc : source) {
            if (Boolean.FALSE.equals(tc.getIsActive())) {
                skippedRetired++;
                continue;
            }
            if (!existing.add(identityKey(tc))) {
                skippedExisting++;
                continue;
            }

            List<SmaTimeframe> timeframes = smaTimeframeRepository.findByTradeConfigId(tc.getId());
            timeframesCopied += timeframes.size();

            if (dryRun) {
                continue;
            }

            TradeConfig copy = copyForDate(tc, toDate);
            TradeConfig saved = tradeConfigRepository.save(copy);
            created.add(saved.getId());

            TradeConfig parentRef = tradeConfigRepository.getReferenceById(saved.getId());
            List<SmaTimeframe> copies = new ArrayList<>(timeframes.size());
            for (SmaTimeframe tf : timeframes) {
                SmaTimeframe row = new SmaTimeframe();
                row.setTradeConfig(parentRef);
                row.setTimePeriod(tf.getTimePeriod());
                row.setSma(tf.getSma());
                row.setSlope(tf.getSlope());
                copies.add(row);
            }
            smaTimeframeRepository.saveAll(copies);
        }

        int cloned = dryRun
                ? source.size() - skippedRetired - skippedExisting
                : created.size();

        if (!dryRun && cloned > 0) {
            afterMutation(toDate);
        }

        String summary = cloneSummary(source.size(), cloned, skippedRetired, skippedExisting,
                fromDate, toDate, dryRun);
        log.info("[trade-config] clone {} -> {}: {} (dryRun={})", fromDate, toDate, summary, dryRun);

        return new CloneResultDTO(fromDate, toDate, source.size(), skippedRetired, skippedExisting,
                cloned, List.copyOf(created), timeframesCopied, dryRun, summary);
    }

    /**
     * What makes two configs "the same config on a different day" for clone
     * de-duplication. Not a database constraint — see the idempotency note on
     * {@link #cloneDay}.
     */
    private static String identityKey(TradeConfig tc) {
        Integer instrumentId = tc.getInstrument() == null ? null : tc.getInstrument().getId();
        return instrumentId + "|" + tc.getTradingSide() + "|" + tc.getTransactionType()
                + "|" + tc.getStratergyId();
    }

    /**
     * Field-by-field copy onto a new trading date.
     *
     * <p>Written out longhand rather than reflected or serialised: a new column
     * that nobody adds here is silently dropped from every clone, and a loud
     * compile-time list is the only thing that makes that omission visible. Same
     * reason {@code applyForm} / {@code toView} are longhand — see the note in
     * {@code ORDERS_AND_POSITIONS.md} about a column missing from one of the four
     * places.</p>
     */
    private TradeConfig copyForDate(TradeConfig from, LocalDate toDate) {
        TradeConfig c = new TradeConfig();
        c.setInstrument(from.getInstrument());
        c.setTradingDate(toDate);
        c.setTradingSide(from.getTradingSide());
        c.setTransactionType(from.getTransactionType());
        c.setTarget(from.getTarget());
        c.setStopLoss(from.getStopLoss());
        c.setTargetPct(from.getTargetPct());
        c.setSlPct(from.getSlPct());
        c.setMaxLoss(from.getMaxLoss());
        c.setOptionDepth(from.getOptionDepth());
        c.setLotQuantity(from.getLotQuantity());
        c.setStratergyId(from.getStratergyId());
        c.setStrategyIds(from.getStrategyIds());
        c.setNumberOfTradesPerDay(from.getNumberOfTradesPerDay());
        c.setNumberOfParallelTrades(from.getNumberOfParallelTrades());
        c.setMaxParallelPerSide(from.getMaxParallelPerSide());
        c.setItmDepth(from.getItmDepth());
        c.setOtmDepth(from.getOtmDepth());
        c.setAtmDepth(from.getAtmDepth());
        c.setMinOptionPrice(from.getMinOptionPrice());
        c.setMaxOptionPrice(from.getMaxOptionPrice());
        c.setMaxSlPoints(from.getMaxSlPoints());
        c.setTrailLadder(from.getTrailLadder());
        // Not copied, on purpose: `source` (a clone is a human action — see the
        // javadoc on cloneDay), `isActive` (a new config starts runnable), `id`,
        // and `updatedDate` (stamped by @PrePersist).
        c.setSource(SOURCE_MANUAL);
        c.setIsActive(Boolean.TRUE);
        return c;
    }

    private static String cloneSummary(int matched, int cloned, int skippedRetired, int skippedExisting,
                                       LocalDate fromDate, LocalDate toDate, boolean dryRun) {
        if (matched == 0) {
            return "No configs on " + fromDate + " to clone.";
        }
        StringBuilder sb = new StringBuilder(dryRun ? "Would clone " : "Cloned ");
        sb.append(cloned).append(" of ").append(matched)
          .append(" config(s) from ").append(fromDate).append(" to ").append(toDate);
        if (skippedExisting > 0) {
            sb.append("; ").append(skippedExisting).append(" already present on ").append(toDate);
        }
        if (skippedRetired > 0) {
            sb.append("; ").append(skippedRetired).append(" retired and left behind");
        }
        return sb.append('.').toString();
    }

    /* ---------------- auto-generated config bulk delete ---------------- */

    /** The only source this bulk API will ever touch. Never client-supplied. */
    public static final String SOURCE_AUTO = "AUTO_DOWNTREND";

    /** Origin stamped on configs created through this service — i.e. by a human. */
    public static final String SOURCE_MANUAL = "MANUAL";

    /**
     * Standing premium band applied when a config does not state one.
     *
     * <p>Mirrors the DB defaults in changeset {@code 025_default_option_price_range}
     * and must be kept in step with them. Duplicated deliberately: Hibernate names
     * every column in its INSERT, so a null field is written as an explicit NULL
     * and the DB default never fires on a JPA insert — the same trap that made
     * {@code source} break every create through this service.</p>
     */
    public static final BigDecimal DEFAULT_MIN_OPTION_PRICE = new BigDecimal("80");
    public static final BigDecimal DEFAULT_MAX_OPTION_PRICE = new BigDecimal("250");

    /**
     * Standing ceiling on the stop-loss, in premium points (changeset 036).
     * Applied when the form leaves the field blank, for the same reason the
     * premium band has a standing value: an uncapped stop is not a neutral
     * default, it is the 75-point stop at the top of the band that the cap
     * exists to prevent.
     */
    public static final BigDecimal DEFAULT_MAX_SL_POINTS = new BigDecimal("60");

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

        // Deleting a config takes its trades and every reference with it —
        // ledger rows, timeframe children, journal rows (user decision
        // 2026-08-31: "trades and its references should also get deleted").
        // The one refusal left: a config with an OPEN trade, which may be a
        // live broker position — force-close it first, then delete. The old
        // `force` flag is accepted for compatibility but no longer gates
        // anything.
        //
        // De-duplicated by id: a matches query that fans out (or a repeated id
        // in a request) must not count — or try to delete — the same config
        // twice.
        List<TradeConfig> deletable = new ArrayList<>();
        List<Integer> openIds = new ArrayList<>();
        List<Integer> tradedIds = new ArrayList<>();
        java.util.Set<Integer> seen = new java.util.HashSet<>();
        for (TradeConfig tc : matches) {
            if (tc.getId() == null || !seen.add(tc.getId())) continue;
            if (tradeOrderRepository.existsByTradeConfigIdAndStatus(tc.getId(), "OPEN")) {
                openIds.add(tc.getId());
                continue;
            }
            if (tradeOrderRepository.existsByTradeConfigId(tc.getId())) {
                tradedIds.add(tc.getId());
            }
            deletable.add(tc);
        }
        // Counted up front so the confirm dialog states exactly how much
        // history goes with the configs before the user agrees.
        long tradeOrders = tradedIds.isEmpty()
                ? 0L
                : tradeOrderRepository.countByTradeConfigIdIn(tradedIds);
        List<Integer> skippedIds = List.copyOf(openIds);

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
                            tradeOrders, true));
        }

        // Trade rows first: once the configs are gone their ids are unrecoverable,
        // so an interrupted delete must not be able to strand the ledger.
        long removedTradeOrders = tradedIds.isEmpty()
                ? 0
                : tradeOrderRepository.deleteByTradeConfigIdIn(tradedIds);

        // Bulk deletes throughout — one statement per table, no per-row count
        // expectations. The old count-then-derived-delete loop queued entity
        // deletions that Hibernate verified at the next iteration's auto-flush,
        // and any row already gone (concurrent request, duplicate id) threw
        // StaleStateException and rolled the whole delete back.
        long removedTimeframes = ids.isEmpty() ? 0 : smaTimeframeRepository.deleteByTradeConfigIdIn(ids);
        if (!ids.isEmpty()) tradeConfigRepository.deleteAllByIdInBatch(ids);
        // Journal hygiene: everything citing the deleted configs goes with
        // them (their trades' rows included, when force removed the trades).
        journal.deleteForTradeConfigs(deletable.stream().map(TradeConfig::getId).toList());
        journal.deleteOrphanedTradeRows();

        // Same cache refresh the single delete performs, once per affected date.
        byDate.keySet().forEach(this::afterMutation);

        log.info("[trade-config] bulk-deleted {} config(s) + {} timeframe row(s) + {} trade row(s); "
                        + "skippedOpen={}; dates={}",
                deletable.size(), removedTimeframes, removedTradeOrders,
                skippedIds.size(), byDate.keySet());

        return new AutoDeleteResultDTO(
                matches.size(), deletable.size(), removedTimeframes, byDate, ids,
                tradedIds.size(), removedTradeOrders,
                skippedIds.size(), skippedIds, false,
                summary(matches.size(), deletable.size(), skippedIds.size(),
                        removedTradeOrders, false));
    }

    /**
     * @param removedTradeOrders trade rows that went (or, on a dry run, would
     *                           go) with the configs — deletion cascades the
     *                           ledger since 2026-08-31.
     */
    private String summary(long matched, long deletable, long skipped,
                           long removedTradeOrders, boolean dryRun) {
        if (matched == 0) {
            return "No auto-generated configs matched the selection.";
        }
        String verb = dryRun ? "Would delete" : "Deleted";
        String base = verb + " " + deletable + " of " + matched + " matched config(s)";
        if (removedTradeOrders > 0) {
            base += " and " + removedTradeOrders + " linked trade_order row(s)";
        }
        if (skipped > 0) {
            return base + "; " + skipped + " skipped — OPEN trade(s) attached (force-close them first).";
        }
        return base + ".";
    }

    /* ---------------- bulk update: one field-set across many configs ---------------- */

    /**
     * Applies one set of field values to every config matching the selector, in
     * a single transaction — the "retune every AUTO config's SL / target at
     * once" provision. {@code null} fields are left untouched on every row, so
     * a request naming only {@code slPct} is a one-column patch.
     *
     * <p>Shares the bulk-delete panel's contract: {@code source} defaults to
     * {@code AUTO_DOWNTREND} so hand-written configs need an explicit opt-in,
     * and {@code dryRun} defaults to {@code true} so the count confirmed in the
     * UI is the server's own.</p>
     *
     * <p><b>No open-trade confirmation, deliberately.</b> Every field this
     * accepts is either snapshotted onto {@code trade_order} at entry (the
     * whole bracket — changesets 011/036) or an entry gate (the premium band,
     * {@code maxLoss}), so applying it mid-day cannot re-price an open
     * position; the same reasoning keeps these fields out of
     * {@link #consequentialChanges}. Fields that <i>would</i> affect open
     * trades (side, quantities, caps, strategy) are not offered here at all —
     * that is what the single-config edit and its confirm dialog are for.</p>
     *
     * <p><b>Side effect worth knowing:</b> every updated row gets a fresh
     * {@code updated_date} (the {@code @PreUpdate} stamp), so the bulk-delete
     * panel's "generation run" clustering will show this edit as its own run.
     * That is honest — the rows were rewritten — but it means UPDATED_RANGE
     * selections made from a pre-edit runs list no longer match these rows.</p>
     */
    @Transactional
    public BulkUpdateResultDTO bulkUpdate(BulkUpdateRequestDTO request) {
        if (request == null) throw new IllegalArgumentException("request payload missing");
        if ((request.getFromDate() == null) != (request.getToDate() == null)) {
            throw new IllegalArgumentException("fromDate and toDate must be set together (or both omitted)");
        }
        if (request.getFromDate() != null && request.getToDate().isBefore(request.getFromDate())) {
            throw new IllegalArgumentException("toDate must not be before fromDate");
        }

        List<String> changes = describeAssignments(request);
        if (changes.isEmpty()) {
            throw new IllegalArgumentException(
                    "Nothing to update — set at least one field (target, stopLoss, targetPct, slPct, "
                            + "maxSlPoints, maxLoss, minOptionPrice, maxOptionPrice, trailLadder)");
        }
        validateBulkValues(request);

        AutoDeleteRequestDTO.Source src = request.getSource() == null
                ? AutoDeleteRequestDTO.Source.AUTO_DOWNTREND
                : request.getSource();

        List<TradeConfig> matches = matchForBulkUpdate(
                src, request.getStrategyId(), request.getFromDate(), request.getToDate());

        // Fail loudly on a row the patch would leave with an inverted premium
        // band — a config that can never trade while looking perfectly healthy.
        // Whole batch rejected rather than partially applied: this runs in one
        // transaction and a silent partial apply is the confusing outcome.
        if (request.getMinOptionPrice() != null || request.getMaxOptionPrice() != null) {
            for (TradeConfig tc : matches) {
                BigDecimal effMin = request.getMinOptionPrice() != null
                        ? request.getMinOptionPrice() : tc.getMinOptionPrice();
                BigDecimal effMax = request.getMaxOptionPrice() != null
                        ? request.getMaxOptionPrice() : tc.getMaxOptionPrice();
                if (effMin != null && effMax != null && effMax.compareTo(effMin) < 0) {
                    throw new IllegalArgumentException(
                            "Update would leave config " + tc.getId() + " with an inverted premium band ("
                                    + effMin + " > " + effMax + ") — nothing was changed");
                }
            }
        }

        Map<LocalDate, Long> byDate = new TreeMap<>();
        for (TradeConfig tc : matches) {
            byDate.merge(tc.getTradingDate(), 1L, Long::sum);
        }
        List<Integer> ids = matches.stream().map(TradeConfig::getId).toList();

        if (request.isDryRun()) {
            return new BulkUpdateResultDTO(matches.size(), 0, byDate, ids, changes, true,
                    bulkUpdateSummary(matches.size(), changes, true));
        }

        String canonicalLadder = request.getTrailLadder() == null
                ? null : TrailLadder.canonical(request.getTrailLadder());
        for (TradeConfig tc : matches) {
            if (request.getTarget() != null) tc.setTarget(request.getTarget());
            if (request.getStopLoss() != null) tc.setStopLoss(request.getStopLoss());
            if (request.getTargetPct() != null) tc.setTargetPct(request.getTargetPct());
            if (request.getSlPct() != null) tc.setSlPct(request.getSlPct());
            if (request.getMaxSlPoints() != null) tc.setMaxSlPoints(request.getMaxSlPoints());
            if (request.getMaxLoss() != null) tc.setMaxLoss(request.getMaxLoss());
            if (request.getMinOptionPrice() != null) tc.setMinOptionPrice(request.getMinOptionPrice());
            if (request.getMaxOptionPrice() != null) tc.setMaxOptionPrice(request.getMaxOptionPrice());
            // Blank means "remove the ladder" (fixed stop applies), null means
            // keep — the canonical() call maps blank to null for us, but only a
            // non-null request field reaches the setter at all.
            if (request.getTrailLadder() != null) tc.setTrailLadder(canonicalLadder);
        }
        tradeConfigRepository.saveAll(matches);

        // Same cache refresh every other mutation performs, once per affected
        // date — skipping it is exactly the "persisted but invisible until
        // restart" trap the CLAUDE.md invariant warns about.
        byDate.keySet().forEach(this::afterMutation);

        log.info("[trade-config] bulk-updated {} config(s) (source={}, strategy={}, window={}..{}): {}",
                matches.size(), src, request.getStrategyId(),
                request.getFromDate(), request.getToDate(), changes);

        return new BulkUpdateResultDTO(matches.size(), matches.size(), byDate, ids, changes, false,
                bulkUpdateSummary(matches.size(), changes, false));
    }

    /**
     * The bulk-update selector, shared by {@link #bulkUpdate} and
     * {@link #bulkUpdatePrefill} so the set the panel prefils from is exactly
     * the set an apply would write. Strategy resolution matches dispatch:
     * {@code strategy_ids} tags, or the primary {@code stratergy_id} when
     * untagged.
     */
    private List<TradeConfig> matchForBulkUpdate(AutoDeleteRequestDTO.Source source,
                                                 Integer strategyId,
                                                 LocalDate fromDate, LocalDate toDate) {
        List<TradeConfig> matches = fromDate == null
                ? tradeConfigRepository.findBySource(source.name())
                : tradeConfigRepository.findBySourceAndTradingDateBetween(source.name(), fromDate, toDate);

        if (strategyId != null) {
            matches = matches.stream()
                    .filter(tc -> {
                        List<Integer> tags = StrategyIds.parse(tc.getStrategyIds());
                        return tags.isEmpty()
                                ? strategyId.equals(tc.getStratergyId())
                                : tags.contains(strategyId);
                    })
                    .toList();
        }
        return matches;
    }

    /**
     * What the bulk-edit panel prefils its fields with: for each editable
     * field, the value <b>every</b> matched config shares — absent when the
     * fleet disagrees (reported in {@code mixedFields}) or when every row is
     * null. Numbers are compared by value, not scale, so {@code 0.30} and
     * {@code 0.3000} read as one shared value.
     *
     * <p>Exists because editing blind was the panel's real flaw: blank-means-
     * unchanged is the right <i>write</i> semantic, but the operator still
     * needs to see what the fleet currently holds before deciding what to
     * change. The UI pairs this with dirty-tracking — a prefilled value that
     * comes back unedited is not sent, so prefill does not turn every apply
     * into a nine-field rewrite.</p>
     */
    public BulkUpdatePrefillDTO bulkUpdatePrefill(AutoDeleteRequestDTO.Source source,
                                                  Integer strategyId) {
        AutoDeleteRequestDTO.Source src = source == null
                ? AutoDeleteRequestDTO.Source.AUTO_DOWNTREND : source;
        List<TradeConfig> matches = matchForBulkUpdate(src, strategyId, null, null);

        Map<String, String> values = new LinkedHashMap<>();
        List<String> mixed = new ArrayList<>();
        prefillField(matches, "target", tc -> plain(tc.getTarget()), values, mixed);
        prefillField(matches, "stopLoss", tc -> plain(tc.getStopLoss()), values, mixed);
        prefillField(matches, "targetPct", tc -> plain(tc.getTargetPct()), values, mixed);
        prefillField(matches, "slPct", tc -> plain(tc.getSlPct()), values, mixed);
        prefillField(matches, "maxSlPoints", tc -> plain(tc.getMaxSlPoints()), values, mixed);
        prefillField(matches, "maxLoss", tc -> plain(tc.getMaxLoss()), values, mixed);
        prefillField(matches, "minOptionPrice", tc -> plain(tc.getMinOptionPrice()), values, mixed);
        prefillField(matches, "maxOptionPrice", tc -> plain(tc.getMaxOptionPrice()), values, mixed);
        prefillField(matches, "trailLadder",
                tc -> tc.getTrailLadder() == null || tc.getTrailLadder().isBlank()
                        ? null : tc.getTrailLadder().trim(),
                values, mixed);

        return new BulkUpdatePrefillDTO(matches.size(), values, mixed);
    }

    /** Scale-free rendering so 0.30 and 0.3000 count as the same shared value. */
    private static String plain(BigDecimal v) {
        return v == null ? null : v.stripTrailingZeros().toPlainString();
    }

    /**
     * Folds one field across the matched set: a value every row shares goes in
     * {@code values}; disagreement lands the field in {@code mixed}; all-null
     * (or an empty set) contributes nothing — the input stays blank either way.
     */
    private static void prefillField(List<TradeConfig> matches, String field,
                                     java.util.function.Function<TradeConfig, String> extractor,
                                     Map<String, String> values, List<String> mixed) {
        boolean first = true;
        String common = null;
        for (TradeConfig tc : matches) {
            String v = extractor.apply(tc);
            if (first) {
                common = v;
                first = false;
            } else if (!Objects.equals(common, v)) {
                mixed.add(field);
                return;
            }
        }
        if (!first && common != null) {
            values.put(field, common);
        }
    }

    /** The non-null assignments a bulk update carries, rendered for the confirm dialog. */
    private static List<String> describeAssignments(BulkUpdateRequestDTO r) {
        List<String> changes = new ArrayList<>();
        if (r.getTarget() != null) changes.add("target = " + r.getTarget());
        if (r.getStopLoss() != null) changes.add("stopLoss = " + r.getStopLoss());
        if (r.getTargetPct() != null) changes.add("targetPct = " + r.getTargetPct());
        if (r.getSlPct() != null) changes.add("slPct = " + r.getSlPct());
        if (r.getMaxSlPoints() != null) changes.add("maxSlPoints = " + r.getMaxSlPoints());
        if (r.getMaxLoss() != null) changes.add("maxLoss = " + r.getMaxLoss());
        if (r.getMinOptionPrice() != null) changes.add("minOptionPrice = " + r.getMinOptionPrice());
        if (r.getMaxOptionPrice() != null) changes.add("maxOptionPrice = " + r.getMaxOptionPrice());
        if (r.getTrailLadder() != null) {
            changes.add(r.getTrailLadder().isBlank()
                    ? "trailLadder removed (fixed stop applies)"
                    : "trailLadder = " + r.getTrailLadder());
        }
        return changes;
    }

    /** Same value rules the single-config form enforces — one field-set, one rulebook. */
    private static void validateBulkValues(BulkUpdateRequestDTO r) {
        BigDecimal targetPct = r.getTargetPct();
        if (targetPct != null && (targetPct.signum() <= 0 || targetPct.compareTo(BigDecimal.ONE) >= 0)) {
            throw new IllegalArgumentException(
                    "targetPct (" + targetPct + ") must be between 0 and 1 exclusive — it is a fraction "
                            + "of entry premium, and a short leg cannot gain more than the premium sold");
        }
        if (r.getSlPct() != null && r.getSlPct().signum() <= 0) {
            throw new IllegalArgumentException("slPct (" + r.getSlPct() + ") must be positive");
        }
        if (r.getMaxSlPoints() != null && r.getMaxSlPoints().signum() <= 0) {
            throw new IllegalArgumentException("maxSlPoints (" + r.getMaxSlPoints()
                    + ") must be positive — it is a ceiling in premium points, and a zero or "
                    + "negative ceiling would stop every trade out on entry");
        }
        if (r.getMinOptionPrice() != null && r.getMinOptionPrice().signum() < 0) {
            throw new IllegalArgumentException("minOptionPrice must not be negative");
        }
        if (r.getMaxOptionPrice() != null && r.getMaxOptionPrice().signum() < 0) {
            throw new IllegalArgumentException("maxOptionPrice must not be negative");
        }
        // Throws with the offending rung named — same gate the form goes through.
        TrailLadder.parse(r.getTrailLadder());
    }

    private static String bulkUpdateSummary(long matched, List<String> changes, boolean dryRun) {
        if (matched == 0) {
            return "No configs matched the selection.";
        }
        return (dryRun ? "Would update " : "Updated ") + matched + " config(s): "
                + String.join("; ", changes) + ".";
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
        // An inverted band matches nothing, so the config would silently never
        // trade. Reject it here rather than let it look like a dead strategy.
        BigDecimal min = form.getMinOptionPrice();
        BigDecimal max = form.getMaxOptionPrice();
        if (min != null && min.signum() < 0) {
            throw new IllegalArgumentException("minOptionPrice must not be negative");
        }
        if (max != null && max.signum() < 0) {
            throw new IllegalArgumentException("maxOptionPrice must not be negative");
        }
        if (min != null && max != null && max.compareTo(min) < 0) {
            throw new IllegalArgumentException(
                    "maxOptionPrice (" + max + ") must not be below minOptionPrice (" + min + ")");
        }
        // A percentage bracket is a fraction, not a display percentage: 0.2 = 20%.
        // A target at or above 1.0 needs the premium to reach zero intraday, which
        // for a short leg means the trade can only ever stop out.
        BigDecimal targetPct = form.getTargetPct();
        BigDecimal slPct = form.getSlPct();
        if (targetPct != null && (targetPct.signum() <= 0 || targetPct.compareTo(BigDecimal.ONE) >= 0)) {
            throw new IllegalArgumentException(
                    "targetPct (" + targetPct + ") must be between 0 and 1 exclusive — it is a fraction "
                            + "of entry premium, and a short leg cannot gain more than the premium sold");
        }
        if (slPct != null && slPct.signum() <= 0) {
            throw new IllegalArgumentException("slPct (" + slPct + ") must be positive");
        }
        BigDecimal maxSlPoints = form.getMaxSlPoints();
        if (maxSlPoints != null && maxSlPoints.signum() <= 0) {
            throw new IllegalArgumentException("maxSlPoints (" + maxSlPoints
                    + ") must be positive — it is a ceiling in premium points, and a zero or "
                    + "negative ceiling would stop every trade out on entry");
        }
        // Throws with the offending rung named. Rejecting here is the whole reason
        // OrderService can treat a malformed ladder as "hand-edited in SQL".
        TrailLadder.parse(form.getTrailLadder());
    }

    private void applyForm(TradeConfig tc, TradeConfigFormDTO form) {
        // Read before the setter below overwrites it. Null on create, the stored
        // value on edit — which is what tells syncPrimaryStrategyId whether the
        // user actually changed the strategy dropdown.
        Integer previousPrimary = tc.getStratergyId();

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
        // Null from the form (blank input, or a client that predates the
        // field) means KEEP the current value — never write null into the
        // NOT NULL column, and never silently reset a widened cap to 1. New
        // entities are born with the safe default via the entity initialiser.
        if (form.getMaxParallelPerSide() != null) {
            tc.setMaxParallelPerSide(form.getMaxParallelPerSide());
        }
        tc.setItmDepth(form.getItmDepth());
        tc.setOtmDepth(form.getOtmDepth());
        tc.setAtmDepth(form.getAtmDepth());
        // Unset means "use the standing band", not "unbounded" — an unbounded
        // config is what produced 6-point entries with a 30-point target.
        tc.setMinOptionPrice(form.getMinOptionPrice() != null
                ? form.getMinOptionPrice() : DEFAULT_MIN_OPTION_PRICE);
        tc.setMaxOptionPrice(form.getMaxOptionPrice() != null
                ? form.getMaxOptionPrice() : DEFAULT_MAX_OPTION_PRICE);

        // Unlike the band, blank here really does mean "no percentage" — the
        // absolute target / stopLoss above then apply, which is how every config
        // predating changeset 027 behaves.
        tc.setTargetPct(form.getTargetPct());
        tc.setSlPct(form.getSlPct());

        // Blank = the standing cap, matching the premium band above: this column
        // bounds loss, so "the user cleared the field" must not resolve to
        // "unbounded". Removing the cap entirely is a deliberate DB edit.
        tc.setMaxSlPoints(form.getMaxSlPoints() != null
                ? form.getMaxSlPoints() : DEFAULT_MAX_SL_POINTS);
        // Blank here does mean off — a config with no ladder simply keeps its
        // fixed stop, which is safe, so the form is allowed to say it. Stored
        // canonicalised so the column never carries the spacing someone typed.
        tc.setTrailLadder(TrailLadder.canonical(form.getTrailLadder()));

        // trade_config.source is NOT NULL (changeset 019) and Hibernate writes the
        // column explicitly, so the DB's DEFAULT 'MANUAL' never applies — leaving
        // it unset made every create through this service fail with a constraint
        // violation. Only stamp it when absent: an edit of a generated config must
        // keep its AUTO_DOWNTREND marker, or the detector loses its dedupe key and
        // the bulk-delete panel stops seeing the row.
        if (tc.getSource() == null || tc.getSource().isBlank()) {
            tc.setSource(SOURCE_MANUAL);
        }

        tc.setStrategyIds(syncPrimaryStrategyId(
                tc.getStrategyIds(), previousPrimary, form.getStrategyId()));
    }

    /**
     * Keeps {@code strategy_ids} in step with the single strategy the form carries,
     * <b>without disturbing any other id in the column</b>.
     *
     * <p>The two sides have different owners and this is the seam between them.
     * Running a config under several strategies is a DB-level edit (append an id to
     * {@code strategy_ids}); the admin form still edits one strategy, the one
     * mirrored in {@code trade_config.stratergy_id}. So:</p>
     *
     * <ul>
     *   <li><b>Blank column</b> — set it to the form's strategy. Covers create, and
     *       configs written before the column existed.</li>
     *   <li><b>Strategy unchanged</b> — leave the column alone. This is the common
     *       edit (someone adjusts a target) and it must not touch the list at all.</li>
     *   <li><b>Strategy changed</b> — swap the old primary for the new one and keep
     *       every other id. {@link StrategyIds} de-duplicates, so moving the primary
     *       onto an id that is already listed collapses to a single entry rather
     *       than doubling it.</li>
     * </ul>
     *
     * <p>Deliberately not a blanket overwrite: that would silently discard
     * hand-added ids on the next unrelated UI edit, which is exactly the drift this
     * feature exists to remove.</p>
     */
    private static String syncPrimaryStrategyId(String csv, Integer previousPrimary, Integer newPrimary) {
        if (newPrimary == null) {
            return csv;
        }
        List<Integer> existing = StrategyIds.parse(csv);
        if (existing.isEmpty()) {
            return StrategyIds.format(List.of(newPrimary));
        }
        if (Objects.equals(previousPrimary, newPrimary)) {
            return StrategyIds.format(existing);
        }
        return StrategyIds.without(StrategyIds.with(csv, newPrimary), previousPrimary);
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
        // Everything the form can edit has to come back out, or reopening a config
        // and saving it writes the blank the form was rendered with. These six were
        // missing: target_pct / sl_pct / the premium band were being cleared on
        // every edit through the UI, and the list's bracket column rendered points
        // only. Fixed here alongside the two new columns, which would otherwise
        // have inherited the same bug.
        v.setTargetPct(tc.getTargetPct());
        v.setSlPct(tc.getSlPct());
        v.setMinOptionPrice(tc.getMinOptionPrice());
        v.setMaxOptionPrice(tc.getMaxOptionPrice());
        v.setMaxSlPoints(tc.getMaxSlPoints());
        v.setTrailLadder(tc.getTrailLadder());
        v.setMaxParallelPerSide(tc.getMaxParallelPerSide());
        v.setSource(tc.getSource());
        v.setUpdatedDate(tc.getUpdatedDate());
        // Null on rows written before changeset 037 reads as active, matching the
        // COALESCE in fetchCombinedByTradingDate: the list must not show a config
        // as retired that dispatch is still running.
        v.setActive(tc.getIsActive() == null || tc.getIsActive());
        v.setMaxLoss(tc.getMaxLoss());
        v.setOptionDepth(tc.getOptionDepth());
        v.setLotQuantity(tc.getLotQuantity());
        v.setStrategyId(tc.getStratergyId());
        // Every strategy the config actually runs under, not just the primary one.
        // Falls back to the primary when the column is blank, mirroring the
        // dispatch fallback in TradeConfigScheduler.
        List<Integer> tagIds = StrategyIds.parse(tc.getStrategyIds());
        v.setStrategyIds(tagIds.isEmpty() && tc.getStratergyId() != null
                ? List.of(tc.getStratergyId())
                : tagIds);

        List<SmaTimeframe> rows = (tc.getId() == null)
                ? List.of()
                : smaTimeframeRepository.findByTradeConfigId(tc.getId());
        v.setTimeframes(rows.stream()
                .map(r -> new SmaTimeframeDTO(r.getId(), r.getTimePeriod(), r.getSma(), r.getSlope()))
                .toList());
        return v;
    }
}
