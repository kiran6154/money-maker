package com.moneymaker.broker.zerodha;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderPlacementService;
import com.moneymaker.repository.InstrumentDetailsRepository;
import com.moneymaker.state.AppState;
import com.moneymaker.telegram.NotificationService;
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
 * <p>The contract is resolved by <b>lookup, never by formatting</b> — see
 * {@link #resolveContract(TradeOrder)}.
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
    private final NotificationService notifier;
    private final InstrumentDetailsRepository instrumentDetailsRepository;

    public ZerodhaOrderPlacementService(@Qualifier("sharedKiteConnect") KiteConnect kiteConnect,
                                        AppState appState,
                                        NotificationService notifier,
                                        InstrumentDetailsRepository instrumentDetailsRepository) {
        this.kiteConnect = Objects.requireNonNull(kiteConnect, "kiteConnect must not be null");
        this.appState = Objects.requireNonNull(appState, "appState must not be null");
        this.notifier = Objects.requireNonNull(notifier, "notifier must not be null");
        this.instrumentDetailsRepository =
                Objects.requireNonNull(instrumentDetailsRepository, "instrumentDetailsRepository must not be null");
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

        Contract contract = resolveContract(order);
        if (contract == null) {
            log.warn("Zerodha placement skipped — could not resolve tradingsymbol for orderId={}", order.getId());
            return null;
        }

        OrderParams params = new OrderParams();
        params.tradingsymbol = contract.tradingSymbol();
        params.exchange = contract.exchange();
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
            notifier.alertOrderRejected(NAME, order.getId(),
                    ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage());
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

    /** The two fields an order needs from the instrument dump: what to trade, and where. */
    record Contract(String tradingSymbol, String exchange) {}

    /**
     * Resolves the derivative contract for an order out of {@code instrument_details}
     * — the app's local copy of the broker's instrument dump.
     *
     * <h3>Why a lookup and not a formatter</h3>
     * Kite's NFO tradingsymbols are not derivable from (underlying, expiry, strike,
     * type) by any single rule. The same NIFTY 23400 CE is
     * {@code NIFTY2660223400CE} for the 2026-06-02 weekly (2-digit year, a
     * <i>single</i> character for the month — {@code 6} for June, {@code O}/{@code N}/{@code D}
     * for Oct/Nov/Dec — then the day) and {@code NIFTY26JUN23400CE} for the
     * 2026-06-30 monthly (2-digit year, 3-letter month, no day). A month-end
     * weekly is published in the monthly form. Any formatter this code invented
     * would be a guess that fires a real market order at a symbol the exchange
     * may or may not list, so the resolution is a straight lookup instead.
     *
     * <h3>The key</h3>
     * {@code trade_order.option_token} is the broker instrument token
     * {@code TokenOptionInstrumentResolver} wrote when the leg was chosen — i.e.
     * the primary key of {@code instrument_details}. One {@code findById} is
     * therefore the whole resolution, and it cannot drift from the leg the
     * strategy actually analysed, because it <i>is</i> that leg's row.
     *
     * <h3>Cross-check before trading</h3>
     * The row's strike and option type are compared against the ledger's own
     * columns. They agree by construction today; they would stop agreeing if
     * {@code instrument_details} were re-seeded from a newer dump that reused a
     * token for a different contract. That is precisely the case where placing
     * the order is worse than not placing it, so a mismatch refuses.
     *
     * <p>Returns {@code null} on every failure — {@link #place} then skips, which
     * on the force-close path raises {@code alertForceCloseExitFailed} telling
     * the operator to square off by hand.
     */
    Contract resolveContract(TradeOrder order) {
        String token = order.getOptionToken();
        if (token == null || token.isBlank()) {
            log.error("Zerodha symbol resolution failed: orderId={} has no option_token — nothing to look up",
                    order.getId());
            return null;
        }

        Integer instrumentToken;
        try {
            instrumentToken = Integer.valueOf(token.trim());
        } catch (NumberFormatException ex) {
            // HISTORICAL_ICICI writes a natural-key string ("NIFTY|NFO|2024-01-04|23400|CE")
            // here instead of a broker token. That source is replay-only and never
            // reaches a live placement, so this is a misconfiguration, not a data gap.
            log.error("Zerodha symbol resolution failed: orderId={} option_token='{}' is not a broker "
                            + "instrument token. This is the historical (CSV) data source's natural key — "
                            + "live Zerodha placement requires backtest.data-source=BROKER.",
                    order.getId(), token);
            return null;
        }

        InstrumentDetails row = instrumentDetailsRepository.findById(instrumentToken).orElse(null);
        if (row == null) {
            log.error("Zerodha symbol resolution failed: orderId={} option_token={} has no instrument_details "
                            + "row. The local instrument dump is stale relative to the ledger — reload it "
                            + "(instrument={} strike={} {}).",
                    order.getId(), instrumentToken, order.getInstrumentName(),
                    order.getOptionStrike(), order.getOptionType());
            return null;
        }

        String symbol = row.getTradingSymbol() == null ? null : row.getTradingSymbol().trim();
        if (symbol == null || symbol.isEmpty()) {
            log.error("Zerodha symbol resolution failed: instrument_details row for token={} carries no "
                    + "tradingsymbol (orderId={})", instrumentToken, order.getId());
            return null;
        }

        if (!matchesLedger(order, row)) {
            log.error("Zerodha symbol resolution REFUSED: instrument_details token={} is '{}' (strike={} type={}) "
                            + "but trade_order {} recorded strike={} type={}. The dump has been re-seeded and the "
                            + "token now names a different contract — placing this order would trade the wrong leg.",
                    instrumentToken, symbol, row.getStrike(), row.getInstrumentType(),
                    order.getId(), order.getOptionStrike(), order.getOptionType());
            return null;
        }

        // Exchange comes from the row rather than a constant: index options are NFO
        // but the same dump lists BFO contracts (BANKEX/SENSEX), and a wrong exchange
        // is a broker-side rejection. NFO stays the fallback for rows loaded before
        // the column was populated.
        String exchange = row.getExchange() == null || row.getExchange().isBlank()
                ? EXCHANGE_NFO
                : row.getExchange().trim();

        log.debug("Zerodha symbol resolved: orderId={} token={} -> {} on {}",
                order.getId(), instrumentToken, symbol, exchange);
        return new Contract(symbol, exchange);
    }

    /**
     * True when the dump row describes the same contract the ledger row does.
     * A ledger column that is null is not evidence of a mismatch, so it passes —
     * only a stated value that disagrees refuses.
     */
    private static boolean matchesLedger(TradeOrder order, InstrumentDetails row) {
        Integer ledgerStrike = order.getOptionStrike();
        if (ledgerStrike != null && row.getStrike() != null
                && row.getStrike().compareTo(BigDecimal.valueOf(ledgerStrike)) != 0) {
            return false;
        }
        String ledgerType = order.getOptionType();
        return ledgerType == null || row.getInstrumentType() == null
                || ledgerType.trim().equalsIgnoreCase(row.getInstrumentType().trim());
    }
}
