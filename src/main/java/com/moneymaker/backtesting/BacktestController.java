package com.moneymaker.backtesting;

import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.login.service.LoginOrchestrator;
import com.moneymaker.login.service.LoginOrchestrator.Outcome;
import com.moneymaker.state.AppState;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.time.Instant;
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

    /** Manually invoke the login orchestrator for the active broker. */
    @PostMapping("/login")
    public ResponseEntity<Map<String, Object>> login() {
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
}
