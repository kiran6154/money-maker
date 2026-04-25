package com.moneymaker.login.service;

import com.moneymaker.login.config.BrokerProperties;
import com.moneymaker.login.exception.BrokerLoginException;
import com.moneymaker.login.model.Broker;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;

/**
 * Facade over all registered {@link BrokerLoginService} adapters. Resolves
 * the active broker from {@code broker.active} and dispatches to the right
 * adapter so controllers / schedulers stay broker-agnostic.
 */
@Slf4j
@Service
public class BrokerLoginManager {

    private final Map<Broker, BrokerLoginService> services = new EnumMap<>(Broker.class);
    private final BrokerProperties properties;

    public BrokerLoginManager(List<BrokerLoginService> adapters, BrokerProperties properties) {
        this.properties = properties;
        for (BrokerLoginService adapter : adapters) {
            services.put(adapter.getBroker(), adapter);
            log.info("Registered broker login adapter: {}", adapter.getBroker());
        }
    }

    public Broker activeBroker() {
        return Broker.fromString(properties.getActive());
    }

    public BrokerLoginService active() {
        Broker broker = activeBroker();
        BrokerLoginService svc = services.get(broker);
        if (svc == null) {
            throw new BrokerLoginException("No login adapter registered for active broker: " + broker);
        }
        return svc;
    }

    public BrokerLoginService forBroker(Broker broker) {
        BrokerLoginService svc = services.get(broker);
        if (svc == null) {
            throw new BrokerLoginException("No login adapter registered for broker: " + broker);
        }
        return svc;
    }

    public List<Broker> availableBrokers() {
        return services.keySet().stream().sorted().toList();
    }
}

