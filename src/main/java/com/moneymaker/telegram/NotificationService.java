package com.moneymaker.telegram;

import com.moneymaker.entity.TradeOrder;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.HeartbeatStatus;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Notification facade. Other packages depend on this class (not Telegram
 * directly) so future channels can be plugged in without touching callers.
 *
 * <h3>Dedupe and throttling</h3>
 * Two general-purpose helpers prevent message storms:
 * <ul>
 *   <li>{@link #sendIfChanged(String, String)} — fire only when the message
 *       for this dedupe key differs from the last one sent. Pair with a
 *       recovery method that checks the dedupe state to fire an "all-clear".</li>
 *   <li>{@link #sendThrottled(String, Duration, String)} — fire only if the
 *       last send for this key was more than {@code cooldown} ago. Use for
 *       events that vary slightly each call (timestamp embedded in message)
 *       but should still respect a quiet period.</li>
 * </ul>
 *
 * <h3>Backtest-mode suppression</h3>
 * The master gate lives in {@link TelegramNotifier}: when
 * {@code app.mode=backtest} and {@code telegram.backtest-enabled=false} (default),
 * every {@code telegram.send(...)} below becomes a no-op. So this class doesn't
 * need its own per-method check anymore — the alerts compose normally and the
 * single configuration property decides whether they actually go out.
 */
@Slf4j
@Service
public class NotificationService {

    private static final DateTimeFormatter TS =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneId.of("Asia/Kolkata"));

    private static final String KEY_MARKET_DATA = "market-data";
    private static final String KEY_REJECT_PREFIX = "order-rejected:";

    private final TelegramNotifier telegram;

    private final Map<String, String> dedupeState = new ConcurrentHashMap<>();
    private final Map<String, Instant> throttleState = new ConcurrentHashMap<>();

    public NotificationService(TelegramNotifier telegram) {
        this.telegram = telegram;
    }

    /* -------------------- general-purpose helpers -------------------- */

    /** Sends only when {@code message} differs from the last one sent for {@code dedupeKey}. */
    public void sendIfChanged(String dedupeKey, String message) {
        if (Objects.equals(message, dedupeState.get(dedupeKey))) return;
        dedupeState.put(dedupeKey, message);
        telegram.send(message);
    }

    /** Drops any remembered state for the given dedupe key. */
    public void clearDedupe(String dedupeKey) {
        dedupeState.remove(dedupeKey);
        throttleState.remove(dedupeKey);
    }

    /** Sends only if the last send for {@code dedupeKey} was more than {@code cooldown} ago. */
    public void sendThrottled(String dedupeKey, Duration cooldown, String message) {
        Instant last = throttleState.get(dedupeKey);
        Instant now = Instant.now();
        if (last != null && Duration.between(last, now).compareTo(cooldown) < 0) return;
        throttleState.put(dedupeKey, now);
        telegram.send(message);
    }

    /* -------------------- login / heartbeat -------------------- */

    public void alertLoginSuccess(Broker broker, String userId) {
        telegram.send(String.format("[OK] *%s* login successful (%s) at %s IST",
                broker, userId == null ? "-" : userId, TS.format(Instant.now())));
    }

    public void alertLoginFailed(Broker broker, String reason) {
        telegram.send(String.format("[FAIL] *%s* login FAILED at %s IST\nReason: `%s`",
                broker, TS.format(Instant.now()), safe(reason)));
    }

    public void alertSessionLost(Broker broker, HeartbeatStatus status, String reason) {
        telegram.send(String.format("[ALERT] *%s* session lost (%s) at %s IST\nDetails: `%s`",
                broker, status, TS.format(Instant.now()), safe(reason)));
    }

    public void alertNoData(Broker broker, String reason) {
        telegram.send(String.format("[NO-DATA] *%s* token valid but NO market data at %s IST\nDetails: `%s`",
                broker, TS.format(Instant.now()), safe(reason)));
    }

    public void alertRecovered(Broker broker) {
        telegram.send(String.format("[RECOVERED] *%s* heartbeat back to OK at %s IST",
                broker, TS.format(Instant.now())));
    }

    /* -------------------- market data API health -------------------- */

    public void alertMarketDataDown(String reason) {
        sendIfChanged(KEY_MARKET_DATA,
                String.format("[ALERT] Market-data API failing at %s IST\nReason: `%s`",
                        TS.format(Instant.now()), safe(reason)));
    }

    public void alertMarketDataUp() {
        if (!dedupeState.containsKey(KEY_MARKET_DATA)) return;
        dedupeState.remove(KEY_MARKET_DATA);
        telegram.send(String.format("[RECOVERED] Market-data API back online at %s IST",
                TS.format(Instant.now())));
    }

    /* -------------------- orders -------------------- */

    public void alertOrderOpened(TradeOrder o) {
        if (o == null) return;
        telegram.send(String.format(
                "[ORDER OPEN] id=%d %s %s %s %s @ %s (cfg=%s)",
                o.getId(),
                o.getEntryDirection(),
                safe(o.getInstrumentName()),
                String.valueOf(o.getOptionStrike()),
                safe(o.getOptionType()),
                o.getEntryPrice(),
                o.getTradeConfigId()));
    }

    public void alertOrderClosed(TradeOrder o) {
        if (o == null) return;
        telegram.send(String.format(
                "[ORDER CLOSE] id=%d %s %s %s entry=%s exit=%s P/L=%s",
                o.getId(),
                safe(o.getInstrumentName()),
                String.valueOf(o.getOptionStrike()),
                safe(o.getOptionType()),
                o.getEntryPrice(),
                o.getExitPrice(),
                o.getProfit()));
    }

    public void alertOrderForceClosed(TradeOrder o) {
        if (o == null) return;
        telegram.send(String.format(
                "[ORDER FORCE-CLOSE] id=%d %s %s %s entry=%s exit=%s P/L=%s",
                o.getId(),
                safe(o.getInstrumentName()),
                String.valueOf(o.getOptionStrike()),
                safe(o.getOptionType()),
                o.getEntryPrice(),
                o.getExitPrice(),
                o.getProfit()));
    }

    public void alertOrderRejected(String brokerName, Long orderId, String reason) {
        String key = KEY_REJECT_PREFIX + (brokerName == null ? "?" : brokerName.toUpperCase(Locale.ROOT));
        sendIfChanged(key, String.format(
                "[REJECT] %s rejected order id=%s at %s IST\nReason: `%s`",
                brokerName, orderId, TS.format(Instant.now()), safe(reason)));
    }

    /* -------------------- helpers -------------------- */

    private static String safe(String s) {
        return s == null ? "-" : s.replace("`", "'");
    }
}
