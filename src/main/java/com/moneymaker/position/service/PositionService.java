package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;

/**
 * Walks every {@link TradeOrder} in {@code OPEN} status each
 * {@code PositionScheduler} tick and updates monitor columns
 * ({@code peakProfit}, {@code peakLoss}, {@code lastMonitoredPrice},
 * {@code lastMonitoredAt}). When the unrealised P&L breaches the
 * {@code targetAtEntry} or {@code stopLossAtEntry} thresholds snapshotted on
 * the row at entry, delegates to {@code OrderService.closeManually} to record
 * the exit.
 *
 * <p>Quote source is broker-agnostic via {@link PositionMonitorFactory}:
 * backtest reads cached candles, live brokers call their LTP endpoint.
 *
 * <p><b>Why we read the snapshot, not {@code SharedData.combinedDto}.</b>
 * SharedData population is timing-sensitive (live cron at 09:16, backtest
 * per-tick), and a config edit mid-trade should not retroactively close
 * already-open positions. {@code OrderService.openOrder} stamps
 * {@code targetAtEntry} / {@code stopLossAtEntry} from the live config
 * exactly once at entry; everything downstream reads from the row.
 */
@Slf4j
@Service
public class PositionService {

    private static final String STATUS_OPEN = "OPEN";

    private final TradeOrderRepository tradeOrderRepository;
    private final PositionMonitorFactory monitorFactory;
    private final OrderService orderService;

    public PositionService(TradeOrderRepository tradeOrderRepository,
                           PositionMonitorFactory monitorFactory,
                           OrderService orderService) {
        this.tradeOrderRepository = Objects.requireNonNull(tradeOrderRepository, "tradeOrderRepository must not be null");
        this.monitorFactory = Objects.requireNonNull(monitorFactory, "monitorFactory must not be null");
        this.orderService = Objects.requireNonNull(orderService, "orderService must not be null");
    }

    public void processPositions() {
        List<TradeOrder> open = tradeOrderRepository.findByStatus(STATUS_OPEN);
        if (open.isEmpty()) return;

        PositionMonitorService monitor = monitorFactory.active();

        for (TradeOrder order : open) {
            try {
                handleOne(order, monitor);
            } catch (Exception ex) {
                log.error("PositionService failed for orderId={}", order.getId(), ex);
            }
        }
    }

    private void handleOne(TradeOrder order, PositionMonitorService monitor) {
        Quote quote = monitor.currentQuote(order);
        if (quote == null || quote.price() == null) {
            log.debug("PositionService: no quote for orderId={} optionToken={} — skipping tick",
                    order.getId(), order.getOptionToken());
            return;
        }
        BigDecimal price = quote.price();
        // Use the quote's "as-of" timestamp so the ledger records exits at the
        // candle time in backtest (not wall-clock). Falls back to now() if a
        // monitor implementation forgets to set asOf.
        LocalDateTime asOf = quote.asOf() != null ? quote.asOf() : LocalDateTime.now();

        // Don't monitor a trade on the same (or earlier) candle that opened it.
        // Entry is recorded at the trigger candle's start timestamp; the first
        // legitimate monitoring opportunity is the next candle. Without this
        // guard a TARGET / STOP_LOSS could fire instantly with exit_time =
        // entry_time, since the same backtest tick that opens the trade also
        // runs the position monitor against the same cached candle.
        if (order.getEntryTime() != null && !asOf.isAfter(order.getEntryTime())) {
            log.debug("PositionService: orderId={} quote asOf={} not after entry={} — skipping",
                    order.getId(), asOf, order.getEntryTime());
            return;
        }

        BigDecimal pnl = perShareProfit(order.getEntryDirection(), order.getEntryPrice(), price);

        // Peak tracking
        if (order.getPeakProfit() == null || pnl.compareTo(order.getPeakProfit()) > 0) {
            order.setPeakProfit(pnl);
        }
        if (order.getPeakLoss() == null || pnl.compareTo(order.getPeakLoss()) < 0) {
            order.setPeakLoss(pnl);
        }

        order.setLastMonitoredPrice(price);
        order.setLastMonitoredAt(asOf);

        log.debug("PositionService: orderId={} dir={} entry={} asOf={} price={} pnl={} target={} stopLoss={}",
                order.getId(), order.getEntryDirection(), order.getEntryPrice(), asOf, price, pnl,
                order.getTargetAtEntry(), order.getStopLossAtEntry());

        // Threshold check using values snapshotted at entry — not the live config.
        String hit = thresholdBreach(order, pnl);
        if (hit != null) {
            log.info("PositionService: orderId={} hit {} (pnl={}, threshold target={} stopLoss={}). Closing at {}.",
                    order.getId(), hit, pnl, order.getTargetAtEntry(), order.getStopLossAtEntry(), asOf);
            // Save peak/last-monitored before closeManually loads the row again.
            tradeOrderRepository.save(order);
            orderService.closeManually(order.getId(), price, asOf, hit);
            return;
        }

        tradeOrderRepository.save(order);
    }

    /**
     * Returns the breached threshold name ({@code TARGET} or {@code STOP_LOSS})
     * or {@code null} if neither is breached or neither is configured.
     *
     * <p>Reads {@code targetAtEntry} / {@code stopLossAtEntry} from the order
     * itself — the values are snapshotted at entry by {@link OrderService}.
     * {@code stopLossAtEntry} is stored as a positive number, so the breach
     * check negates it: {@code pnl <= -stopLoss}.
     */
    private String thresholdBreach(TradeOrder order, BigDecimal pnl) {
        BigDecimal target   = order.getTargetAtEntry();
        BigDecimal stopLoss = order.getStopLossAtEntry();

        if (target != null && pnl.compareTo(target) >= 0) {
            return "TARGET";
        }
        if (stopLoss != null && pnl.compareTo(stopLoss.negate()) <= 0) {
            return "STOP_LOSS";
        }
        return null;
    }

    /** Per-share P&L given entry direction. SELL entry profits when price drops. */
    private BigDecimal perShareProfit(String entryDirection, BigDecimal entryPrice, BigDecimal currentPrice) {
        if (entryPrice == null || currentPrice == null) return BigDecimal.ZERO;
        if ("SELL".equalsIgnoreCase(entryDirection)) {
            return entryPrice.subtract(currentPrice);
        }
        return currentPrice.subtract(entryPrice);
    }
}
