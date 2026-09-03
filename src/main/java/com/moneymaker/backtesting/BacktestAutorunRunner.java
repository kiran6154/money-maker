package com.moneymaker.backtesting;

import com.moneymaker.market.exception.HistoricalDataMissingException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.LinkedHashSet;
import java.util.Objects;
import java.util.Set;

/**
 * Phase 10 worker entry point: replays a date range at startup and (by
 * default) exits with a status code, so the parallel driver
 * ({@code scripts/backtest-parallel.ps1}) can launch K plain
 * {@code java -jar} processes and wait on them — no HTTP orchestration, no
 * servers left behind.
 *
 * <p><b>Double-gated against live.</b> The bean only exists when
 * {@code backtest.autorun.enabled=true} (never set in
 * {@code application.properties}; the driver passes it on the command line),
 * and even then it refuses to run unless {@code app.mode=backtest}. A live
 * deployment cannot trip this by accident: both gates must be forced at once.
 *
 * <p>The runner calls the same {@link BacktestAnalysisService#run} the
 * {@code /api/backtest/analysis} endpoint calls — same pipeline, same
 * scheduler entry points, no parallel code path (CLAUDE.md invariant 5/8).
 *
 * <p>Exit codes: {@code 0} success, {@code 1} unexpected failure, {@code 2}
 * refused (wrong mode / bad arguments), {@code 3} aborted on missing
 * historical data. With {@code backtest.autorun.exit=false} the process stays
 * up after the run — the Phase 12 warm-worker mode, where the driver reuses
 * the resident JVM (and its candle/SMA caches) over HTTP for later runs.
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "backtest.autorun.enabled", havingValue = "true")
public class BacktestAutorunRunner implements ApplicationRunner {

    private final BacktestAnalysisService backtestAnalysisService;
    private final ConfigurableApplicationContext context;
    private final String appMode;
    private final String from;
    private final String to;
    private final String strategyIds;
    private final String configIds;
    private final Integer configStrategyId;
    private final boolean exitWhenDone;

    public BacktestAutorunRunner(BacktestAnalysisService backtestAnalysisService,
                                 ConfigurableApplicationContext context,
                                 @Value("${app.mode:live}") String appMode,
                                 @Value("${backtest.autorun.from:}") String from,
                                 @Value("${backtest.autorun.to:}") String to,
                                 @Value("${backtest.autorun.strategy-ids:}") String strategyIds,
                                 @Value("${backtest.autorun.config-ids:}") String configIds,
                                 @Value("${backtest.autorun.config-strategy-id:#{null}}") Integer configStrategyId,
                                 @Value("${backtest.autorun.exit:true}") boolean exitWhenDone) {
        this.backtestAnalysisService = Objects.requireNonNull(backtestAnalysisService);
        this.context = Objects.requireNonNull(context);
        this.appMode = appMode == null ? "" : appMode.trim();
        this.from = from;
        this.to = to;
        this.strategyIds = strategyIds;
        this.configIds = configIds;
        this.configStrategyId = configStrategyId;
        this.exitWhenDone = exitWhenDone;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (!"backtest".equalsIgnoreCase(appMode)) {
            log.error("[autorun] refused: backtest.autorun.enabled=true but app.mode={} — "
                    + "the autorun runner never executes outside backtest mode", appMode);
            finish(2);
            return;
        }

        LocalDate fromDate;
        LocalDate toDate;
        try {
            fromDate = LocalDate.parse(require(from, "backtest.autorun.from"));
            toDate = LocalDate.parse(require(to, "backtest.autorun.to"));
        } catch (Exception ex) {
            log.error("[autorun] refused: {}", ex.getMessage());
            finish(2);
            return;
        }

        Set<Integer> strategyScope = parseIds(strategyIds);
        Set<Integer> configScope = parseIds(configIds);
        log.info("[autorun] replaying {}..{} (strategyIds={}, configIds={}, configStrategyId={}, exit={})",
                fromDate, toDate,
                strategyScope == null ? "all" : strategyScope,
                configScope == null ? "all" : configScope,
                configStrategyId == null ? "own" : configStrategyId,
                exitWhenDone);

        try {
            BacktestAnalysisService.BacktestRunResult result = backtestAnalysisService.run(
                    fromDate, toDate, strategyScope, configScope, configStrategyId);
            log.info("[autorun] completed {}..{} in {} ms — {} tick results, {} successful",
                    fromDate, toDate, result.durationMs(), result.totalDays(), result.successDays());
            finish(0);
        } catch (HistoricalDataMissingException ex) {
            log.error("[autorun] aborted — historical data missing: {}", ex.getMessage());
            finish(3);
        } catch (Exception ex) {
            log.error("[autorun] failed", ex);
            finish(1);
        }
    }

    private void finish(int code) {
        if (!exitWhenDone) {
            log.info("[autorun] staying resident (backtest.autorun.exit=false) — "
                    + "drive further runs via POST /api/backtest/analysis");
            return;
        }
        // Tomcat's threads are non-daemon; System.exit after a clean context
        // close is the supported way for a runner-driven batch process to end.
        System.exit(SpringApplication.exit(context, () -> code));
    }

    private static String require(String value, String key) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(key + " must be set (ISO date, e.g. 2024-01-01)");
        }
        return value.trim();
    }

    /** "1,2" → {1, 2}; blank → null (meaning "all" — same convention as the controller). */
    private static Set<Integer> parseIds(String csv) {
        if (csv == null || csv.isBlank()) return null;
        Set<Integer> ids = new LinkedHashSet<>();
        for (String part : csv.split(",")) {
            if (!part.isBlank()) ids.add(Integer.parseInt(part.trim()));
        }
        return ids.isEmpty() ? null : ids;
    }
}
