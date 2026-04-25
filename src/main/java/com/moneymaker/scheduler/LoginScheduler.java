package com.moneymaker.scheduler;

import com.moneymaker.broker.angelone.AngelOneLoginService;
import com.moneymaker.broker.groww.GrowwLoginService;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.model.HeartbeatResult;
import com.moneymaker.login.model.HeartbeatStatus;
import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.login.service.BrokerLoginService;
import com.moneymaker.login.service.LoginOrchestrator;
import com.moneymaker.state.AppState;
import com.moneymaker.telegram.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.DayOfWeek;
import java.time.Instant;
import java.time.LocalDateTime;

/**
 * Scheduling-only concern. All actual login decisions live in
 * {@link LoginOrchestrator}; this class merely fires the orchestrator on a
 * cron and runs the two-tier heartbeat (auth + data probe).
 *
 * <p><b>Mode-gated:</b> only registered when {@code app.mode=live} (the
 * default). In {@code app.mode=backtest} the scheduler is absent and login
 * is driven manually via {@code POST /api/backtest/login}.</p>
 *
 * <p>Telegram alerts are emitted only on <b>state transitions</b> to avoid spam.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "app.mode", havingValue = "live", matchIfMissing = true)
public class LoginScheduler {

    private final BrokerLoginManager manager;
    private final AppState appState;
    private final NotificationService notifier;
    private final LoginOrchestrator loginOrchestrator;

    /** 08:00 IST Mon-Fri: first login of the day. */
    @Scheduled(cron = "0 0 8 * * MON-FRI", zone = "Asia/Kolkata")
    public void ensureSessionAtMarketOpen() {
        LocalDateTime now = LocalDateTime.now();
        if (now.getDayOfWeek() == DayOfWeek.SATURDAY || now.getDayOfWeek() == DayOfWeek.SUNDAY) {
            return;
        }
        log.info("[LoginScheduler] 08:00 check on {}", now);
        loginOrchestrator.ensureLoggedIn();
    }

    /** Heartbeat every 1 minute. Telegram alerts are emitted only on state
     *  transitions (see {@link #transitionAndNotify}), so a steady "OK" or
     *  steady "AUTH_FAIL" never spams the channel. */
    @Scheduled(fixedDelay = 60_000L, initialDelay = 30_000L)
    public void heartbeat() {
        BrokerSession session = appState.currentSession().orElse(null);
        if (session == null) {
            transitionAndNotify(HeartbeatStatus.NO_SESSION, null, "no active session");
            return;
        }

        BrokerLoginService svc = manager.forBroker(session.getBroker());

        boolean authOk;
        try {
            authOk = svc.validateSession(session);
        } catch (Exception e) {
            log.warn("[Heartbeat] auth probe threw: {}", e.getMessage());
            transitionAndNotify(HeartbeatStatus.HTTP_ERROR, null, "auth probe error: " + e.getMessage());
            return;
        }

        if (!authOk) {
            // Capture previous status BEFORE transitionAndNotify mutates AppState,
            // so we can tell whether this is the first failure or a steady-state failure.
            HeartbeatStatus prev = appState.getLastHeartbeatStatus();
            transitionAndNotify(HeartbeatStatus.AUTH_FAIL, null, "validateSession=false");

            boolean firstFailure = prev != HeartbeatStatus.AUTH_FAIL;
            boolean totpBroker   = svc instanceof GrowwLoginService || svc instanceof AngelOneLoginService;

            // Only attempt auto-relogin once per AUTH_FAIL transition – otherwise
            // a permanently broken broker session would fire alertLoginFailed
            // (and a Telegram message) every minute the scheduler ticks.
            if (firstFailure && totpBroker) {
                log.info("[Heartbeat] AUTH_FAIL transition for {} – attempting auto-relogin once.",
                        svc.getBroker());
                loginOrchestrator.ensureLoggedIn();
            } else if (totpBroker) {
                log.debug("[Heartbeat] AUTH_FAIL persists for {} – auto-relogin already attempted, " +
                        "will retry on next status transition or at 08:00 cron.", svc.getBroker());
            }
            return;
        }

        HeartbeatResult dataResult = svc.fetchHeartbeatQuote(session);
        switch (dataResult.getStatus()) {
            case OK -> transitionAndNotify(HeartbeatStatus.OK, dataResult.getLastTickAt(), null);
            case NO_DATA -> transitionAndNotify(HeartbeatStatus.NO_DATA, null, dataResult.getMessage());
            case HTTP_ERROR -> transitionAndNotify(HeartbeatStatus.HTTP_ERROR, null, dataResult.getMessage());
            default -> transitionAndNotify(dataResult.getStatus(), dataResult.getLastTickAt(), dataResult.getMessage());
        }
    }

    /* ---------- helpers ---------- */

    private void transitionAndNotify(HeartbeatStatus newStatus, Instant tickAt, String reason) {
        HeartbeatStatus prev = appState.getLastHeartbeatStatus();
        appState.onHeartbeat(newStatus, tickAt, reason);

        if (prev == newStatus) return;
        Broker broker = appState.currentBroker().orElse(null);
        if (broker == null) return;

        switch (newStatus) {
            case AUTH_FAIL, HTTP_ERROR -> notifier.alertSessionLost(broker, newStatus, reason);
            case NO_DATA -> notifier.alertNoData(broker, reason);
            case OK -> {
                if (prev != HeartbeatStatus.NO_SESSION) notifier.alertRecovered(broker);
            }
            case NO_SESSION -> { /* silent */ }
        }
    }
}
