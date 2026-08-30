package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.journal.PositionJournal;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.util.TrailLadder;
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
 * {@code lastMonitoredAt}, {@code trailSlAt}). When the unrealised P&L breaches
 * the {@code targetAtEntry} or {@code stopLossAtEntry} thresholds snapshotted on
 * the row at entry — or the trailing floor this class ratchets up from
 * {@code trailLadderAtEntry} — delegates to {@code OrderService.closeManually}
 * to record the exit.
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

    /**
     * The during-position half of the observation journal. Wired here rather
     * than into {@code PositionScheduler} so a backtest replays it identically
     * to live (CLAUDE.md invariant 8), and called only after each tick's
     * decision is made — it records what happened, it never takes part in it.
     */
    private final PositionJournal positionJournal;

    public PositionService(TradeOrderRepository tradeOrderRepository,
                           PositionMonitorFactory monitorFactory,
                           OrderService orderService,
                           PositionJournal positionJournal) {
        this.tradeOrderRepository = Objects.requireNonNull(tradeOrderRepository, "tradeOrderRepository must not be null");
        this.monitorFactory = Objects.requireNonNull(monitorFactory, "monitorFactory must not be null");
        this.orderService = Objects.requireNonNull(orderService, "orderService must not be null");
        this.positionJournal = Objects.requireNonNull(positionJournal, "positionJournal must not be null");
    }

    public void processPositions() {
        List<TradeOrder> open = tradeOrderRepository.findByStatus(STATUS_OPEN);
        if (open.isEmpty()) return;

        PositionMonitorService monitor = monitorFactory.active();

        // Drop journal state for trades that have since closed. This is the one
        // place that knows the current open set, so it is the cheapest correct
        // moment to bound it.
        positionJournal.retainOpen(open.stream().map(TradeOrder::getId).toList());

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

        // Resting-order stop model (S4 decision, 2026-08-31): a floor — the
        // trailing rung or the fixed stop — is an SL order resting at the
        // broker, so it fills the moment the bar touches it, at the floor
        // price, regardless of where the bar closes. Detection therefore uses
        // the bar's ADVERSE extreme when the monitor supplies one (backtest
        // candles carry high/low; live LTP quotes leave them null and degrade
        // to close-only, the pre-existing behaviour).
        //
        // Convention: adverse-first within a bar. The floor tested is the one
        // armed by PREVIOUS ticks; a rung this bar's own excursion earns arms
        // only after the breach check, so it cannot exit on the bar that
        // earned it. Bar internals are unordered, and this is the conservative
        // reading — it can understate the ladder, never flatter it.
        BigDecimal adversePnl = extremePnl(order, quote, pnl, true);
        String hit = thresholdBreach(order, pnl, adversePnl);

        // Peak tracking uses the bar's favorable extreme for the same reason —
        // "price makes new values" intra-bar is what arms a rung in live.
        BigDecimal favorablePnl = extremePnl(order, quote, pnl, false);
        if (order.getPeakProfit() == null || favorablePnl.compareTo(order.getPeakProfit()) > 0) {
            order.setPeakProfit(favorablePnl);
        }
        if (order.getPeakLoss() == null || adversePnl.compareTo(order.getPeakLoss()) < 0) {
            order.setPeakLoss(adversePnl);
        }

        order.setLastMonitoredPrice(price);
        order.setLastMonitoredAt(asOf);

        // Arm rungs AFTER the breach check (adverse-first convention above).
        // A rung locks strictly below its own trigger (TrailLadder.parse
        // enforces it), so the newly armed floor is below the peak that armed
        // it and waits for a later bar.
        applyTrail(order);

        log.debug("[position] orderId={} {} {}{} entry={}@{} cur={}@{} pl={} maxPL={} maxLoss={} target={} stopLoss={} trailSl={} → {}",
                order.getId(), order.getInstrumentName(), order.getOptionStrike(), order.getOptionType(),
                order.getEntryPrice(), order.getEntryTime(),
                price, asOf, pnl, order.getPeakProfit(), order.getPeakLoss(),
                order.getTargetAtEntry(), order.getStopLossAtEntry(), order.getTrailSlAt(),
                hit != null ? hit : "hold");

        // MONITOR / EVENT rows for this tick. Deliberately after every decision
        // above and before none of them: `hit` is already settled and is passed
        // in as a recorded fact, so journalling cannot reorder or alter an exit.
        // Guarded even though PositionJournal swallows its own failures — a
        // broken journal must never cost a stop-loss.
        try {
            positionJournal.observe(order, asOf, pnl, hit);
        } catch (Exception ex) {
            log.debug("[position] journal observation failed for orderId={} — ignored: {}",
                    order.getId(), ex.toString());
        }

        if (hit != null) {
            // A floor exit fills AT the floor (the resting order's trigger),
            // not at the bar's close — that is the whole point of the model.
            // TARGET keeps the close-price fill it always had.
            BigDecimal exitPrice = price;
            if ("TRAIL_SL".equals(hit)) {
                exitPrice = priceAtPnl(order, order.getTrailSlAt());
            } else if ("STOP_LOSS".equals(hit)) {
                exitPrice = priceAtPnl(order, order.getStopLossAtEntry().negate());
            }
            log.info("[position] CLOSE orderId={} reason={} pnl={} adversePnl={} exitPrice={} (target={} stopLoss={} trailSl={} peak={}) at {}",
                    order.getId(), hit, pnl, adversePnl, exitPrice, order.getTargetAtEntry(), order.getStopLossAtEntry(),
                    order.getTrailSlAt(), order.getPeakProfit(), asOf);
            // Save peak/last-monitored before closeManually loads the row again.
            tradeOrderRepository.save(order);
            orderService.closeManually(order.getId(), exitPrice, asOf, hit);
            return;
        }

        tradeOrderRepository.save(order);
    }

    /**
     * Raises the trailing floor to whatever rung the trade's <b>peak</b> profit has
     * earned, and never lowers it.
     *
     * <p>Peak, not current P&L, is what makes this a ratchet: a trade that touches
     * +50 keeps its +25 floor even if price falls back to +30, so the excursion it
     * actually achieved is converted into a floor instead of being given back. That
     * is the whole point of the ladder — see changeset 036.</p>
     *
     * <p>The ladder is read from {@code trailLadderAtEntry} on the row, not from
     * the live config, for the same reason the fixed bracket is: editing a ladder
     * mid-session must not re-floor trades that are already open. It was
     * canonicalised and validated at entry, so a parse failure here means the
     * column was corrupted after the fact — log it and leave the trade on its fixed
     * stop rather than letting the exception abort the tick for every other order.</p>
     */
    private void applyTrail(TradeOrder order) {
        String ladder = order.getTrailLadderAtEntry();
        if (ladder == null || ladder.isBlank()) return;

        BigDecimal lock;
        try {
            lock = TrailLadder.lockFor(ladder, order.getPeakProfit());
        } catch (IllegalArgumentException ex) {
            log.error("[position] orderId={} has an unusable trail_ladder_at_entry \"{}\" — "
                            + "trailing disabled for this trade, fixed stop-loss still applies: {}",
                    order.getId(), ladder, ex.getMessage());
            return;
        }
        if (lock == null) return; // no rung reached yet

        BigDecimal current = order.getTrailSlAt();
        if (current == null || lock.compareTo(current) > 0) {
            log.info("[position] TRAIL orderId={} peak={} → stop-loss floor {} (was {}) ladder={}",
                    order.getId(), order.getPeakProfit(), lock, current, ladder);
            order.setTrailSlAt(lock);
        }
    }

    /**
     * Returns the breached threshold name ({@code TARGET}, {@code TRAIL_SL} or
     * {@code STOP_LOSS}) or {@code null} if none is breached or none is configured.
     *
     * <p>Reads {@code targetAtEntry} / {@code stopLossAtEntry} / {@code trailSlAt}
     * from the order itself — the first two are snapshotted at entry by
     * {@link OrderService}, the third is maintained by {@link #applyTrail}.
     * {@code stopLossAtEntry} is stored as a positive number, so the breach check
     * negates it: {@code adversePnl <= -stopLoss}.</p>
     *
     * <p><b>Two different P&Ls on purpose</b> (resting-order model, S4 decision):
     * the floors are tested against {@code adversePnl} — the bar's worst moment —
     * because an SL order resting at the broker fills on a touch; {@code TARGET}
     * is tested against the close {@code pnl}, unchanged from before, because no
     * resting order exists for it (see the entry for the follow-up question).
     * TARGET is evaluated first, as before — on a bar that spans both, the
     * close-tested target keeps priority exactly as it did when everything was
     * close-tested.</p>
     *
     * <p>The two stops are not checked in sequence but collapsed into the
     * <b>higher</b> of the two floors, labelled by whichever put it there. Order of
     * evaluation would otherwise decide the exit reason on a tick where both
     * breach — which happens whenever a candle gaps straight through both — and
     * the label is the only thing that tells a trailed exit apart from a stopped
     * one afterwards.</p>
     */
    private String thresholdBreach(TradeOrder order, BigDecimal pnl, BigDecimal adversePnl) {
        BigDecimal target   = order.getTargetAtEntry();
        BigDecimal stopLoss = order.getStopLossAtEntry();
        BigDecimal trailSl  = order.getTrailSlAt();

        if (target != null && pnl.compareTo(target) >= 0) {
            return "TARGET";
        }

        BigDecimal fixedFloor = stopLoss != null ? stopLoss.negate() : null;
        // Strictly above: a trail sitting exactly on the fixed stop moved nothing,
        // so the exit is the one that would have happened without the ladder.
        boolean trailIsTighter = trailSl != null
                && (fixedFloor == null || trailSl.compareTo(fixedFloor) > 0);

        if (trailIsTighter) {
            return adversePnl.compareTo(trailSl) <= 0 ? "TRAIL_SL" : null;
        }
        if (fixedFloor != null && adversePnl.compareTo(fixedFloor) <= 0) {
            return "STOP_LOSS";
        }
        return null;
    }

    /**
     * The per-share P&L at the bar's adverse ({@code true}) or favorable
     * ({@code false}) extreme, degrading to the close-based {@code pnl} when the
     * quote carries no bar (live LTP) or the extreme is missing. For a SELL
     * entry the adverse extreme is the bar HIGH (price rose against the short);
     * for a BUY it is the LOW — and vice versa for favorable.
     */
    private BigDecimal extremePnl(TradeOrder order, Quote quote, BigDecimal pnl, boolean adverse) {
        boolean sell = "SELL".equalsIgnoreCase(order.getEntryDirection());
        BigDecimal extreme = (adverse == sell) ? quote.high() : quote.low();
        if (extreme == null) return pnl;
        BigDecimal atExtreme = perShareProfit(order.getEntryDirection(), order.getEntryPrice(), extreme);
        if (adverse) {
            return atExtreme.compareTo(pnl) < 0 ? atExtreme : pnl;
        }
        return atExtreme.compareTo(pnl) > 0 ? atExtreme : pnl;
    }

    /**
     * The price at which this order's P&L equals {@code targetPnl} — where a
     * resting SL order at that floor fills. SELL: {@code entry − pnl};
     * BUY: {@code entry + pnl}.
     */
    private BigDecimal priceAtPnl(TradeOrder order, BigDecimal targetPnl) {
        if ("SELL".equalsIgnoreCase(order.getEntryDirection())) {
            return order.getEntryPrice().subtract(targetPnl);
        }
        return order.getEntryPrice().add(targetPnl);
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
