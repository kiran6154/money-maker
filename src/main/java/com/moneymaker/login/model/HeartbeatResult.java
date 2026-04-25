package com.moneymaker.login.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

/**
 * Standardised outcome of a single heartbeat probe.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class HeartbeatResult {

    private HeartbeatStatus status;
    /** Free-form message (e.g. broker error code, http status). */
    private String message;
    /** Last data tick timestamp reported by the broker, when available. */
    private Instant lastTickAt;

    public boolean isOk() {
        return status == HeartbeatStatus.OK;
    }

    public static HeartbeatResult ok(Instant lastTickAt) {
        return HeartbeatResult.builder().status(HeartbeatStatus.OK).lastTickAt(lastTickAt).build();
    }

    public static HeartbeatResult of(HeartbeatStatus status, String message) {
        return HeartbeatResult.builder().status(status).message(message).build();
    }
}

