package com.moneymaker.backtesting;

import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.login.service.LoginOrchestrator;
import com.moneymaker.login.service.LoginOrchestrator.Outcome;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.state.AppState;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Manual driver for the backtest run-mode.
 *
 * <p><b>Mode-gated:</b> registered <i>only</i> when {@code app.mode=backtest}.
 * In {@code live} mode the bean is absent and {@code POST /api/backtest/login}
 * returns 404 — preventing accidental manual logins from racing the live
 * scheduler.</p>
 *
 * <p>The controller is deliberately <b>not</b> a pipeline. Login is just a
 * service call to {@link LoginOrchestrator#ensureLoggedIn()} — the very same
 * call the live {@link com.moneymaker.scheduler.LoginScheduler} makes — so
 * backtest preflight is byte-for-byte identical to live.</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/backtest")
@RequiredArgsConstructor
@ConditionalOnProperty(name = "app.mode", havingValue = "backtest")
public class BacktestController {

    private final LoginOrchestrator loginOrchestrator;
    private final BrokerLoginManager manager;
    private final AppState appState;
    private final BacktestAnalysisService backtestAnalysisService;
    private final BacktestResetService backtestResetService;
    @Autowired
    private TradeConfigScheduler tradeConfigScheduler;

    /**
     * When true, {@link #runAnalysis} purges {@code trade_order} +
     * {@code alert_state} rows + in-memory caches for the requested date
     * range <b>before</b> running the backtest. Default {@code false} so
     * an operator hitting the endpoint to inspect prior output doesn't
     * lose it; tests override via {@code application-test.properties}.
     */
    @Value("${backtest.auto-reset:false}")
    private boolean autoReset;
    /** Manually invoke the login orchestrator for the active broker. */
    @PostMapping("/login")
    public ResponseEntity<Map<String, Object>> login() {
        tradeConfigScheduler.getConfigsForDate(LocalDate.now());

        Instant start = Instant.now();
        Outcome outcome = loginOrchestrator.ensureLoggedIn();
        long durationMs = Duration.between(start, Instant.now()).toMillis();

        boolean success = outcome == Outcome.ALREADY_VALID || outcome == Outcome.LOGGED_IN;
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("outcome", outcome);
        body.put("success", success);
        body.put("activeBroker", manager.activeBroker());
        body.put("loggedIn", appState.isLoggedIn());
        body.put("durationMs", durationMs);
        body.put("message", switch (outcome) {
            case ALREADY_VALID        -> "Existing session is still valid.";
            case LOGGED_IN            -> "Auto-login (TOTP) succeeded.";
            case INTERACTIVE_REQUIRED -> "Active broker requires interactive login. Visit /login/start.";
            case FAILED               -> "Auto-login failed. See server logs / Telegram for details.";
        });

        log.info("[Backtest] /login -> {} (success={})", outcome, success);
        return ResponseEntity.status(success ? HttpStatus.OK : HttpStatus.CONFLICT).body(body);
    }

    @PostMapping("/analysis")
    public ResponseEntity<BacktestAnalysisService.BacktestRunResult> runAnalysis(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {
        if (autoReset) {
            BacktestResetService.ResetSummary summary = backtestResetService.resetRange(fromDate, toDate);
            log.info("[Backtest] auto-reset before /analysis: {}", summary);
        }
        BacktestAnalysisService.BacktestRunResult result = backtestAnalysisService.run(fromDate, toDate);
        log.info("[Backtest] /analysis {} -> {} completed in {}ms", fromDate, toDate, result.durationMs());
        return ResponseEntity.ok(result);
    }

    /**
     * Manual reset endpoint. Purges {@code trade_order} + {@code alert_state}
     * rows in the date range and clears in-memory caches. Always available
     * (so operators can recover from an incomplete prior run); the auto-reset
     * variant above is what runs before every {@code /analysis} call when
     * {@code backtest.auto-reset=true}.
     *
     * <p>Validation: {@code toDate} must be on or before today — protects
     * against operator typos that would wipe future-dated data.
     */
    @PostMapping("/reset")
    public ResponseEntity<?> reset(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {
        if (toDate.isAfter(LocalDate.now())) {
            return ResponseEntity.badRequest().body(Map.of(
                    "error", "toDate cannot be in the future",
                    "toDate", toDate.toString(),
                    "today", LocalDate.now().toString()));
        }
        try {
            BacktestResetService.ResetSummary summary = backtestResetService.resetRange(fromDate, toDate);
            return ResponseEntity.ok(summary);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
