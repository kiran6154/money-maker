package com.moneymaker.broker.zerodha;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.position.service.PositionMonitorService;
import com.moneymaker.state.AppState;
import com.zerodhatech.kiteconnect.KiteConnect;
import com.zerodhatech.kiteconnect.kitehttp.exceptions.KiteException;
import com.zerodhatech.models.LTPQuote;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.Objects;

/**
 * Live Zerodha position monitor — calls {@code kiteConnect.getLTP(...)} keyed
 * by the option's instrument token. The {@link Quote#asOf()} is wall-clock
 * (Kite LTP doesn't carry an authoritative quote-time field) — fine for live
 * since "now" is the right exit timestamp.
 */
@Slf4j
@Service
public class ZerodhaPositionMonitorService implements PositionMonitorService {

    public static final String NAME = "ZERODHA";

    private final KiteConnect kiteConnect;
    private final AppState appState;

    public ZerodhaPositionMonitorService(@Qualifier("sharedKiteConnect") KiteConnect kiteConnect,
                                         AppState appState) {
        this.kiteConnect = Objects.requireNonNull(kiteConnect, "kiteConnect must not be null");
        this.appState = Objects.requireNonNull(appState, "appState must not be null");
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public Quote currentQuote(TradeOrder order) {
        if (order == null || order.getOptionToken() == null) return null;
        if (!appState.isLoggedIn()) return null;

        try {
            String[] tokens = new String[] { order.getOptionToken() };
            Map<String, LTPQuote> ltp = kiteConnect.getLTP(tokens);
            if (ltp == null) return null;
            LTPQuote quote = ltp.get(order.getOptionToken());
            if (quote == null) return null;
            return new Quote(BigDecimal.valueOf(quote.lastPrice), LocalDateTime.now());
        } catch (KiteException | IOException ex) {
            log.warn("Zerodha getLTP failed for optionToken={} (orderId={}): {}",
                    order.getOptionToken(), order.getId(), ex.getMessage());
            return null;
        }
    }
}
