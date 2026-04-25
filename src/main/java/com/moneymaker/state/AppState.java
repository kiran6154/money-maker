package com.moneymaker.state;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.BrokerSessionEntity;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.model.HeartbeatStatus;
import com.moneymaker.login.service.BrokerSessionStore;
import com.moneymaker.repository.BrokerSessionRepository;
import com.moneymaker.repository.TradeConfigRepository;
import jakarta.annotation.PostConstruct;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Single in-memory facade for the application's runtime state. Backed by
 * MySQL via {@link BrokerSessionStore} / repositories and rebuilt on
 * startup. Inject this anywhere instead of touching individual stores so
 * the {@code loggedIn} flag, current broker session, cached trade configs
 * and (soon) orders are queried through one consistent API.
 */
@Slf4j
@Component
public class AppState {

    private final BrokerSessionStore sessionStore;
    private final BrokerSessionRepository sessionRepository;
    private final TradeConfigRepository tradeConfigRepository;

    private final AtomicReference<BrokerSession> session = new AtomicReference<>();

    @Getter
    private volatile HeartbeatStatus lastHeartbeatStatus = HeartbeatStatus.NO_SESSION;
    @Getter
    private volatile Instant lastHeartbeatAt;
    @Getter
    private volatile Instant lastDataAt;
    @Getter
    private volatile boolean dataHealthy;

    private volatile List<TradeConfigCombinedDTO> tradeConfigs = Collections.emptyList();
    private volatile List<Object> orders = Collections.emptyList(); // TODO: replace with Order entity

    public AppState(BrokerSessionStore sessionStore,
                    BrokerSessionRepository sessionRepository,
                    TradeConfigRepository tradeConfigRepository) {
        this.sessionStore = sessionStore;
        this.sessionRepository = sessionRepository;
        this.tradeConfigRepository = tradeConfigRepository;
    }

    @PostConstruct
    void rehydrate() {
        sessionRepository.findFirstByLoggedInTrue().ifPresent(this::applyEntity);
        log.info("[AppState] rehydrated - loggedIn={}, broker={}, status={}",
                isLoggedIn(),
                currentSession().map(BrokerSession::getBroker).orElse(null),
                lastHeartbeatStatus);
    }

    /* ---------- session ---------- */

    public Optional<BrokerSession> currentSession() {
        BrokerSession s = session.get();
        if (s != null) return Optional.of(s);
        return sessionStore.current().map(this::cache);
    }

    public Optional<Broker> currentBroker() {
        return currentSession().map(BrokerSession::getBroker);
    }

    public boolean isLoggedIn() {
        BrokerSession s = currentSession().orElse(null);
        if (s == null) return false;
        // A transient heartbeat blip (NO_DATA / HTTP_ERROR) must not flip the
        // logged-in flag — only a real auth failure or no-session state does.
        if (lastHeartbeatStatus == HeartbeatStatus.AUTH_FAIL
                || lastHeartbeatStatus == HeartbeatStatus.NO_SESSION) {
            return false;
        }
        return s.isValid() && !s.isExpired();
    }

    public void onLoginSuccess(BrokerSession s) {
        sessionStore.save(s);
        cache(s);
        this.lastHeartbeatStatus = HeartbeatStatus.OK;
        this.lastHeartbeatAt = Instant.now();
        this.dataHealthy = true;
    }

    public void onLogout() {
        sessionStore.clear();
        session.set(null);
        this.lastHeartbeatStatus = HeartbeatStatus.NO_SESSION;
        this.dataHealthy = false;
    }

    public void onHeartbeat(HeartbeatStatus status, Instant tickAt, String reason) {
        this.lastHeartbeatStatus = status;
        this.lastHeartbeatAt = Instant.now();
        this.dataHealthy = status == HeartbeatStatus.OK;
        if (tickAt != null) this.lastDataAt = tickAt;

        // The session row's logged_in flag only flips on explicit logout or
        // when the orchestrator stores a fresh session. Heartbeat ticks only
        // update the diagnostic columns (status / last_data_at / data_healthy)
        // so a transient probe failure does not blow away the cached tokens.
        Broker broker = currentBroker().orElse(null);
        if (broker != null) {
            sessionStore.updateHeartbeatStatus(broker, status.name(), tickAt, dataHealthy);
        }
        if (reason != null) log.debug("[AppState] heartbeat {} - {}", status, reason);
    }

    /* ---------- trade configs ---------- */

    public List<TradeConfigCombinedDTO> tradeConfigs() {
        return tradeConfigs;
    }

    public void setTradeConfigs(List<TradeConfigCombinedDTO> list) {
        this.tradeConfigs = list == null ? Collections.emptyList() : new ArrayList<>(list);
    }

    public List<Object> orders() {
        return orders;
    }

    public void setOrders(List<Object> list) {
        this.orders = list == null ? Collections.emptyList() : new ArrayList<>(list);
    }

    /* ---------- helpers ---------- */

    private BrokerSession cache(BrokerSession s) {
        session.set(s);
        return s;
    }

    private void applyEntity(BrokerSessionEntity e) {
        cache(sessionStore.toDto(e));
        this.lastHeartbeatAt = e.getLastHeartbeatAt();
        this.lastDataAt = e.getLastDataAt();
        this.dataHealthy = e.isDataHealthy();
        if (e.getLastHeartbeatStatus() != null) {
            try {
                this.lastHeartbeatStatus = HeartbeatStatus.valueOf(e.getLastHeartbeatStatus());
            } catch (IllegalArgumentException ignored) {
                this.lastHeartbeatStatus = HeartbeatStatus.OK;
            }
        }
    }
}

