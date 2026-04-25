package com.moneymaker.login.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.moneymaker.entity.BrokerSessionEntity;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.repository.BrokerSessionRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.HashMap;
import java.util.Optional;

/**
 * Persistent (MySQL) holder for the currently authenticated broker session.
 *
 * <p>Single-broker-at-a-time policy: at most one row per broker (UNIQUE on
 * {@code broker}) and at most one row in the table with
 * {@code logged_in = true}. Saving a session for broker X first flips
 * {@code logged_in = false} on every other broker.</p>
 */
@Slf4j
@Component
public class BrokerSessionStore {

    private final BrokerSessionRepository repository;
    private final ObjectMapper mapper;

    public BrokerSessionStore(BrokerSessionRepository repository, ObjectMapper mapper) {
        this.repository = repository;
        this.mapper = mapper;
    }

    /* ---------- query ---------- */

    @Transactional(readOnly = true)
    public Optional<BrokerSession> current() {
        return repository.findFirstByLoggedInTrue().map(this::toDto);
    }

    @Transactional(readOnly = true)
    public Optional<BrokerSessionEntity> currentEntity() {
        return repository.findFirstByLoggedInTrue();
    }

    @Transactional(readOnly = true)
    public boolean isValid() {
        return current().map(s -> s.isValid() && !s.isExpired()).orElse(false);
    }

    public boolean isLoggedIn() {
        return repository.findFirstByLoggedInTrue().map(BrokerSessionEntity::isLoggedIn).orElse(false);
    }

    /* ---------- mutation ---------- */

    @Transactional
    public BrokerSessionEntity save(BrokerSession session) {
        if (session == null || session.getBroker() == null) {
            throw new IllegalArgumentException("BrokerSession and its broker must be non-null");
        }
        repository.clearLoggedInExcept(session.getBroker());

        BrokerSessionEntity entity = repository.findByBroker(session.getBroker())
                .orElseGet(BrokerSessionEntity::new);

        entity.setBroker(session.getBroker());
        entity.setUserId(session.getUserId());
        entity.setAccessToken(session.getAccessToken());
        entity.setRefreshToken(session.getRefreshToken());
        entity.setPublicToken(session.getPublicToken());
        entity.setLoginAt(session.getLoginAt() != null ? session.getLoginAt() : Instant.now());
        entity.setExpiresAt(session.getExpiresAt());
        entity.setLoggedIn(session.isValid());
        entity.setRawJson(serialiseRaw(session));
        return repository.save(entity);
    }

    @Transactional
    public void clear() {
        repository.clearAllLoggedIn();
    }

    @Transactional
    public void updateHeartbeatStatus(Broker broker,
                                      String status,
                                      Instant tickAt,
                                      boolean dataHealthy) {
        repository.findByBroker(broker).ifPresent(e -> {
            e.setLastHeartbeatAt(Instant.now());
            e.setLastHeartbeatStatus(status);
            if (tickAt != null) e.setLastDataAt(tickAt);
            e.setDataHealthy(dataHealthy);
            // NOTE: do NOT touch loggedIn here. It is owned by save() / clear()
            // (explicit login / logout). A transient probe blip must not
            // invalidate the stored credentials.
            repository.save(e);
        });
    }

    /* ---------- mapping ---------- */

    public BrokerSession toDto(BrokerSessionEntity e) {
        if (e == null) return null;
        return BrokerSession.builder()
                .broker(e.getBroker())
                .userId(e.getUserId())
                .accessToken(e.getAccessToken())
                .refreshToken(e.getRefreshToken())
                .publicToken(e.getPublicToken())
                .loginAt(e.getLoginAt())
                .expiresAt(e.getExpiresAt())
                .valid(e.isLoggedIn())
                .raw(new HashMap<>())
                .build();
    }

    private String serialiseRaw(BrokerSession session) {
        if (session.getRaw() == null || session.getRaw().isEmpty()) return null;
        try {
            return mapper.writeValueAsString(session.getRaw());
        } catch (JsonProcessingException e) {
            log.warn("Could not serialise BrokerSession.raw: {}", e.getMessage());
            return null;
        }
    }
}
