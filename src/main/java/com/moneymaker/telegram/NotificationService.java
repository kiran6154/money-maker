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

    /**
     * Drops ALL remembered dedupe / throttle state. Used by
     * {@code BacktestResetService} between backtest runs so a second run in
     * the same JVM doesn't suppress alerts the first run already sent.
     * <b>Do not call from live-mode runtime paths</b> — would re-fire every
     * dedup'd alert on the next emit.
     */
    public void clearAllDedupeState() {
        dedupeState.clear();
        throttleState.clear();
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

    /* -------------------- session health -------------------- */

    /**
     * Throttled alert for "no active broker session" surfaces from non-heartbeat
     * paths (e.g. the backtest tick loop). Heartbeat itself already alerts via
     * {@link #alertSessionLost(Broker, HeartbeatStatus, String)} on the
     * {@code OK → NO_SESSION} transition; this method exists so a per-tick
     * code path can emit at most one message per {@code cooldown} window
     * without inventing its own state machine.
     */
    public void alertNoActiveSession(String reason) {
        sendThrottled("no-session", Duration.ofMinutes(5),
                String.format("[ALERT] No active broker session at %s IST\nReason: `%s`",
                        TS.format(Instant.now()), safe(reason)));
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

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter TIME_FMT = DateTimeFormatter.ofPattern("HH:mm:ss");

    public void alertOrderOpened(TradeOrder o) {
        if (o == null) return;
        StringBuilder sb = new StringBuilder("[ORDER OPEN]").append('\n');
        sb.append("  id         : ").append(o.getId()).append('\n');
        sb.append("  strategy   : ").append(o.getStrategyId()).append('\n');
        sb.append("  config     : ").append(o.getTradeConfigId()).append('\n');
        sb.append("  instrument : ").append(safe(o.getInstrumentName())).append('\n');
        sb.append("  strike     : ").append(o.getOptionStrike()).append(' ').append(safe(o.getOptionType())).append('\n');
        sb.append("  direction  : ").append(safe(o.getEntryDirection())).append('\n');
        sb.append("  entry rule : ").append(safe(o.getEntryReason())).append('\n');
        sb.append("  entry time : ").append(formatDateTime(o.getEntryTime())).append('\n');
        sb.append("  entry      : ").append(o.getEntryPrice());
        telegram.send(sb.toString());
    }

    public void alertOrderClosed(TradeOrder o) {
        if (o == null) return;
        StringBuilder sb = new StringBuilder("[ORDER CLOSE]").append('\n');
        sb.append("  id         : ").append(o.getId()).append('\n');
        sb.append("  strategy   : ").append(o.getStrategyId()).append('\n');
        sb.append("  config     : ").append(o.getTradeConfigId()).append('\n');
        sb.append("  instrument : ").append(safe(o.getInstrumentName())).append('\n');
        sb.append("  strike     : ").append(o.getOptionStrike()).append(' ').append(safe(o.getOptionType())).append('\n');
        sb.append("  entry rule : ").append(safe(o.getEntryReason())).append('\n');
        sb.append("  entry time : ").append(formatDateTime(o.getEntryTime())).append('\n');
        sb.append("  entry      : ").append(o.getEntryPrice()).append('\n');
        sb.append("  exit time  : ").append(formatDateTime(o.getExitTime())).append('\n');
        sb.append("  exit       : ").append(o.getExitPrice()).append('\n');
        sb.append("  exit reason: ").append(safe(o.getExitReason())).append('\n');
        sb.append("  P/L        : ").append(o.getProfit());
        telegram.send(sb.toString());
    }

    /**
     * <b>Critical</b> alert: a force-close attempt placed via the broker
     * returned null. The row stays {@code OPEN} with
     * {@code fill_status=EXIT_FAILED} so it can be retried (manually or by
     * the next {@code DaySummaryScheduler} tick); meanwhile the broker
     * position is unattended, so ops needs to know now.
     */
    public void alertOrderExitFailed(TradeOrder o, String reason) {
        if (o == null) return;
        StringBuilder sb = new StringBuilder("[CRITICAL] ORDER EXIT FAILED").append('\n');
        sb.append("  id         : ").append(o.getId()).append('\n');
        sb.append("  config     : ").append(o.getTradeConfigId()).append('\n');
        sb.append("  instrument : ").append(safe(o.getInstrumentName())).append('\n');
        sb.append("  strike     : ").append(o.getOptionStrike()).append(' ').append(safe(o.getOptionType())).append('\n');
        sb.append("  direction  : ").append(safe(o.getEntryDirection())).append('\n');
        sb.append("  entry      : ").append(o.getEntryPrice()).append(" @ ").append(formatDateTime(o.getEntryTime())).append('\n');
        sb.append("  reason     : ").append(safe(reason)).append('\n');
        sb.append("  ACTION     : broker position still OPEN — reconcile manually or wait for retry");
        telegram.send(sb.toString());
    }

    public void alertOrderForceClosed(TradeOrder o) {
        if (o == null) return;
        StringBuilder sb = new StringBuilder("[ORDER FORCE-CLOSE]").append('\n');
        sb.append("  id         : ").append(o.getId()).append('\n');
        sb.append("  strategy   : ").append(o.getStrategyId()).append('\n');
        sb.append("  config     : ").append(o.getTradeConfigId()).append('\n');
        sb.append("  instrument : ").append(safe(o.getInstrumentName())).append('\n');
        sb.append("  strike     : ").append(o.getOptionStrike()).append(' ').append(safe(o.getOptionType())).append('\n');
        sb.append("  entry rule : ").append(safe(o.getEntryReason())).append('\n');
        sb.append("  entry time : ").append(formatDateTime(o.getEntryTime())).append('\n');
        sb.append("  entry      : ").append(o.getEntryPrice()).append('\n');
        sb.append("  exit time  : ").append(formatDateTime(o.getExitTime())).append('\n');
        sb.append("  exit       : ").append(o.getExitPrice()).append('\n');
        sb.append("  P/L        : ").append(o.getProfit());
        telegram.send(sb.toString());
    }

    /** Compact {@code yyyy-MM-dd HH:mm:ss} or {@code -} when null. */
    private static String formatDateTime(java.time.LocalDateTime ts) {
        if (ts == null) return "-";
        return ts.toLocalDate().format(DATE_FMT) + " " + ts.toLocalTime().format(TIME_FMT);
    }

    /**
     * End-of-day digest. One message per trading day; once-per-day gating is
     * the caller's responsibility (see {@code DaySummaryScheduler} +
     * {@link com.moneymaker.state.DailyEventGuard}). Body is pre-formatted by
     * the scheduler so this method stays a thin pass-through.
     */
    public void alertDaySummary(String body) {
        if (body == null || body.isBlank()) return;
        telegram.send(body);
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
