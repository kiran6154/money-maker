package com.moneymaker.backtesting;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.scheduler.AnalysisScheduler;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.shared.data.SharedData;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class BacktestAnalysisService {

    private final TradeConfigScheduler tradeConfigScheduler;
    private final AnalysisScheduler analysisScheduler;

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
        List<BacktestDayResult> days = new ArrayList<>();
        LocalDate cursor = fromDate;
        while (!cursor.isAfter(toDate)) {
            days.add(runForDate(cursor));
            cursor = cursor.plusDays(1);
        }

        long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
        long successCount = days.stream().filter(BacktestDayResult::success).count();
        return new BacktestRunResult(fromDate, toDate, days.size(), successCount, durationMs, days);
    }

    private BacktestDayResult runForDate(LocalDate date) {
        Instant startedAt = Instant.now();
        try {
            List<TradeConfigCombinedDTO> combinedDto = tradeConfigScheduler.fetchTradeConfigsByDate(date);
            SharedData.combinedDto = combinedDto;

            if (combinedDto == null || combinedDto.isEmpty()) {
                long durationMs = Duration.between(startedAt, Instant.now()).toMillis();
                return new BacktestDayResult(date, true, 0, durationMs, "No trade config found.");
            }

            analysisScheduler.calculateIndicator(date);
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
            LocalDate date,
            boolean success,
            int tradeConfigCount,
            long durationMs,
            String message
    ) {
    }
}
