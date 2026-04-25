package com.moneymaker.login.service;

import com.moneymaker.broker.angelone.AngelOneLoginService;
import com.moneymaker.broker.groww.GrowwLoginService;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.state.AppState;
import com.moneymaker.telegram.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Stateless, scheduler-independent login orchestrator. Encapsulates the
 * "ensure we have a valid broker session, otherwise log in" decision so the
 * exact same flow can be invoked from
 * {@link com.moneymaker.scheduler.LoginScheduler the live scheduler} or
 * {@link com.moneymaker.backtesting.BacktestController the backtest
 * controller} — without either of them duplicating logic.
 *
 * <p>The orchestrator never schedules anything, never holds state, and never
 * calls Telegram directly except via {@link NotificationService}. All session
 * mutations go through {@link AppState}.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class LoginOrchestrator {

    private final BrokerLoginManager manager;
    private final AppState appState;
    private final NotificationService notifier;

    /** Result of {@link #ensureLoggedIn()}. */
    public enum Outcome {
        /** Existing session was valid; no action taken. */
        ALREADY_VALID,
        /** Auto-login (TOTP) succeeded and a fresh session is stored. */
        LOGGED_IN,
        /** Active broker requires interactive login (e.g. Zerodha) – user action needed. */
        INTERACTIVE_REQUIRED,
        /** Auto-login was attempted but failed. */
        FAILED
    }

    /**
     * Ensure the active broker has a valid session. If not, attempts an
     * automatic login for TOTP-capable brokers (Groww, Angel One) and emits
     * the appropriate Telegram notification on success / failure.
     */
    public Outcome ensureLoggedIn() {
        BrokerLoginService active = manager.active();
        BrokerSession current = appState.currentSession().orElse(null);

        if (current != null && safeValidate(active, current)) {
            log.info("[LoginOrchestrator] Existing {} session is still valid.", active.getBroker());
            return Outcome.ALREADY_VALID;
        }

        return autoLogin(active);
    }

    /**
     * Force a fresh login for the active broker, regardless of any cached
     * session. Useful for tests / backtests that always want a clean slate.
     */
    public Outcome forceLogin() {
        return autoLogin(manager.active());
    }

    /* ---------- internals ---------- */

    private Outcome autoLogin(BrokerLoginService active) {
        if (active instanceof GrowwLoginService || active instanceof AngelOneLoginService) {
            log.info("[LoginOrchestrator] Auto-logging in to {} via TOTP.", active.getBroker());
            try {
                BrokerLoginResponse resp = active.completeLogin(BrokerLoginRequest.builder().build());
                if (resp.isSuccess() && resp.getSession() != null) {
                    appState.onLoginSuccess(resp.getSession());
                    notifier.alertLoginSuccess(active.getBroker(), resp.getSession().getUserId());
                    log.info("[LoginOrchestrator] {} auto-login OK; valid until {}",
                            active.getBroker(), resp.getSession().getExpiresAt());
                    return Outcome.LOGGED_IN;
                }
                notifier.alertLoginFailed(active.getBroker(), resp.getMessage());
                log.error("[LoginOrchestrator] {} auto-login failed: {}", active.getBroker(), resp.getMessage());
                return Outcome.FAILED;
            } catch (Exception e) {
                notifier.alertLoginFailed(active.getBroker(), e.getMessage());
                log.error("[LoginOrchestrator] {} auto-login threw", active.getBroker(), e);
                return Outcome.FAILED;
            }
        }

        if (active.getBroker() == Broker.ZERODHA) {
            String msg = "Zerodha requires interactive login. Visit " + active.getLoginUrl();
            notifier.alertLoginFailed(Broker.ZERODHA, msg);
            log.warn("[LoginOrchestrator] {}", msg);
            return Outcome.INTERACTIVE_REQUIRED;
        }
        return Outcome.FAILED;
    }

    private boolean safeValidate(BrokerLoginService svc, BrokerSession session) {
        try {
            return svc.validateSession(session);
        } catch (Exception e) {
            log.warn("[LoginOrchestrator] validateSession threw: {}", e.getMessage());
            return false;
        }
    }
}

