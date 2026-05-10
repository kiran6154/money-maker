package com.moneymaker.broker.angelone;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderPlacementService;
import com.moneymaker.state.AppState;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.Objects;

/**
 * Angel One (SmartAPI) order placement.
 *
 * <p><b>Status: structural skeleton.</b> Both {@link #place} and
 * {@link #syncFill} return {@code null} until SmartAPI's REST client is wired
 * in.
 */
@Slf4j
@Service
public class AngelOneOrderPlacementService implements OrderPlacementService {

    public static final String NAME = "ANGEL_ONE";

    private final AppState appState;

    public AngelOneOrderPlacementService(AppState appState) {
        this.appState = Objects.requireNonNull(appState, "appState must not be null");
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public String place(TradeOrder order, TradeConfigCombinedDTO config) {
        if (!appState.isLoggedIn()) {
            log.warn("AngelOne placement skipped — not logged in. orderId={}", order.getId());
            return null;
        }

        boolean closing = "CLOSED".equalsIgnoreCase(order.getStatus());
        boolean isSellEntry = "SELL".equalsIgnoreCase(order.getEntryDirection());
        String txn = (isSellEntry == closing) ? "BUY" : "SELL";
        int qty = (config != null && config.getTradeConfig() != null && config.getTradeConfig().getLotQuantity() != null)
                ? Math.max(config.getTradeConfig().getLotQuantity(), 1)
                : 1;

        // TODO(broker): POST to SmartAPI placeOrder via authenticated client.
        log.info("AngelOne place [stub] orderId={} txn={} qty={} symbolHint={}-{}-{}-{}",
                order.getId(), txn, qty, order.getInstrumentName(), order.getOptionStrike(),
                order.getOptionType(), order.getStatus());
        return null;
    }

    @Override
    public FillSnapshot syncFill(String brokerOrderId) {
        // TODO(broker): GET SmartAPI order book and translate the matching row.
        log.debug("AngelOne syncFill [stub] brokerOrderId={}", brokerOrderId);
        return null;
    }
}
