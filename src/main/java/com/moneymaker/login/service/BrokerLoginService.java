package com.moneymaker.login.service;

import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.model.HeartbeatResult;
import com.moneymaker.login.model.HeartbeatStatus;

/**
 * Contract every broker-specific login adapter must implement. Each adapter
 * is responsible for translating its native broker API responses into the
 * standard {@link BrokerSession} / {@link BrokerLoginResponse} types.
 */
public interface BrokerLoginService {

    /** Which broker this service handles. */
    Broker getBroker();

    /**
     * The URL the user should be sent to in order to start the login flow.
     * For brokers without a hosted login page (e.g. Groww TOTP), return a
     * local URL pointing at the manual-login form.
     */
    String getLoginUrl();

    /**
     * Completes the login flow using the broker-specific inputs supplied
     * in {@code request} and returns a populated {@link BrokerSession}.
     */
    BrokerLoginResponse completeLogin(BrokerLoginRequest request);

    /** Validates that the supplied session is still accepted by the broker. */
    boolean validateSession(BrokerSession session);

    /** Best-effort logout (invalidates the broker-side session). */
    void logout(BrokerSession session);

    /**
     * Heartbeat data probe – fetch a lightweight market-data quote (e.g.
     * NIFTY 50 LTP) and verify the response carries a non-stale tick. The
     * default implementation reports OK; override in market-data capable
     * brokers.
     */
    default HeartbeatResult fetchHeartbeatQuote(BrokerSession session) {
        return HeartbeatResult.of(HeartbeatStatus.OK, "no-op");
    }
}
