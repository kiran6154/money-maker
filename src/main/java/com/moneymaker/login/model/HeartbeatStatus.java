package com.moneymaker.login.model;

/**
 * Outcome of a single heartbeat tick. {@link #OK} means both the auth token
 * and a market-data probe succeeded. The other values map to distinct alert
 * conditions consumed by the notification layer.
 */
public enum HeartbeatStatus {
    /** Auth + data probe both succeeded. */
    OK,
    /** Broker rejected the auth token (re-login required). */
    AUTH_FAIL,
    /** Auth ok but the data probe failed or returned a stale tick. */
    NO_DATA,
    /** Network / unexpected error – treated as transient. */
    HTTP_ERROR,
    /** No session present. */
    NO_SESSION
}

