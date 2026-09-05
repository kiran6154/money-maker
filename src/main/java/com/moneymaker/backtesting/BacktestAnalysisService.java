package com.moneymaker.backtesting;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.login.service.BrokerSessionStore;
import com.moneymaker.market.exception.HistoricalDataMissingException;
import com.moneymaker.journal.JournalRecorder;
import com.moneymaker.market.service.TradingCalendar;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.AnalysisScheduler;
import com.moneymaker.scheduler.OrderScheduler;
import com.moneymaker.scheduler.PositionScheduler;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import com.zerodhatech.kiteconnect.KiteConnect;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Slf4j
@Service
public class BacktestAnalysisService {

    private final TradeConfigScheduler tradeConfigScheduler;
    private final AnalysisScheduler analysisScheduler;
    private final OrderScheduler orderScheduler;
    private final PositionScheduler positionScheduler;
    private final OrderService orderService;
    private final TradeOrderRepository tradeOrderRepository;
    private final BrokerSessionStore brokerSessionStore;
    private final KiteConnect sharedKiteConnect;
    private final NotificationService notifier;
    private final BacktestMarketDataCache marketDataCache;
    private final TradingCalendar tradingCalendar;
    private final JournalRecorder journal;
    private final com.moneymaker.market.service.MarketHoursService marketHours;

    /**
     * Used only by {@link #detachEverythingLoadedThisTick()}. Field-injected
     * rather than constructor-injected so the eleven existing constructor call
     * sites - including tests - stay untouched by a purely internal concern.
     */
    @jakarta.persistence.PersistenceContext
    private jakarta.persistence.EntityManager entityManager;

    // Phase 7 instrumentation: per-day wall time by pipeline phase, reset at
    // each day's start and printed on the day-done line. The replay is
    // single-threaded, so plain fields are safe.
    private long dayIndicatorNs;
    private long dayStrategyNs;
    private long dayOrdersNs;
    private long dayPositionsNs;
    private int dayTicks;

    public BacktestAnalysisService(
            TradeConfigScheduler tradeConfigScheduler,
            AnalysisScheduler analysisScheduler,
            OrderScheduler orderScheduler,
            PositionScheduler positionScheduler,
            OrderService orderService,
            TradeOrderRepository tradeOrderRepository,
            BrokerSessionStore brokerSessionStore,
            @Qualifier("sharedKiteConnect") KiteConnect sharedKiteConnect,
            NotificationService notifier,
            BacktestMarketDataCache marketDataCache,
            TradingCalendar tradingCalendar,
            JournalRecorder journal,
            com.moneymaker.market.service.MarketHoursService marketHours) {
        this.tradeConfigScheduler = tradeConfigScheduler;
        this.analysisScheduler = analysisScheduler;
        this.orderScheduler = orderScheduler;
        this.positionScheduler = positionScheduler;
        this.orderService = orderService;
        this.tradeOrderRepository = tradeOrderRepository;
        this.brokerSessionStore = brokerSessionStore;
        this.sharedKiteConnect = sharedKiteConnect;
        this.notifier = notifier;
        this.marketDataCache = marketDataCache;
        this.tradingCalendar = tradingCalendar;
        this.journal = journal;
        this.marketHours = marketHours;
    }

    /**
     * Replay every strategy tagged on the window's configs. Config generation
     * lives in a different domain entirely ({@code tradeconfig.generation},
     * user decision 2026-08-31) — a replay consumes configs and has no code
     * path that writes one, so a measurement run structurally cannot mutate
     * the config set it is measuring.
     */
    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate) {
        return run(fromDate, toDate, null);
    }

    /**
     * Replay scoped to the given strategy ids ({@code null} or empty = all).
     * The filter is applied to the per-day {@code (config, strategy)} fan-out
     * before it reaches {@code SharedData.combinedDto}, so every downstream
     * stage — fetch, dispatch, orders, positions — sees only the scoped pairs.
     */
    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate, Set<Integer> strategyIds) {
        return run(fromDate, toDate, strategyIds, null);
    }

    /**
     * Replay scoped to strategies <i>and</i> to specific {@code trade_config}
     * ids ({@code null} or empty = all, for either). The two compose: a
     * {@code (config, strategy)} pair survives only when the strategy is in
     * {@code strategyIds} and the config's id is in {@code configIds}. This is
     * what lets a run measure one strategy against a hand-picked subset of the
     * generated (or manual) configs rather than everything on the window's
     * dates. Config ids outside the window simply match nothing — no error.
     */
    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate,
                                 Set<Integer> strategyIds, Set<Integer> configIds) {
        return run(fromDate, toDate, strategyIds, configIds, null);
    }

    /**
     * Cross-run variant (user request 2026-08-31: "strategy 1 can be run
     * against strategy 2's auto configs"). When {@code configStrategyId} is
     * set, the day's config set is <b>that strategy's configs</b> — every
     * config tagged with it (or carrying it as primary) — and each strategy in
     * {@code strategyIds} runs against <i>all</i> of them, regardless of the
     * configs' own tags. The normal tag-driven fan-out is replaced, not
     * filtered: this is how a strategy is measured on a config set that was
     * generated for a different one.
     *
     * <p>{@code strategyIds} must be non-empty in this mode — the whole point
     * is naming the runner. Ledger note: rows land under the <i>run</i>
     * strategy's id on the borrowed config's id, so caps and dedupe still key
     * on {@code (configId, runStrategyId)} and a cross ledger is directly
     * comparable to that strategy's normal run — but nothing on the row says
     * the config set was borrowed. Wipe the ledger between compare runs, as
     * for any same-window rerun.</p>
     */
    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate,
                                 Set<Integer> strategyIds, Set<Integer> configIds,
                                 Integer configStrategyId) {
        if (configStrategyId != null && (strategyIds == null || strategyIds.isEmpty())) {
            throw new IllegalArgumentException(
                    "configStrategyId=" + configStrategyId + " needs at least one strategy in "
                            + "strategyIds — pick which strategy should run against that config set");
        }
        if (fromDate == null) {
            throw new IllegalArgumentException("fromDate must not be null");
        }
        if (toDate == null) {
            throw new IllegalArgumentException("toDate must not be null");
        }
        if (fromDate.isAfter(toDate)) {
            throw new IllegalArgumentException("fromDate must be on or before toDate");
        }

        Instant startedAt = Instant.now();
        List<BacktestDayResult> results = new ArrayList<>();

        // Phase 9a: the broker session is read ONCE per run, not once per tick.
        // It cannot change mid-replay (nothing in backtest mode writes it), and
        // reading it inside runForDate cost one DB round trip per tick — ~18k
        // queries on a year run — plus a per-tick token re-set on the shared
        // KiteConnect. A missing/invalid session aborts the run up front with
        // one alert instead of one warning per tick.
        var sessionEntity = brokerSessionStore.currentEntity();
        if (sessionEntity.isEmpty()) {
            log.error("[Backtest] No active broker session — aborting run {}..{}", fromDate, toDate);
            notifier.alertNoActiveSession("backtest run " + fromDate + ".." + toDate);
            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            return new BacktestRunResult(fromDate, toDate, 0, 0, durationMs, List.of());
        }
        var session = sessionEntity.get();
        String accessToken = session.getAccessToken();
        if (accessToken == null || accessToken.isEmpty()) {
            log.error("[Backtest] Broker session has no access token — aborting run {}..{}", fromDate, toDate);
            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            return new BacktestRunResult(fromDate, toDate, 0, 0, durationMs, List.of());
        }
        sharedKiteConnect.setAccessToken(accessToken);
        if (session.getPublicToken() != null && !session.getPublicToken().isEmpty()) {
            sharedKiteConnect.setPublicToken(session.getPublicToken());
        }
        SharedData.sharedKiteconnect = sharedKiteConnect;
        log.debug("[Backtest] KiteConnect initialized once for user {} (run {}..{})",
                session.getUserId(), fromDate, toDate);

        // Names every observation this run produces, so two runs over the same
        // dates stay separable in journal_observation instead of merging into one
        // indistinguishable pile.
        journal.beginRun("bt-" + fromDate + "_" + toDate + "-" + startedAt.toEpochMilli());

        // Replay bounds come from MarketHoursService — the declared source of
        // truth for the session window — as open/close plus the
        // app.market.replay-*-offset-minutes keys (defaults reproduce the old
        // 09:20 / 15:20 constants exactly). The early stop at the last tick is
        // the de-facto broker square-off cutoff for index options: closes at
        // 15:30 (the hard market close) get rejected by most brokers in live
        // mode, and SEBI's 5-minute pre-close auction distorts last-tick prices.
        LocalTime marketStart = marketHours.replayFirstTick();
        LocalTime marketEnd = marketHours.replayLastTick();

        // Loop through each date. Configs and time-periods are fetched *per day*
        // — the same way the live 09:16 cron does it. A 50-day run does NOT
        // pre-fetch all 50 days' configs upfront; each iteration of this loop
        // is a "trading day" in isolation.
        LocalDate currentDate = fromDate;
        while (!currentDate.isAfter(toDate)) {
            LocalDateTime currentDateTime = LocalDateTime.of(currentDate, marketStart);
            LocalDateTime dateEnd = LocalDateTime.of(currentDate, marketEnd);

            // Non-sessions are skipped before anything else. This is the calendar
            // the data reports, not Mon-Fri: a market holiday would otherwise be
            // "replayed" against whatever candles the lookback window ends on —
            // the previous session's — and a special Saturday session would be
            // dropped even though it has candles.
            if (!tradingCalendar.isTradingDay(currentDate)) {
                log.debug("[Backtest] day={} — not a trading day, skipping", currentDate);
                currentDate = currentDate.plusDays(1);
                continue;
            }

            // ===== Day-start: fetch this day's config (live cron equivalent) =====
            List<TradeConfigCombinedDTO> combinedDto = tradeConfigScheduler.getConfigsForDate(currentDate);

            // Cross-run: replace the tag-driven fan-out with configStrategyId's
            // config set, re-badged onto each run strategy. Mutually exclusive
            // with the plain scope filter below — in cross mode strategyIds
            // names the runners, not a filter on the configs' own tags.
            if (configStrategyId != null) {
                List<TradeConfigCombinedDTO> crossed =
                        crossStrategies(combinedDto, configStrategyId, strategyIds);
                log.info("[Backtest] day={} cross-run: strategies {} against strategy {}'s configs "
                                + "— {} (config, strategy) pairs from {} fan-out rows",
                        currentDate, strategyIds, configStrategyId, crossed.size(), combinedDto.size());
                combinedDto = crossed;
            }
            // Strategy scoping: keep only the (config, strategy) pairs whose
            // strategyId was requested. Valid because every cap and dedupe rule
            // downstream is keyed on (tradeConfigId, strategyId) — strategies do
            // not compete for each other's slots — so a scoped run's ledger is
            // the same rows that strategy would have produced inside a full run.
            else if (strategyIds != null && !strategyIds.isEmpty()) {
                List<TradeConfigCombinedDTO> scoped = combinedDto.stream()
                        .filter(dto -> dto != null && dto.getStrategyId() != null
                                && strategyIds.contains(dto.getStrategyId()))
                        .toList();
                log.info("[Backtest] day={} strategy scope {} keeps {} of {} (config, strategy) pairs",
                        currentDate, strategyIds, scoped.size(), combinedDto.size());
                combinedDto = scoped;
            }

            // Config scoping: keep only the pairs whose trade_config id was
            // requested. Same soundness argument as the strategy scope above —
            // caps and dedupe are keyed per (tradeConfigId, strategyId), so
            // configs do not compete for each other's slots and a scoped run's
            // ledger matches what those configs produce inside a full run.
            if (configIds != null && !configIds.isEmpty()) {
                List<TradeConfigCombinedDTO> scoped = combinedDto.stream()
                        .filter(dto -> dto != null && dto.getTradeConfig() != null
                                && dto.getTradeConfig().getId() != null
                                && configIds.contains(dto.getTradeConfig().getId()))
                        .toList();
                log.info("[Backtest] day={} config scope keeps {} of {} (config, strategy) pairs",
                        currentDate, scoped.size(), combinedDto.size());
                combinedDto = scoped;
            }
            Set<Integer> timePeriodsMinutes = uniqueTimePeriodsFor(combinedDto);

            // No config means no trading today — it does NOT mean skip the day.
            // End-of-day detection decides whether to trade *tomorrow*, and that
            // question is independent of whether we happened to trade today.
            // Gating it on today's config made a single empty day terminal: with
            // AUTO_DOWNTREND configs only ever written by the previous day's
            // detection, one day without one meant detection never ran again and
            // every later day was skipped too. A 31-day range stopped after 5.
            boolean canTrade = !combinedDto.isEmpty() && !timePeriodsMinutes.isEmpty();
            if (!canTrade) {
                log.info("[Backtest] day={} — no active configs, no trading; running end-of-day detection only",
                        currentDate);
            }

            // Count rows already in trade_order for this date so the end-of-day
            // summary can show the *delta* this run produced, not the cumulative total.
            long rowsBefore = countTradeOrdersOnDate(currentDate);
            Instant dayStart = Instant.now();
            dayIndicatorNs = dayStrategyNs = dayOrdersNs = dayPositionsNs = 0;
            dayTicks = 0;

            // ===== Phase 1: enable per-day candle cache =====
            // MarketDataService now slices the cached series for every tick's
            // fetchHistoricalData call. First call per (symbol, interval) does
            // a single broker fetch over the wide [dayFrom, dayTo] window; the
            // remaining ~71 ticks for that pair are slice-only. Live mode is
            // unaffected — the cache stays inactive outside backtest.
            int lookbackDays = analysisScheduler.computeLookbackCalendarDays();
            LocalDateTime dayFrom = LocalDateTime.of(currentDate, marketStart).minusDays(lookbackDays);
            LocalDateTime dayTo   = LocalDateTime.of(currentDate, marketEnd);
            marketDataCache.beginDay(dayFrom, dayTo);

            log.info("[Backtest] day={} starting (configs={}, time-periods={}, cache window={}..{})",
                    currentDate, combinedDto.size(), timePeriodsMinutes, dayFrom, dayTo);

            int forceClosed = 0;
            long rowsAfter;
            try {
                if (canTrade) {
                    // Log + telegram the active configs for this trading date — once per date.
                    tradeConfigScheduler.reportConfigsForDay(currentDate, combinedDto);

                    int tickMinutes = getSmallestTimePeriod(timePeriodsMinutes);
                    while (!currentDateTime.isAfter(dateEnd)) {
                        LocalDateTime tickAt = currentDateTime;
                        try {
                            BacktestDayResult result = runForDateTime(tickAt, combinedDto);
                            results.add(result);
                        } catch (HistoricalDataMissingException ex) {
                            // Deliberately not caught below: replaying an incomplete
                            // data set silently is worse than not replaying it. Abort
                            // the run so the gap is fixed rather than averaged over.
                            log.error("[Backtest] {} — aborting run: {}", tickAt, ex.getMessage());
                            throw ex;
                        } catch (Exception ex) {
                            // Surface the exception unambiguously and keep the loop alive
                            // so one bad tick doesn't abort the whole day — the run will
                            // still reach the "[Backtest] day=… done" / "completed" lines.
                            log.error("[Backtest] tick {} threw — continuing", tickAt, ex);
                        }
                        currentDateTime = currentDateTime.plusMinutes(tickMinutes);
                    }

                    // End-of-day cleanup: force-close any intraday position whose strike
                    // fell out of the active-strike set before the close-signal could fire.
                    try {
                        forceClosed = orderService.forceCloseOpenPositions(currentDate, dateEnd);
                        if (forceClosed > 0) {
                            log.info("[Backtest] {} — force-closed {} open intraday position(s) at {}",
                                    currentDate, forceClosed, dateEnd);
                        }
                    } catch (Exception ex) {
                        log.error("[Backtest] {} — force-close at end-of-day failed", currentDate, ex);
                    }
                }

                // End-of-day downtrend detection — auto-generates next-day
                // trade_config rows for every sma_downtrend_rule that passes.
                // Backtest-only today (no live scheduler wired). Idempotent:
                // skipped if AUTO_DOWNTREND rows already exist for the next day.
                //
                // OUTSIDE the canTrade branch on purpose: this is what lets the
                // auto-config chain restart after a day that generated nothing.
                // The detector is near-blind on the first day of an expiry cycle,
                // where the newly-nearest contract has only that morning's candles
                // (~75, so only the shortest SMA is computable) — that day often
                // writes no config, and before this it took the whole rest of the
                // run down with it.
                //
                // Runs against either data source: the detector resolves every
                // symbol through OptionInstrumentResolver, and the historical
                // provider now serves the "day" candles its ATR needs by rolling
                // up the imported 5-minute rows.
                rowsAfter = countTradeOrdersOnDate(currentDate);
            } finally {
                // Day-end wipe — runs after force-close, regardless of exceptions.
                // Every per-day cache/state container is cleared here so the next
                // backtest day (and any subsequent run of /api/backtest/analysis
                // in the same JVM) starts from a clean slate. Without this, leftover
                // entries in SharedData's strike maps cause Strategy1 to evaluate
                // stale strikes and — because ConcurrentHashMap iteration is
                // non-deterministic — picks a different "first" strike across runs
                // even for identical inputs.
                marketDataCache.endDay();
                // Clears the strike cache, the freshness stamps AND the
                // contract-id index together. Clearing the map alone would leave
                // the position monitor quoting a contract that is no longer
                // cached, which looks entirely normal in the ledger.
                SharedData.clearStrikeCaches();
                SharedData.marketDataByInstrumentAndInterval.clear();
                SharedData.tradeSignals.clear();
                // strike → option symbol, and the symbol encodes the expiry. Left
                // uncleared, a multi-day run that crosses an expiry keeps serving
                // the *previous* expiry's series for the same strike.
                SharedData.optionTokenMap.clear();
                log.debug("[Backtest] day={} — caches wiped (strikeMarketData, marketData, tradeSignals, optionTokenMap)",
                        currentDate);
            }
            long dayMs = Duration.between(dayStart, Instant.now()).toMillis();
            // DIAGNOSTIC (perf branch): SMA work split for the day.
            long smaCalls = com.moneymaker.indicator.SMAIndicatorImpl.CALLS.sumThenReset();
            long smaWarm = com.moneymaker.indicator.SMAIndicatorImpl.WARMUP_COMPUTED.sumThenReset();
            long smaFull = com.moneymaker.indicator.SMAIndicatorImpl.FULL_COMPUTED.sumThenReset();
            long smaReused = com.moneymaker.indicator.SMAIndicatorImpl.FULL_REUSED.sumThenReset();
            log.info("[Backtest] day={} done in {} ms — trade_order rows: before={} after={} delta={} forceClosed={} "
                            + "| phases ms: indicator={} strategy={} orders={} positions={} (ticks={}) "
                            + "| sma: calls={} warmup={} fullComputed={} fullReused={}",
                    currentDate, dayMs, rowsBefore, rowsAfter, rowsAfter - rowsBefore, forceClosed,
                    dayIndicatorNs / 1_000_000, dayStrategyNs / 1_000_000,
                    dayOrdersNs / 1_000_000, dayPositionsNs / 1_000_000, dayTicks,
                    smaCalls, smaWarm, smaFull, smaReused);

            currentDate = currentDate.plusDays(1);
        }

        // Drop any in-flight signals from the run so a subsequent backtest /
        // live tick starts with a clean queue. Persisted TradeOrder rows stay —
        // they are the backtest's output ledger.
        SharedData.tradeSignals.clear();

        // Flush the tail of the buffer; without this the last partial batch of a
        // run is lost, which is most of a short run.
        journal.endRun();

        long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
        long successCount = results.stream().filter(BacktestDayResult::success).count();
        return new BacktestRunResult(fromDate, toDate, results.size(), successCount, durationMs, results);
    }

    /**
     * The cross-run fan-out: {@code configStrategyId}'s config set × the run
     * strategies.
     *
     * <p>A config belongs to the set when any of its fan-out rows carries
     * {@code configStrategyId} — which, via {@code strategyIdsFor}'s fallback,
     * covers both tagged configs and untagged ones whose primary
     * {@code stratergy_id} matches. Each config is taken <b>once</b> (a config
     * tagged {@code "1,2"} contributes one template, not two) and re-badged
     * onto every run strategy, ascending, so a re-run writes the same pairs in
     * the same order. The siblings share the template's {@code TradeConfig} /
     * timeframe instances, same as the normal fan-out — nothing downstream
     * mutates them.</p>
     */
    // Package-private static: this is the whole semantic of the cross-run and
    // the only part of it unit-testable without standing up the replay loop.
    static List<TradeConfigCombinedDTO> crossStrategies(List<TradeConfigCombinedDTO> dtos,
                                                        int configStrategyId,
                                                        Set<Integer> runStrategyIds) {
        java.util.Map<Integer, TradeConfigCombinedDTO> templates = new java.util.LinkedHashMap<>();
        if (dtos != null) {
            for (TradeConfigCombinedDTO dto : dtos) {
                if (dto == null || dto.getTradeConfig() == null || dto.getTradeConfig().getId() == null) {
                    continue;
                }
                if (dto.getStrategyId() == null || dto.getStrategyId() != configStrategyId) {
                    continue;
                }
                templates.putIfAbsent(dto.getTradeConfig().getId(), dto);
            }
        }
        List<Integer> runners = runStrategyIds == null
                ? List.of()
                : runStrategyIds.stream().filter(java.util.Objects::nonNull).sorted().toList();

        List<TradeConfigCombinedDTO> crossed = new ArrayList<>();
        for (TradeConfigCombinedDTO template : templates.values()) {
            for (Integer runId : runners) {
                crossed.add(new TradeConfigCombinedDTO(
                        template.getTradeConfig(),
                        template.getInstrument(),
                        template.getInstrumentDetails(),
                        template.getTimeframes(),
                        runId));
            }
        }
        return crossed;
    }

    /**
     * Unique SMA-timeframe periods (in minutes) across the configs already
     * fetched for *one* trading day. Used by the per-day loop to size the
     * tick increment — no multi-day pre-fetch.
     */
    private Set<Integer> uniqueTimePeriodsFor(List<TradeConfigCombinedDTO> configs) {
        Set<Integer> periods = new HashSet<>();
        if (configs == null) return periods;
        for (TradeConfigCombinedDTO config : configs) {
            List<SmaTimeframe> timeframes = config.getTimeframes();
            if (timeframes == null) continue;
            for (SmaTimeframe timeframe : timeframes) {
                if (timeframe.getTimePeriod() != null) {
                    periods.add(timeframe.getTimePeriod());
                }
            }
        }
        return periods;
    }

    /**
     * Get the smallest time period to use as the base increment
     */
    private int getSmallestTimePeriod(Set<Integer> timePeriodsMinutes) {
        return timePeriodsMinutes.stream()
                .mapToInt(Integer::intValue)
                .min()
                .orElse(5); // Default to 5 minutes if no periods found
    }

    /**
     * Detaches every entity the tick loaded, so the persistence context does not
     * grow for the length of the run.
     *
     * <h3>Why this is needed</h3>
     * {@code spring.jpa.open-in-view} defaults to {@code true}, so a whole replay
     * - which is one long HTTP request - runs inside a <b>single Hibernate
     * session</b>. Every {@code TradeOrder} loaded by any tick stays managed in
     * it, and Hibernate dirty-checks the entire context on each flush. So
     * {@code tradeOrderRepository.save(order)} in {@code PositionService} gets
     * steadily slower as the run proceeds: quadratic in the number of rows the
     * run has touched.
     *
     * <p><b>Measured</b> (2026-09-05, seven Pressure books): the position phase
     * grew from 34 s on the replay's third day to 112 s by its fourteenth, at
     * which point a full year projected to well over twelve hours. Five
     * consecutive thread dumps landed on the same line -
     * {@code PositionService.handleOne}'s closing {@code save} - while
     * {@code performance_schema} attributed only ~1.4 s of SQL per 60 s of wall
     * time. Slow save, fast SQL, degrading within a run and resetting between
     * runs is the signature of exactly this. With the context cleared per tick
     * the same days run in 3.6-6.2 s and, more importantly, stop degrading.
     *
     * <h3>Why not simply set open-in-view=false</h3>
     * That is the more usual fix and it works - it was how this was first
     * diagnosed. It was rejected because it changes behaviour for the whole
     * application, including five Thymeleaf views that may touch a lazy
     * association after their controller returns, and a
     * {@code LazyInitializationException} there would surface at runtime in a
     * page no test covers. Clearing here is scoped to the replay by
     * construction: nothing outside this loop can be affected.
     *
     * <h3>Why it is safe here</h3>
     * The replay holds no entity across ticks. Every tick reloads what it needs -
     * {@code findByStatus("OPEN")} in the position and order paths,
     * {@code findConfig} from {@code SharedData} - so there is nothing for a
     * detach to break. It runs after the last write of the tick, so no pending
     * change can be discarded: {@code clear()} drops unflushed state, and the
     * position and order services both save through the repository, which
     * flushes on commit of their own transactions before returning here.
     */
    private void detachEverythingLoadedThisTick() {
        if (entityManager == null) return;
        try {
            entityManager.clear();
        } catch (Exception ex) {
            // Never let a housekeeping call take down a replay day. Losing the
            // clear costs speed, not correctness.
            log.debug("[Backtest] persistence-context clear failed - continuing: {}", ex.toString());
        }
    }

    private BacktestDayResult runForDateTime(LocalDateTime dateTime, List<TradeConfigCombinedDTO> combinedDto) {
        return runForDate(dateTime,combinedDto);
    }

    private BacktestDayResult runForDate(LocalDateTime date, List<TradeConfigCombinedDTO> combinedDto) {
        Instant startedAt = Instant.now();

        try {
            // Broker session + KiteConnect token setup happens once per run
            // (Phase 9a) — see run(). This method carries only per-tick work.
            SharedData.combinedDto = combinedDto;

            if (combinedDto == null || combinedDto.isEmpty()) {
                long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
                return new BacktestDayResult(date, true, 0, durationMs, "No trade config found.");
            }

            // ===== Per-tick narrative (DEBUG) =====
            // The block between START and END is the single tick: indicators →
            // strategy → orders → positions. Counters captured before/after so
            // the END line shows what *this* tick produced (delta), not totals.
            //
            // Gated on the log level: these four counts exist only to render the
            // END line's delta, and nothing else in this method reads them. At
            // INFO — which is what a benchmark or a long run should use — they
            // are four DB round trips per tick bought for nothing.
            boolean narrate = log.isDebugEnabled();
            long rowsBefore   = narrate ? safeCount() : 0L;
            long closedBefore = narrate ? safeCountClosed() : 0L;

            log.debug("=== Analysis {} START ===", date);

            // Phase 7: per-phase wall time, accumulated across the day's ticks
            // and reported on the day-done INFO line. Nanotime bookkeeping only;
            // the phases themselves are untouched.
            long t0 = System.nanoTime();
            try {
                analysisScheduler.calculateIndicator(date);
            }
            catch (HistoricalDataMissingException e) {
                // Never swallowed: a run replaying an incomplete data set would
                // produce a plausible but meaningless P&L. Abort the whole run.
                throw e;
            }
            catch(Exception e){
                log.error("[Backtest] calculateIndicator failed at {}", date, e);
            }
            long t1 = System.nanoTime();
            analysisScheduler.runStrategies(date);
            long t2 = System.nanoTime();
            // Capture signals between strategy emit and order drain — processOrders
            // empties the queue, so reading it after would always show 0.
            int signalsEmitted = SharedData.tradeSignals != null ? SharedData.tradeSignals.size() : 0;
            orderScheduler.processOrders();
            long t3 = System.nanoTime();
            positionScheduler.processPositions();
            detachEverythingLoadedThisTick();
            long t4 = System.nanoTime();
            dayIndicatorNs += t1 - t0;
            dayStrategyNs  += t2 - t1;
            dayOrdersNs    += t3 - t2;
            dayPositionsNs += t4 - t3;
            dayTicks++;

            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            if (narrate) {
                long opened = safeCount() - rowsBefore;              // new trade_order rows
                long closed = safeCountClosed() - closedBefore;      // OPEN → CLOSED transitions
                log.debug("=== Analysis {} END (signals={}, opened={}, closed={}, dur={}ms) ===",
                        date, signalsEmitted, opened, closed, durationMs);
            }

            return new BacktestDayResult(date, true, combinedDto.size(), durationMs, "Analysis completed.");
        } catch (HistoricalDataMissingException ex) {
            throw ex;
        } catch (Exception ex) {
            log.error("[Backtest] analysis failed for date {}", date, ex);
            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            return new BacktestDayResult(date, false, 0, durationMs, ex.getMessage());
        }
    }

    /** Total trade_order row count; 0 on any error so the tick log never fails. */
    private long safeCount() {
        try { return tradeOrderRepository.count(); }
        catch (Exception ex) { return 0L; }
    }

    /** Trade_order rows in CLOSED status; 0 on any error. */
    private long safeCountClosed() {
        try {
            return tradeOrderRepository.countByStatus("CLOSED");
        } catch (Exception ex) {
            return 0L;
        }
    }

    public record BacktestRunResult(
            LocalDate fromDate,
            LocalDate toDate,
            int totalDays,
            long successDays,
            long durationMs,
            List<BacktestDayResult> days
    ) {
    }

    /**
     * Counts {@code trade_order} rows whose entry timestamp falls inside the
     * trading day. Used by the per-day summary to report the row-delta produced
     * by this backtest invocation rather than the cumulative total.
     */
    private long countTradeOrdersOnDate(LocalDate date) {
        if (tradeOrderRepository == null || date == null) return 0L;
        try {
            LocalDateTime start = date.atStartOfDay();
            LocalDateTime end   = start.plusDays(1).minusNanos(1);
            return tradeOrderRepository.countByStatusAndEntryTimeBetween("OPEN", start, end)
                    + tradeOrderRepository.countByStatusAndEntryTimeBetween("CLOSED", start, end);
        } catch (Exception ex) {
            log.debug("[Backtest] failed to count trade_order rows for {}: {}", date, ex.getMessage());
            return 0L;
        }
    }

    public record BacktestDayResult(
            LocalDateTime date,
            boolean success,
            int tradeConfigCount,
            long durationMs,
            String message
    ) {
    }
}
