package com.moneymaker.backtesting;

import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.market.exception.HistoricalDataMissingException;
import com.moneymaker.login.service.LoginOrchestrator;
import com.moneymaker.login.service.LoginOrchestrator.Outcome;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.state.AppState;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
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
    @Autowired
    private TradeConfigScheduler tradeConfigScheduler;;
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

    /**
     * Replay a window. Since 2026-08-31 (user request) a replay no longer
     * generates {@code AUTO_DOWNTREND} configs as a side effect — run
     * {@link #generateConfigs} first for a window that has none, or pass
     * {@code generateConfigs=true} to restore the old combined behaviour.
     * Separation keeps a measurement run from mutating the config set it is
     * measuring.
     */
    @PostMapping("/analysis")
    public ResponseEntity<?> runAnalysis(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate,
            @RequestParam(value = "generateConfigs", defaultValue = "false") boolean generateConfigs) {
        try {
            BacktestAnalysisService.BacktestRunResult result =
                    backtestAnalysisService.run(fromDate, toDate, generateConfigs);
            log.info("[Backtest] /analysis {} -> {} (generateConfigs={}) completed in {}ms",
                    fromDate, toDate, generateConfigs, result.durationMs());
            return ResponseEntity.ok(result);
        } catch (HistoricalDataMissingException ex) {
            // The run was aborted on purpose — the imported data set does not
            // cover this window. Report it as a client-fixable problem with the
            // missing series named, not as an opaque 500.
            log.error("[Backtest] /analysis {} -> {} aborted: {}", fromDate, toDate, ex.getMessage());
            return ResponseEntity.unprocessableEntity().body(Map.of(
                    "error", "Backtest aborted — historical data missing",
                    "detail", ex.getMessage()));
        }
    }

    /**
     * Generation-only: run the EOD downtrend detector over each session in the
     * window, writing {@code AUTO_DOWNTREND} configs, with no replay and no
     * ledger writes. Idempotent — the detector skips days whose configs exist.
     */
    @PostMapping("/generate-configs")
    public ResponseEntity<?> generateConfigs(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {
        return ResponseEntity.ok(backtestAnalysisService.generateConfigsOnly(fromDate, toDate));
    }

}
