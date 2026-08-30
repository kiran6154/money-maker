package com.moneymaker.scheduler;

import com.moneymaker.entity.TradeConfig;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

/**
 * Fires once after market close (15:31 IST by default) to:
 *
 * <ol>
 *   <li>Force-close any {@code OPEN} trade still on the books at
 *       {@link MarketHoursService#marketCloseToday()}, so the day's ledger
 *       is complete before we summarise it.</li>
 *   <li>Build a compact per-day digest from {@code trade_order} rows and
 *       fire it through {@link NotificationService#alertDaySummary(String)}.</li>
 * </ol>
 *
 * <p>{@link DailyEventGuard} backstops the schedule — a JVM restart at 17:00
 * will <b>not</b> re-fire the summary; the persisted row in {@code alert_state}
 * still wins.</p>
 *
 * <h3>Two guard keys, not one (GAPS #5)</h3>
 * The two steps fail independently, so they are gated independently:
 * {@code day-summary-forceclose} is written once the force-close has run, and
 * {@code day-summary-telegram} only once the digest has actually reached
 * Telegram. A failed send therefore leaves its key unwritten and the next tick
 * retries <i>only</i> the digest — it will not force-close a second time, and a
 * delivered digest is never re-sent. Before this the single {@code day-summary}
 * key was written up-front, so a network blip on the Telegram POST silently ate
 * the summary for the day.
 *
 * <p>With the default once-a-day cron there is no second tick to retry on; the
 * recovery paths are an operator-set repeating {@code app.market.summary-cron}
 * (which the two-key gate now makes safe to run every few minutes) and
 * {@code POST /api/admin/day-summary} — the manual re-run of GAPS #6, which calls
 * {@link #runEndOfDayFor(LocalDate, boolean)} directly.</p>
 *
 * <p>Skipped entirely in backtest mode — {@code BacktestAnalysisService}
 * already calls {@link OrderService#forceCloseOpenPositions(LocalDate, LocalDateTime)}
 * at the end of every replay day, and we don't want a live Telegram to fire on
 * every backtest boot.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DaySummaryScheduler {

    /**
     * The single key used before the two-key split. Still consulted so that a
     * deploy landing mid-afternoon, after the old code already fired and marked
     * the day, doesn't read the two new keys as "never ran" and re-send.
     */
    private static final String LEGACY_ALERT_KEY = "day-summary";
    private static final String KEY_FORCE_CLOSE = "day-summary-forceclose";
    private static final String KEY_TELEGRAM = "day-summary-telegram";

    private static final DateTimeFormatter TIME_FMT = DateTimeFormatter.ofPattern("HH:mm");

    private final OrderService orderService;
    private final TradeOrderRepository tradeOrderRepository;
    private final TradeConfigRepository tradeConfigRepository;
    private final MarketHoursService marketHours;
    private final NotificationService notifier;
    private final DailyEventGuard dailyEventGuard;

    @Value("${app.mode:live}")
    private String appMode;

    /**
     * 15:31 IST MON-FRI. One minute after the configured close gives the
     * 15:30 PositionScheduler tick time to settle before we force-close.
     */
    @Scheduled(cron = "${app.market.summary-cron:0 31 15 * * MON-FRI}", zone = "${app.market.timezone:Asia/Kolkata}")
    public void runEndOfDay() {
        if (!"live".equalsIgnoreCase(appMode)) {
            log.debug("[day-summary] skipped — app.mode={}", appMode);
            return;
        }
        runEndOfDayFor(LocalDate.now(marketHours.zone()));
    }

    /**
     * The end-of-day work for one date, with the wall clock supplied rather than
     * read. Split out of the {@code @Scheduled} method so the day's date is a
     * parameter and not an ambient fact — which is what lets the tests exercise a
     * fixed weekday, and what the manual re-run endpoint (GAPS #6) calls.
     */
    void runEndOfDayFor(LocalDate today) {
        runEndOfDayFor(today, false);
    }

    /**
     * @param force bypass {@link DailyEventGuard} and run both halves regardless
     *              of what has already fired for this date. The manual re-run
     *              endpoint's escape hatch (GAPS #6) for the case the guard cannot
     *              distinguish: the digest went out, but it was wrong — it fired
     *              before a delayed close, so the day it summarised was not over.
     *              Everything the guard <i>can</i> see (a missed run, a Telegram
     *              that failed to send) is already handled by re-running without
     *              force, which is why force is not the default.
     *
     * <p>Force is safe on the force-close half too:
     * {@link OrderService#forceCloseOpenPositions} only ever selects rows still in
     * status {@code OPEN}, so a second pass over an already-swept day closes
     * nothing and returns 0.</p>
     *
     * @return the number of positions force-closed on this pass
     */
    public int runEndOfDayFor(LocalDate today, boolean force) {
        if (today.getDayOfWeek() == DayOfWeek.SATURDAY || today.getDayOfWeek() == DayOfWeek.SUNDAY) {
            return 0;
        }
        boolean legacyAlreadyFired = !force && dailyEventGuard.alreadyFired(LEGACY_ALERT_KEY, today);

        // Date-aware, not "today's" close: a re-run for a past date must stamp
        // exits with that day's close, not the current one.
        LocalDateTime closeAt = marketHours.marketCloseOn(today);
        log.info("[day-summary] {} — running end-of-day at {}{}", today, closeAt,
                force ? " (force: guard bypassed)" : "");

        // ---- half 1: force-close. Marked only after it returns cleanly. ----
        int forceClosed = 0;
        if (legacyAlreadyFired || (!force && dailyEventGuard.alreadyFired(KEY_FORCE_CLOSE, today))) {
            log.info("[day-summary] {} — force-close already ran today, skipping it", today);
        } else {
            try {
                forceClosed = orderService.forceCloseOpenPositions(today, closeAt);
                dailyEventGuard.firstTime(KEY_FORCE_CLOSE, today);
            } catch (Exception ex) {
                // Left unmarked on purpose: an unclosed position is worth
                // another attempt, and the method is idempotent (it only ever
                // selects rows still in status OPEN).
                log.error("[day-summary] forceCloseOpenPositions failed — leaving '{}' unmarked for retry",
                        KEY_FORCE_CLOSE, ex);
            }
        }

        // ---- half 2: the digest. Marked only after Telegram confirms. ----
        if (legacyAlreadyFired || (!force && dailyEventGuard.alreadyFired(KEY_TELEGRAM, today))) {
            log.info("[day-summary] {} — digest already delivered today, skipping it", today);
            return forceClosed;
        }

        String body = buildSummary(today, forceClosed);
        log.info("[day-summary] {}\n{}", today, body);

        boolean delivered;
        try {
            delivered = notifier.alertDaySummary(body);
        } catch (Exception ex) {
            log.error("[day-summary] Telegram send failed", ex);
            delivered = false;
        }

        if (delivered) {
            dailyEventGuard.firstTime(KEY_TELEGRAM, today);
        } else {
            log.warn("[day-summary] {} — digest NOT delivered; '{}' left unmarked so the next tick retries",
                    today, KEY_TELEGRAM);
        }
        return forceClosed;
    }

    /* ---------------- summary builder ---------------- */

    private String buildSummary(LocalDate date, int forceClosed) {
        LocalDateTime from = date.atStartOfDay();
        LocalDateTime to = date.plusDays(1).atStartOfDay().minusNanos(1);
        List<TradeOrder> trades = tradeOrderRepository.findByEntryTimeBetween(from, to);

        if (trades.isEmpty()) {
            return String.format(
                    "*Day Summary — %s*%n  no trades%n  market window: %s–%s",
                    date, TIME_FMT.format(marketHours.marketOpenOn(date)),
                    TIME_FMT.format(marketHours.marketCloseOn(date)));
        }

        Map<Integer, Integer> lotQuantities = lotQuantitiesFor(trades);

        int total = trades.size();
        int closed = 0, openLeftover = 0, winners = 0, losers = 0, scratches = 0;
        BigDecimal totalPnl = BigDecimal.ZERO;   // per-share, as stored on the row
        BigDecimal totalNet  = BigDecimal.ZERO;  // per-share × lot quantity
        int unpricedTrades = 0;
        Set<Integer> unpricedConfigs = new TreeSet<>();
        TradeOrder biggestWinner = null;
        TradeOrder biggestLoser  = null;
        Map<String, Integer> byExitReason = new HashMap<>();
        Map<Integer, BigDecimal> byConfig  = new TreeMap<>();

        for (TradeOrder t : trades) {
            if ("CLOSED".equalsIgnoreCase(t.getStatus())) {
                closed++;
                BigDecimal pnl = t.getProfit() == null ? BigDecimal.ZERO : t.getProfit();
                totalPnl = totalPnl.add(pnl);
                int sign = pnl.signum();
                if (sign > 0) {
                    winners++;
                    if (biggestWinner == null || pnl.compareTo(biggestWinner.getProfit()) > 0) biggestWinner = t;
                } else if (sign < 0) {
                    losers++;
                    if (biggestLoser == null || pnl.compareTo(biggestLoser.getProfit()) < 0) biggestLoser = t;
                } else {
                    scratches++;
                }
                BigDecimal net = netPnl(pnl, lotQuantities.get(t.getTradeConfigId()));
                if (net == null) {
                    // The multiplier is gone (config deleted, or lot_quantity
                    // null / non-positive). Counting the trade at ×1 would read
                    // as a real rupee figure, so it is excluded and declared.
                    unpricedTrades++;
                    unpricedConfigs.add(t.getTradeConfigId());
                } else {
                    totalNet = totalNet.add(net);
                    byConfig.merge(t.getTradeConfigId(), net, BigDecimal::add);
                }
                byExitReason.merge(t.getExitReason() == null ? "-" : t.getExitReason(), 1, Integer::sum);
            } else {
                openLeftover++;
            }
        }

        StringBuilder sb = new StringBuilder();
        String nl = System.lineSeparator();
        sb.append("*Day Summary — ").append(date).append("*").append(nl);
        sb.append("  window      : ")
          .append(TIME_FMT.format(marketHours.marketOpenOn(date))).append("–")
          .append(TIME_FMT.format(marketHours.marketCloseOn(date))).append(nl);
        sb.append("  trades      : ").append(total).append(nl);
        sb.append("  closed      : ").append(closed).append(nl);
        sb.append("  open left   : ").append(openLeftover).append(nl);
        sb.append("  force-closed: ").append(forceClosed).append(nl);
        sb.append("  winners     : ").append(winners).append(nl);
        sb.append("  losers      : ").append(losers).append(nl);
        sb.append("  scratches   : ").append(scratches).append(nl);
        sb.append("  P/L (per-sh): ").append(totalPnl).append(nl);
        sb.append("  P/L (net)   : ").append(totalNet.setScale(2, RoundingMode.HALF_UP)).append(nl);
        if (unpricedTrades > 0) {
            sb.append("  no lot qty  : ").append(unpricedTrades)
              .append(" trade(s) excluded from net — config(s) ")
              .append(unpricedConfigs.stream().map(id -> "#" + id)
                      .reduce((a, b) -> a + ", " + b).orElse("-"))
              .append(nl);
        }

        if (biggestWinner != null) {
            appendExtreme(sb, "  best winner : ", biggestWinner, lotQuantities, nl);
        }
        if (biggestLoser != null) {
            appendExtreme(sb, "  worst loser : ", biggestLoser, lotQuantities, nl);
        }

        if (!byExitReason.isEmpty()) {
            sb.append("  exit reasons: ");
            sb.append(byExitReason.entrySet().stream()
                    .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                    .map(e -> e.getKey() + "=" + e.getValue())
                    .reduce((a, b) -> a + ", " + b).orElse("-"));
            sb.append(nl);
        }

        if (!byConfig.isEmpty()) {
            sb.append("  by config   : ");
            sb.append(byConfig.entrySet().stream()
                    .sorted(Map.Entry.<Integer, BigDecimal>comparingByValue(
                            Comparator.reverseOrder()))
                    .map(e -> "#" + e.getKey() + "=" + e.getValue().setScale(2, RoundingMode.HALF_UP))
                    .reduce((a, b) -> a + ", " + b).orElse("-"));
        }

        return sb.toString();
    }

    /**
     * One line for the day's best / worst trade, carrying both units so neither
     * can be misread: {@code pnl/sh} is the number on the ledger row,
     * {@code net} is what actually hit the account.
     *
     * <p>The ranking itself stays on the per-share figure — the same trade the
     * previous version of this digest picked. Ranking on net would silently
     * change which trade gets named on any day where two configs trade different
     * lot sizes, and that is a reporting decision, not part of this fix.</p>
     */
    private void appendExtreme(StringBuilder sb, String label, TradeOrder t,
                               Map<Integer, Integer> lotQuantities, String nl) {
        BigDecimal net = netPnl(t.getProfit(), lotQuantities.get(t.getTradeConfigId()));
        sb.append(label).append("id=").append(t.getId())
          .append(" ").append(t.getInstrumentName())
          .append(" ").append(t.getOptionStrike())
          .append(" ").append(t.getOptionType())
          .append(" pnl/sh=").append(t.getProfit())
          .append(" net=").append(net == null ? "?" : net.setScale(2, RoundingMode.HALF_UP))
          .append(nl);
    }

    /* ---------------- lot multiplication (GAPS #2) ---------------- */

    /**
     * {@code trade_config_id → lot_quantity} for every config that traded today.
     *
     * <p>{@code trade_order.profit} is per-share by design — the ledger stores the
     * premium move, not the rupee outcome — so the digest has to supply the
     * multiplier. {@code TradeConfig.lotQuantity} is the right one because it is
     * the <i>same</i> number the placement services hand the broker as the order
     * quantity (see {@code ZerodhaOrderPlacementService.quantity}, and
     * {@code EodDowntrendDetectionService}, which seeds it from
     * {@code Instrument.lotQty}). Multiplying by anything else would produce a
     * P&amp;L that disagrees with the size actually traded.</p>
     *
     * <p>Read live rather than snapshotted onto the row: no
     * {@code lot_quantity_at_entry} column exists today, and adding one is the
     * schema half of GAPS #2 that this change deliberately leaves open. The
     * consequence is that editing a config's {@code lotQuantity} between entry
     * and 15:31 makes the digest value the <i>edited</i> size — noted in
     * {@code docs/GAPS.md}.</p>
     *
     * <p>Configs whose row has been deleted, or whose {@code lot_quantity} is
     * null / non-positive, are simply absent from the map; callers exclude those
     * trades from the net rather than assuming a size.</p>
     */
    private Map<Integer, Integer> lotQuantitiesFor(List<TradeOrder> trades) {
        Set<Integer> configIds = new TreeSet<>();
        for (TradeOrder t : trades) {
            if (t.getTradeConfigId() != null) configIds.add(t.getTradeConfigId());
        }
        if (configIds.isEmpty()) return Map.of();

        Map<Integer, Integer> lots = new HashMap<>();
        for (TradeConfig tc : tradeConfigRepository.findAllById(configIds)) {
            if (tc == null || tc.getId() == null) continue;
            Integer qty = tc.getLotQuantity();
            if (qty != null && qty > 0) lots.put(tc.getId(), qty);
        }
        return lots;
    }

    /** Per-share P&amp;L × lot quantity, or {@code null} when the quantity is unknown. */
    private static BigDecimal netPnl(BigDecimal perShare, Integer lotQuantity) {
        if (perShare == null || lotQuantity == null || lotQuantity <= 0) return null;
        return perShare.multiply(BigDecimal.valueOf(lotQuantity));
    }
}
