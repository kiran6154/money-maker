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
    private final EodDowntrendDetectionService eodDowntrendDetectionService;
    private final TradingCalendar tradingCalendar;
    private final JournalRecorder journal;
    private final com.moneymaker.market.service.MarketHoursService marketHours;

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
            EodDowntrendDetectionService eodDowntrendDetectionService,
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
        this.eodDowntrendDetectionService = eodDowntrendDetectionService;
        this.tradingCalendar = tradingCalendar;
        this.journal = journal;
        this.marketHours = marketHours;
    }

    /** Per-window summary of a generation-only pass ({@code /api/backtest/generate-configs}). */
    public record GenerateConfigsResult(LocalDate fromDate, LocalDate toDate,
                                        int sessionsProcessed, int failures,
                                        List<String> failedDates, long durationMs) {}

    /**
     * Generation-only counterpart of {@link #run}: walks each trading session
     * in the window and runs the EOD downtrend detector for it — no replay, no
     * ledger writes, no shared-state mutation beyond what the detector itself
     * persists. Idempotent by the detector's own contract (it skips days whose
     * configs already exist). A per-day failure is recorded and the walk
     * continues, matching how the combined flow treated detector errors.
     */
    public GenerateConfigsResult generateConfigsOnly(LocalDate fromDate, LocalDate toDate) {
        if (fromDate == null || toDate == null) {
            throw new IllegalArgumentException("fromDate and toDate must not be null");
        }
        if (fromDate.isAfter(toDate)) {
            throw new IllegalArgumentException("fromDate must be on or before toDate");
        }
        Instant startedAt = Instant.now();
        int sessions = 0;
        List<String> failed = new ArrayList<>();
        LocalDate d = fromDate;
        while (!d.isAfter(toDate)) {
            if (tradingCalendar.isTradingDay(d)) {
                sessions++;
                try {
                    eodDowntrendDetectionService.runForDay(d);
                } catch (Exception ex) {
                    failed.add(d.toString());
                    log.error("[Backtest] generate-configs {} — detector failed", d, ex);
                }
            }
            d = d.plusDays(1);
        }
        long ms = java.time.Duration.between(startedAt, Instant.now()).toMillis();
        log.info("[Backtest] generate-configs {} -> {}: {} session(s), {} failure(s), {}ms",
                fromDate, toDate, sessions, failed.size(), ms);
        return new GenerateConfigsResult(fromDate, toDate, sessions, failed.size(), failed, ms);
    }

    /**
     * Replay without config generation — the default since 2026-08-31 (user
     * request): a backtest run and {@code AUTO_DOWNTREND} generation are
     * separate operations, so a measurement run can never mutate the config
     * set it is measuring. Use {@link #generateConfigsOnly} to generate, or
     * the three-arg overload with {@code generateConfigs=true} for the old
     * combined behaviour.
     */
    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate) {
        return run(fromDate, toDate, false);
    }

    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate, boolean generateConfigs) {
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
                if (generateConfigs) {
                    try {
                        eodDowntrendDetectionService.runForDay(currentDate);
                    } catch (Exception ex) {
                        log.error("[Backtest] {} — EOD downtrend detection failed", currentDate, ex);
                    }
                }

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
                SharedData.strikeMarketDataByInstrumentAndInterval.clear();
                SharedData.strikeMarketDataTick.clear();
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
            log.info("[Backtest] day={} done in {} ms — trade_order rows: before={} after={} delta={} forceClosed={}",
                    currentDate, dayMs, rowsBefore, rowsAfter, rowsAfter - rowsBefore, forceClosed);

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

    private BacktestDayResult runForDateTime(LocalDateTime dateTime, List<TradeConfigCombinedDTO> combinedDto) {
        return runForDate(dateTime,combinedDto);
    }

    private BacktestDayResult runForDate(LocalDateTime date, List<TradeConfigCombinedDTO> combinedDto) {
        Instant startedAt = Instant.now();

        try {
            // Fetch broker session details from the database
            var sessionEntity = brokerSessionStore.currentEntity();
            if (sessionEntity.isEmpty()) {
                log.warn("[Backtest] No active broker session found for date {}", date);
                notifier.alertNoActiveSession("backtest tick at " + date);
                long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
                return new BacktestDayResult(date, false, 0, durationMs, "No active broker session found.");
            }

            var session = sessionEntity.get();
            String userId = session.getUserId();

            // Initialize KiteConnect with fetched details
            String accessToken = session.getAccessToken();
            String publicToken = session.getPublicToken();

            if (accessToken == null || accessToken.isEmpty()) {
                log.warn("[Backtest] Access token is missing for date {}", date);
                long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
                return new BacktestDayResult(date, false, 0, durationMs, "Access token is missing.");
            }

            // Set access token on the shared KiteConnect bean
            sharedKiteConnect.setAccessToken(accessToken);
            if (publicToken != null && !publicToken.isEmpty()) {
                sharedKiteConnect.setPublicToken(publicToken);
            }

            // Also set in SharedData for backward compatibility
            SharedData.sharedKiteconnect = sharedKiteConnect;

            log.debug("[Backtest] KiteConnect initialized for user: {} on date: {}", userId, date);

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
            analysisScheduler.runStrategies(date);
            // Capture signals between strategy emit and order drain — processOrders
            // empties the queue, so reading it after would always show 0.
            int signalsEmitted = SharedData.tradeSignals != null ? SharedData.tradeSignals.size() : 0;
            orderScheduler.processOrders();
            positionScheduler.processPositions();

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
