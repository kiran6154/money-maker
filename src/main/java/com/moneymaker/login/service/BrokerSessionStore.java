package com.moneymaker.login.service;

import com.moneymaker.login.model.BrokerSession;
import org.springframework.stereotype.Component;

import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

/**
 * In-memory holder for the currently authenticated {@link BrokerSession}.
 * Replace with a JPA-backed implementation when persistence is required.
 */
@Component
public class BrokerSessionStore {

    private final AtomicReference<BrokerSession> current = new AtomicReference<>();

    public Optional<BrokerSession> current() {
        return Optional.ofNullable(current.get());
    }

    public void save(BrokerSession session) {
        current.set(session);
    }

    public void clear() {
        current.set(null);
    }

    public boolean isValid() {
        BrokerSession s = current.get();
        return s != null && s.isValid() && !s.isExpired();
    }
}

