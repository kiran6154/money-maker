package com.moneymaker.backtesting;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderPlacementService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Simulated placement for backtest runs. The persisted {@link TradeOrder}
 * row is the backtest ledger; no broker call happens. Returns {@code null}
 * for the broker order id and a {@code BACKTEST}-status snapshot so callers
 * can mark rows as immediately final.
 */
@Slf4j
@Service
public class BacktestingOrderPlacementService implements OrderPlacementService {

    public static final String NAME = "BACKTESTING";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public String place(TradeOrder order, TradeConfigCombinedDTO config) {
        log.debug("[stub] Backtesting place: status={}, orderId={}", order.getStatus(), order.getId());
        return null;
    }

    @Override
    public FillSnapshot syncFill(String brokerOrderId) {
        // Backtest rows have no broker counterpart — sync is a no-op that
        // simply reports them as final at whatever price the strategy used.
        return new FillSnapshot("BACKTEST", null, null);
    }
}
