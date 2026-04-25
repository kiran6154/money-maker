package com.moneymaker.entity;

import com.moneymaker.login.model.Broker;
import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/**
 * Persistent record of an authenticated broker session. There is at most one
 * row per broker (UNIQUE on {@code broker}) and at most one row in the whole
 * table with {@code logged_in = true} (enforced by
 * {@link com.moneymaker.login.service.BrokerSessionStore}).
 */
@Entity
@Table(name = "broker_session")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class BrokerSessionEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Enumerated(EnumType.STRING)
    @Column(name = "broker", nullable = false, unique = true, length = 32)
    private Broker broker;

    @Column(name = "user_id", length = 64)
    private String userId;

    @Column(name = "access_token", length = 2048)
    private String accessToken;

    @Column(name = "refresh_token", length = 2048)
    private String refreshToken;

    @Column(name = "public_token", length = 2048)
    private String publicToken;

    @Column(name = "login_at")
    private Instant loginAt;

    @Column(name = "expires_at")
    private Instant expiresAt;

    @Column(name = "last_heartbeat_at")
    private Instant lastHeartbeatAt;

    @Column(name = "last_heartbeat_status", length = 32)
    private String lastHeartbeatStatus;

    @Column(name = "last_data_at")
    private Instant lastDataAt;

    @Column(name = "logged_in", nullable = false)
    private boolean loggedIn;

    @Column(name = "data_healthy", nullable = false)
    private boolean dataHealthy;

    @Lob
    @Column(name = "raw_json", columnDefinition = "TEXT")
    private String rawJson;
}

