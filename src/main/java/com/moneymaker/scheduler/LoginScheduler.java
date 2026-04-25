package com.moneymaker.scheduler;

import com.moneymaker.broker.angelone.AngelOneLoginService;
import com.moneymaker.broker.groww.GrowwLoginService;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.login.service.BrokerLoginService;
import com.moneymaker.login.service.BrokerSessionStore;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.DayOfWeek;
import java.time.LocalDateTime;

/**
 * Validates / refreshes broker sessions on a schedule.
 *
 * <ul>
 *   <li>09:00 IST Mon–Fri: ensure we have a valid session for the active broker.
 *       For Groww (TOTP-capable) we mint one automatically; for Zerodha we log
 *       the login URL because it requires interactive 2FA.</li>
 *   <li>Every 5 minutes: revalidate the current session against the broker.</li>
 * </ul>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LoginScheduler {

    private final BrokerLoginManager manager;
    private final BrokerSessionStore store;

    @Scheduled(cron = "0 0 9 * * MON-FRI", zone = "Asia/Kolkata")
    public void ensureSessionAtMarketOpen() {
        LocalDateTime now = LocalDateTime.now();
        if (now.getDayOfWeek() == DayOfWeek.SATURDAY || now.getDayOfWeek() == DayOfWeek.SUNDAY) {
            return;
        }
        log.info("[LoginScheduler] 09:00 check on {}", now);

        BrokerLoginService active = manager.active();
        BrokerSession current = store.current().orElse(null);

        if (current != null && active.validateSession(current)) {
            current.setValid(true);
            store.save(current);
            log.info("[LoginScheduler] Existing {} session is still valid.", active.getBroker());
            return;
        }

        if (active instanceof GrowwLoginService || active instanceof AngelOneLoginService) {
            log.info("[LoginScheduler] No valid session – auto-logging in to {} via TOTP.",
                    active.getBroker());
            BrokerLoginResponse resp = active.completeLogin(BrokerLoginRequest.builder().build());
            if (resp.isSuccess()) {
                store.save(resp.getSession());
                log.info("[LoginScheduler] {} login OK; valid until {}",
                        active.getBroker(), resp.getSession().getExpiresAt());
            } else {
                log.error("[LoginScheduler] {} auto-login failed: {}",
                        active.getBroker(), resp.getMessage());
            }
        } else if (active.getBroker() == Broker.ZERODHA) {
            log.warn("[LoginScheduler] Zerodha session missing/invalid. Visit {} to log in.",
                    active.getLoginUrl());
        }
    }

    @Scheduled(fixedDelay = 5 * 60 * 1000L, initialDelay = 60 * 1000L)
    public void revalidate() {
        store.current().ifPresent(s -> {
            boolean ok = manager.forBroker(s.getBroker()).validateSession(s);
            if (s.isValid() != ok) {
                s.setValid(ok);
                store.save(s);
                log.info("[LoginScheduler] {} session validity changed -> {}", s.getBroker(), ok);
            }
        });
    }
}
