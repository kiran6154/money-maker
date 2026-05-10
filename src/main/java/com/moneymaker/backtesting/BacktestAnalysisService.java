package com.moneymaker.backtesting;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.login.service.BrokerSessionStore;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.scheduler.AnalysisScheduler;
import com.moneymaker.scheduler.OrderScheduler;
import com.moneymaker.scheduler.PositionScheduler;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.shared.data.SharedData;
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
    private final BrokerSessionStore brokerSessionStore;
    private final KiteConnect sharedKiteConnect;

    public BacktestAnalysisService(
            TradeConfigScheduler tradeConfigScheduler,
            AnalysisScheduler analysisScheduler,
            OrderScheduler orderScheduler,
            PositionScheduler positionScheduler,
            OrderService orderService,
            BrokerSessionStore brokerSessionStore,
            @Qualifier("sharedKiteConnect") KiteConnect sharedKiteConnect) {
        this.tradeConfigScheduler = tradeConfigScheduler;
        this.analysisScheduler = analysisScheduler;
        this.orderScheduler = orderScheduler;
        this.positionScheduler = positionScheduler;
        this.orderService = orderService;
        this.brokerSessionStore = brokerSessionStore;
        this.sharedKiteConnect = sharedKiteConnect;
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

        // Get unique time periods from trade configs across the date range
        Set<Integer> timePeriodsMinutes = getUniqueTimePeriods(fromDate, toDate);

        if (timePeriodsMinutes.isEmpty()) {
            log.warn("[Backtest] No time periods configured in SMA timeframes");
            return new BacktestRunResult(fromDate, toDate, 0, 0, 0, results);
        }

        log.info("[Backtest] Running analysis with time periods (minutes): {}", timePeriodsMinutes);

        // Market hours: 9:15 AM to 3:30 PM
        LocalTime marketStart = LocalTime.of(9, 20);
        LocalTime marketEnd = LocalTime.of(15, 30);

        // Loop through each date
        LocalDate currentDate = fromDate;
        while (!currentDate.isAfter(toDate)) {
            // Loop through each time interval for this date
            LocalDateTime currentDateTime = LocalDateTime.of(currentDate, marketStart);
            LocalDateTime dateEnd = LocalDateTime.of(currentDate, marketEnd);
            List<TradeConfigCombinedDTO> combinedDto = tradeConfigScheduler.fetchTradeConfigsByDate(toDate);

            while (!currentDateTime.isAfter(dateEnd)) {
                BacktestDayResult result = runForDateTime(currentDateTime,combinedDto);
                results.add(result);
                currentDateTime = currentDateTime.plusMinutes(getSmallestTimePeriod(timePeriodsMinutes));
            }

            // End-of-day cleanup: force-close any intraday position whose strike
            // fell out of the active-strike set before the close-signal could fire.
            try {
                int closed = orderService.forceCloseOpenPositions(currentDate, dateEnd);
                if (closed > 0) {
                    log.info("[Backtest] {} — force-closed {} open intraday position(s) at {}",
                            currentDate, closed, dateEnd);
                }
            } catch (Exception ex) {
                log.error("[Backtest] {} — force-close at end-of-day failed", currentDate, ex);
            }

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
     * Get unique time periods (in minutes) from all trade configs in the date range
     */
    private Set<Integer> getUniqueTimePeriods(LocalDate fromDate, LocalDate toDate) {
        Set<Integer> periods = new HashSet<>();
        LocalDate currentDate = fromDate;

        while (!currentDate.isAfter(toDate)) {
            List<TradeConfigCombinedDTO> configs = tradeConfigScheduler.fetchTradeConfigsByDate(currentDate);
            for (TradeConfigCombinedDTO config : configs) {
                List<SmaTimeframe> timeframes = config.getTimeframes();
                if (timeframes != null) {
                    for (SmaTimeframe timeframe : timeframes) {
                        if (timeframe.getTimePeriod() != null) {
                            periods.add(timeframe.getTimePeriod());
                        }
                    }
                }
            }
            currentDate = currentDate.plusDays(1);
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

            log.info("[Backtest] KiteConnect initialized for user: {} on date: {}", userId, date);

            SharedData.combinedDto = combinedDto;

            if (combinedDto == null || combinedDto.isEmpty()) {
                long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
                return new BacktestDayResult(date, true, 0, durationMs, "No trade config found.");
            }

            try {
                analysisScheduler.calculateIndicator(date);
            }
            catch(Exception e){
                e.printStackTrace();
            }
            analysisScheduler.runStrategies();
            orderScheduler.processOrders();
            positionScheduler.processPositions();
            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            return new BacktestDayResult(date, true, combinedDto.size(), durationMs, "Analysis completed.");
        } catch (Exception ex) {
            log.error("[Backtest] analysis failed for date {}", date, ex);
            long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
            return new BacktestDayResult(date, false, 0, durationMs, ex.getMessage());
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

    public record BacktestDayResult(
            LocalDateTime date,
            boolean success,
            int tradeConfigCount,
            long durationMs,
            String message
    ) {
    }
}
