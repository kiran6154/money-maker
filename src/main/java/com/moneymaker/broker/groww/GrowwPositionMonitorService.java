package com.moneymaker.broker.groww;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.position.service.PositionMonitorService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Groww live-quote lookup. Skeleton — returns {@code null} until the Groww
 * REST client is wired in.
 */
@Slf4j
@Service
public class GrowwPositionMonitorService implements PositionMonitorService {

    public static final String NAME = "GROWW";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public Quote currentQuote(TradeOrder order) {
        // TODO(broker): GET Groww quote for order.getOptionToken() and return its last price.
        log.debug("Groww currentQuote [stub] orderId={}", order != null ? order.getId() : null);
        return null;
    }
}
