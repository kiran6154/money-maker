package com.moneymaker.broker.groww;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderPlacementService;
import com.moneymaker.state.AppState;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.Objects;

/**
 * Groww order placement.
 *
 * <p><b>Status: structural skeleton.</b> Both {@link #place} and
 * {@link #syncFill} return {@code null} until the Groww REST client is wired
 * in. The decision logic mirrors {@code ZerodhaOrderPlacementService} so the
 * shape is stable when the actual HTTP calls land.
 */
@Slf4j
@Service
public class GrowwOrderPlacementService implements OrderPlacementService {

    public static final String NAME = "GROWW";

    private final AppState appState;

    public GrowwOrderPlacementService(AppState appState) {
        this.appState = Objects.requireNonNull(appState, "appState must not be null");
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public String place(TradeOrder order, TradeConfigCombinedDTO config) {
        if (!appState.isLoggedIn()) {
            log.warn("Groww placement skipped — not logged in. orderId={}", order.getId());
            return null;
        }

        boolean closing = "CLOSED".equalsIgnoreCase(order.getStatus());
        boolean isSellEntry = "SELL".equalsIgnoreCase(order.getEntryDirection());
        String txn = (isSellEntry == closing) ? "BUY" : "SELL";
        int qty = (config != null && config.getTradeConfig() != null && config.getTradeConfig().getLotQuantity() != null)
                ? Math.max(config.getTradeConfig().getLotQuantity(), 1)
                : 1;

        // TODO(broker): POST to Groww order-create endpoint via authenticated REST client.
        log.info("Groww place [stub] orderId={} txn={} qty={} symbolHint={}-{}-{}-{}",
                order.getId(), txn, qty, order.getInstrumentName(), order.getOptionStrike(),
                order.getOptionType(), order.getStatus());
        return null;
    }

    @Override
    public FillSnapshot syncFill(String brokerOrderId) {
        // TODO(broker): GET Groww order-status by id and translate into FillSnapshot.
        log.debug("Groww syncFill [stub] brokerOrderId={}", brokerOrderId);
        return null;
    }
}
