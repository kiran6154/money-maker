package com.moneymaker.broker.zerodha;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderPlacementService;
import com.moneymaker.state.AppState;
import com.zerodhatech.kiteconnect.KiteConnect;
import com.zerodhatech.kiteconnect.kitehttp.exceptions.KiteException;
import com.zerodhatech.models.Order;
import com.zerodhatech.models.OrderParams;
import com.zerodhatech.models.OrderResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Zerodha (Kite Connect) order placement + fill resolution.
 *
 * <p>{@link #place} dispatches a regular MARKET order on NFO using the shared
 * {@link KiteConnect} bean (whose access token is managed by
 * {@code ZerodhaLoginService}). Returns the Kite order id so the caller can
 * persist it on the {@link TradeOrder} for later reconciliation.
 *
 * <p>{@link #syncFill} calls {@code getOrderHistory(brokerOrderId)} and
 * normalises Kite's status string into our {@code FillSnapshot.status}
 * vocabulary.
 *
 * <p><b>Tradingsymbol resolution is still a known gap.</b> See
 * {@link #resolveTradingSymbol(TradeOrder)}.
 */
@Slf4j
@Service
public class ZerodhaOrderPlacementService implements OrderPlacementService {

    public static final String NAME = "ZERODHA";
    private static final String EXCHANGE_NFO = "NFO";
    private static final String PRODUCT_NRML = "NRML";
    private static final String ORDER_TYPE_MARKET = "MARKET";
    private static final String VALIDITY_DAY = "DAY";
    private static final String VARIETY_REGULAR = "regular";

    private final KiteConnect kiteConnect;
    private final AppState appState;

    public ZerodhaOrderPlacementService(@Qualifier("sharedKiteConnect") KiteConnect kiteConnect,
                                        AppState appState) {
        this.kiteConnect = Objects.requireNonNull(kiteConnect, "kiteConnect must not be null");
        this.appState = Objects.requireNonNull(appState, "appState must not be null");
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public String place(TradeOrder order, TradeConfigCombinedDTO config) {
        if (!appState.isLoggedIn()) {
            log.warn("Zerodha placement skipped — not logged in. orderId={}", order.getId());
            return null;
        }

        String tradingSymbol = resolveTradingSymbol(order);
        if (tradingSymbol == null) {
            log.warn("Zerodha placement skipped — could not resolve tradingsymbol for orderId={}", order.getId());
            return null;
        }

        OrderParams params = new OrderParams();
        params.tradingsymbol = tradingSymbol;
        params.exchange = EXCHANGE_NFO;
        params.transactionType = transactionType(order);
        params.quantity = quantity(order, config);
        params.product = PRODUCT_NRML;
        params.orderType = ORDER_TYPE_MARKET;
        params.validity = VALIDITY_DAY;

        try {
            OrderResponse placed = kiteConnect.placeOrder(params, VARIETY_REGULAR);
            String kiteOrderId = placed != null ? placed.orderId : null;
            log.info("Zerodha placeOrder OK: orderId={} symbol={} txn={} qty={} kiteOrderId={}",
                    order.getId(), params.tradingsymbol, params.transactionType, params.quantity, kiteOrderId);
            return kiteOrderId;
        } catch (KiteException | IOException ex) {
            log.error("Zerodha placeOrder FAILED: orderId={} symbol={} txn={} qty={}",
                    order.getId(), params.tradingsymbol, params.transactionType, params.quantity, ex);
            return null;
        }
    }

    @Override
    public FillSnapshot syncFill(String brokerOrderId) {
        if (brokerOrderId == null || brokerOrderId.isBlank()) return null;
        if (!appState.isLoggedIn()) {
            log.warn("Zerodha syncFill skipped — not logged in. brokerOrderId={}", brokerOrderId);
            return null;
        }
        try {
            List<Order> history = kiteConnect.getOrderHistory(brokerOrderId);
            if (history == null || history.isEmpty()) return null;
            // Kite returns history oldest-first; the latest known state is the last entry.
            Order latest = history.get(history.size() - 1);
            return new FillSnapshot(
                    normaliseStatus(latest.status),
                    parseAveragePrice(latest.averagePrice),
                    parseQuantity(latest.filledQuantity)
            );
        } catch (KiteException | IOException ex) {
            log.error("Zerodha syncFill FAILED for brokerOrderId={}", brokerOrderId, ex);
            return null;
        }
    }

    private static String normaliseStatus(String kiteStatus) {
        if (kiteStatus == null) return "PENDING";
        switch (kiteStatus.toUpperCase(Locale.ROOT)) {
            case "COMPLETE":  return "COMPLETE";
            case "REJECTED":  return "REJECTED";
            case "CANCELLED":
            case "CANCELED":  return "CANCELLED";
            default:          return "PENDING"; // NEW, OPEN, MODIFY_PENDING, etc.
        }
    }

    private static BigDecimal parseAveragePrice(Object value) {
        if (value == null) return null;
        try {
            return new BigDecimal(value.toString());
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static Integer parseQuantity(Object value) {
        if (value == null) return null;
        try {
            return Integer.valueOf(value.toString());
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    /**
     * BUY entry / SELL exit-of-BUY → Kite "BUY". SELL entry / BUY exit-of-SELL → Kite "SELL".
     *   OPEN  → fire entryDirection as the txn type.
     *   CLOSED→ fire the inverse (close = opposite direction).
     */
    private String transactionType(TradeOrder order) {
        boolean closing = "CLOSED".equalsIgnoreCase(order.getStatus());
        boolean isSellEntry = "SELL".equalsIgnoreCase(order.getEntryDirection());
        boolean buyTxn = isSellEntry == closing;
        return buyTxn ? "BUY" : "SELL";
    }

    private int quantity(TradeOrder order, TradeConfigCombinedDTO config) {
        if (config != null && config.getTradeConfig() != null && config.getTradeConfig().getLotQuantity() != null) {
            int q = config.getTradeConfig().getLotQuantity();
            return q > 0 ? q : 1;
        }
        return 1;
    }

    /**
     * <b>TODO:</b> resolve via cached Kite NFO instruments dump. Until that
     * lands we return {@code null} so {@link #place} bails rather than send
     * an order with a wrong symbol.
     */
    private String resolveTradingSymbol(TradeOrder order) {
        log.debug("resolveTradingSymbol: not yet implemented for orderId={}, instrument={}, strike={} {}",
                order.getId(), order.getInstrumentName(), order.getOptionStrike(), order.getOptionType());
        return null;
    }
}
