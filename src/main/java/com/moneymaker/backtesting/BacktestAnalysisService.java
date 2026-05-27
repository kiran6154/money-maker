package com.moneymaker.backtesting;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.login.service.BrokerSessionStore;
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
            BacktestMarketDataCache marketDataCache) {
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
    }

    public BacktestRunResult run(LocalDate fromDate, LocalDate toDate) {
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

        // Market hours: 09:15–15:30. We stop the strategy loop and force-close
        // every still-OPEN intraday position at 15:20 — that's the de-facto
        // broker square-off cutoff for index options. Closes at 15:30 (the
        // hard market close) get rejected by most brokers in live mode, and
        // SEBI's 5-minute pre-close auction phase distorts last-tick prices.
        LocalTime marketStart = LocalTime.of(9, 20);
        LocalTime marketEnd = LocalTime.of(15, 20);

        // Loop through each date. Configs and time-periods are fetched *per day*
        // — the same way the live 09:16 cron does it. A 50-day run does NOT
        // pre-fetch all 50 days' configs upfront; each iteration of this loop
        // is a "trading day" in isolation.
        LocalDate currentDate = fromDate;
        while (!currentDate.isAfter(toDate)) {
            LocalDateTime currentDateTime = LocalDateTime.of(currentDate, marketStart);
            LocalDateTime dateEnd = LocalDateTime.of(currentDate, marketEnd);

            // ===== Day-start: fetch this day's config (live cron equivalent) =====
            List<TradeConfigCombinedDTO> combinedDto = tradeConfigScheduler.getConfigsForDate(currentDate);
            Set<Integer> timePeriodsMinutes = uniqueTimePeriodsFor(combinedDto);

            if (combinedDto.isEmpty() || timePeriodsMinutes.isEmpty()) {
                log.info("[Backtest] day={} — no active configs / no time-periods, skipping day", currentDate);
                currentDate = currentDate.plusDays(1);
                continue;
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

            // Log + telegram the active configs for this trading date — once per date.
            tradeConfigScheduler.reportConfigsForDay(currentDate, combinedDto);

            int tickMinutes = getSmallestTimePeriod(timePeriodsMinutes);
            int forceClosed = 0;
            long rowsAfter;
            try {
                while (!currentDateTime.isAfter(dateEnd)) {
                    LocalDateTime tickAt = currentDateTime;
                    try {
                        BacktestDayResult result = runForDateTime(tickAt, combinedDto);
                        results.add(result);
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
                SharedData.marketDataByInstrumentAndInterval.clear();
                SharedData.tradeSignals.clear();
                log.debug("[Backtest] day={} — caches wiped (strikeMarketData, marketData, tradeSignals)",
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
            long rowsBefore   = safeCount();
            long closedBefore = safeCountClosed();

            log.debug("=== Analysis {} START ===", date);

            try {
                analysisScheduler.calculateIndicator(date);
            }
            catch(Exception e){
                log.error("[Backtest] calculateIndicator failed at {}", date, e);
            }
            analysisScheduler.runStrategies();
            // Capture signals between strategy emit and order drain — processOrders
            // empties the queue, so reading it after would always show 0.
            int signalsEmitted = SharedData.tradeSignals != null ? SharedData.tradeSignals.size() : 0;
            orderScheduler.processOrders();
            positionScheduler.processPositions();

            long rowsAfter   = safeCount();
            long closedAfter = safeCountClosed();
            long opened = rowsAfter - rowsBefore;             // new trade_order rows
            long closed = closedAfter - closedBefore;          // OPEN → CLOSED transitions

            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            log.debug("=== Analysis {} END (signals={}, opened={}, closed={}, dur={}ms) ===",
                    date, signalsEmitted, opened, closed, durationMs);

            return new BacktestDayResult(date, true, combinedDto.size(), durationMs, "Analysis completed.");
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
            LocalDateTime min = LocalDateTime.of(1970, 1, 1, 0, 0);
            LocalDateTime max = LocalDateTime.of(9999, 1, 1, 0, 0);
            return tradeOrderRepository.findByStatusAndEntryTimeBetween("CLOSED", min, max).size();
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
            return tradeOrderRepository.findByStatusAndEntryTimeBetween("OPEN", start, end).size()
                    + tradeOrderRepository.findByStatusAndEntryTimeBetween("CLOSED", start, end).size();
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
