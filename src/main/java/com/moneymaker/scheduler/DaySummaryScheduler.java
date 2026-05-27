package com.moneymaker.scheduler;

import com.moneymaker.entity.TradeOrder;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

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
 * <p>Skipped entirely in backtest mode — {@code BacktestAnalysisService}
 * already calls {@link OrderService#forceCloseOpenPositions(LocalDate, LocalDateTime)}
 * at the end of every replay day, and we don't want a live Telegram to fire on
 * every backtest boot.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DaySummaryScheduler {

    private static final String ALERT_KEY = "day-summary";
    private static final DateTimeFormatter TIME_FMT = DateTimeFormatter.ofPattern("HH:mm");

    private final OrderService orderService;
    private final TradeOrderRepository tradeOrderRepository;
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
        LocalDate today = LocalDate.now(marketHours.zone());
        if (today.getDayOfWeek() == DayOfWeek.SATURDAY || today.getDayOfWeek() == DayOfWeek.SUNDAY) {
            return;
        }
        if (!dailyEventGuard.firstTime(ALERT_KEY, today)) {
            log.info("[day-summary] {} — already fired today, skipping", today);
            return;
        }

        // M3: force-close happens 5 min before market close (15:25 default)
        // so the broker exit order is accepted before the hard 15:30 cliff.
        LocalDateTime closeAt = marketHours.forceCloseToday();
        log.info("[day-summary] {} — running end-of-day at {}", today, closeAt);

        int forceClosed = 0;
        try {
            forceClosed = orderService.forceCloseOpenPositions(today, closeAt);
        } catch (Exception ex) {
            log.error("[day-summary] forceCloseOpenPositions failed", ex);
        }

        String body = buildSummary(today, forceClosed);
        log.info("[day-summary] {}\n{}", today, body);
        try {
            notifier.alertDaySummary(body);
        } catch (Exception ex) {
            log.error("[day-summary] Telegram send failed", ex);
        }
    }

    /* ---------------- summary builder ---------------- */

    private String buildSummary(LocalDate date, int forceClosed) {
        LocalDateTime from = date.atStartOfDay();
        LocalDateTime to = date.plusDays(1).atStartOfDay().minusNanos(1);
        List<TradeOrder> trades = tradeOrderRepository.findByEntryTimeBetween(from, to);

        if (trades.isEmpty()) {
            return String.format(
                    "*Day Summary — %s*%n  no trades%n  market window: %s–%s",
                    date, TIME_FMT.format(marketHours.marketOpenToday()),
                    TIME_FMT.format(marketHours.marketCloseToday()));
        }

        int total = trades.size();
        int closed = 0, openLeftover = 0, winners = 0, losers = 0, scratches = 0;
        BigDecimal totalPnl = BigDecimal.ZERO;
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
                byConfig.merge(t.getTradeConfigId(), pnl, BigDecimal::add);
                byExitReason.merge(t.getExitReason() == null ? "-" : t.getExitReason(), 1, Integer::sum);
            } else {
                openLeftover++;
            }
        }

        StringBuilder sb = new StringBuilder();
        String nl = System.lineSeparator();
        sb.append("*Day Summary — ").append(date).append("*").append(nl);
        sb.append("  window      : ")
          .append(TIME_FMT.format(marketHours.marketOpenToday())).append("–")
          .append(TIME_FMT.format(marketHours.marketCloseToday())).append(nl);
        sb.append("  trades      : ").append(total).append(nl);
        sb.append("  closed      : ").append(closed).append(nl);
        sb.append("  open left   : ").append(openLeftover).append(nl);
        sb.append("  force-closed: ").append(forceClosed).append(nl);
        sb.append("  winners     : ").append(winners).append(nl);
        sb.append("  losers      : ").append(losers).append(nl);
        sb.append("  scratches   : ").append(scratches).append(nl);
        sb.append("  P/L (per-sh): ").append(totalPnl).append(nl);

        if (biggestWinner != null) {
            sb.append("  best winner : id=").append(biggestWinner.getId())
              .append(" ").append(biggestWinner.getInstrumentName())
              .append(" ").append(biggestWinner.getOptionStrike())
              .append(" ").append(biggestWinner.getOptionType())
              .append(" pnl=").append(biggestWinner.getProfit()).append(nl);
        }
        if (biggestLoser != null) {
            sb.append("  worst loser : id=").append(biggestLoser.getId())
              .append(" ").append(biggestLoser.getInstrumentName())
              .append(" ").append(biggestLoser.getOptionStrike())
              .append(" ").append(biggestLoser.getOptionType())
              .append(" pnl=").append(biggestLoser.getProfit()).append(nl);
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
                    .map(e -> "#" + e.getKey() + "=" + e.getValue())
                    .reduce((a, b) -> a + ", " + b).orElse("-"));
        }

        return sb.toString();
    }
}
