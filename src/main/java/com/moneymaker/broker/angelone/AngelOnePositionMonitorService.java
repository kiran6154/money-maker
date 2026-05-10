package com.moneymaker.broker.angelone;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.position.service.PositionMonitorService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Angel One live-quote lookup. Skeleton — returns {@code null} until SmartAPI
 * is wired in.
 */
@Slf4j
@Service
public class AngelOnePositionMonitorService implements PositionMonitorService {

    public static final String NAME = "ANGEL_ONE";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public Quote currentQuote(TradeOrder order) {
        // TODO(broker): GET SmartAPI quote for order.getOptionToken() and return its last price.
        log.debug("AngelOne currentQuote [stub] orderId={}", order != null ? order.getId() : null);
        return null;
    }
}
