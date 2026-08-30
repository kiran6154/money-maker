package com.moneymaker.journal;

import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.structure.MarketStructureAnalyzer;
import com.moneymaker.structure.MarketStructureAnalyzer.StructureEvent;
import com.moneymaker.structure.StructureEventCache;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The during-position half of the journal: a {@code MONITOR} row per monitored
 * open trade per tick, and an {@code EVENT} row for each structure break that
 * became knowable while the trade was running.
 *
 * <h3>The question this exists to answer</h3>
 * {@code ENTRY} and {@code EXIT} record structure at the two ends of a trade and
 * nothing in between, so the ledger can say a trade gave back 90 points but not
 * whether anything warned first. On a ledger where every stop-loss overshot its
 * stop and 17 trades gave back an average of +13.81 before closing at −77.19,
 * <i>did an AGAINST CHoCH precede the adverse move, and with how many bars of
 * warning?</i> is the question worth answering — and it needs the timeline, not
 * the endpoints.
 *
 * <h3>Cadence: every evaluated tick, no sampling</h3>
 * One MONITOR row per open trade per tick the monitor actually evaluated. No
 * thinning, because any interval or "only when something changed" filter is a
 * behaviour parameter with no {@code TradeConfig} field behind it, and inventing
 * one in code is precisely what CLAUDE.md invariant 9 forbids. Ticks the monitor
 * skipped — no quote, or the entry-candle guard — produce no row: their absence
 * is the record that the monitor had nothing to act on. Volume is bounded by
 * open trades rather than by legs (a few rows per tick against the ~24 CANDIDATE
 * rows the same tick already writes), so this is a rounding error on journal
 * cost.
 *
 * <h3>Events are gated on {@code confirmableAt}, twice</h3>
 * A swing is not knowable when it prints — only once {@code fractalN} further
 * bars have closed past it. So an event is journalled only when
 * <ol>
 *   <li>{@code confirmableAt <= observedAt} — the confirming bar has settled, so
 *       the break was knowable at the tick that records it. Recording at
 *       {@code occurredAt} instead would re-introduce the look-ahead that cost
 *       this codebase a 640-point swing in apparent edge; and</li>
 *   <li>{@code confirmableAt >= entryTime} — it became knowable during the
 *       position. A break confirmed before entry is already summarised in the
 *       ENTRY row's structure features; re-emitting it as a during-position
 *       warning would be a false one.</li>
 * </ol>
 * Note the second gate is on {@code confirmableAt}, not {@code occurredAt}: a
 * bar that broke a level just before entry but was confirmed after it is new
 * information arriving during the trade, which is exactly what this is for.
 *
 * <h3>Never influences the monitor</h3>
 * Called after the tick's decision is made, with that decision passed in as a
 * recorded fact. It reads the order and the cached series and writes rows;
 * nothing here can change an exit. Every entry point swallows its own failures —
 * a journal that cannot write is a gap in analysis, an exception escaping it
 * would be a lost trade.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PositionJournal {

    /** Decision recorded on a tick that breached nothing. */
    static final String HOLD = "HOLD";

    private final JournalRecorder journal;
    private final ObservationContextFactory observations;
    private final StructureEventCache structureEvents;
    private final MarketStructureAnalyzer analyzer;

    /**
     * Structure breaks already journalled per open trade, so a break confirmed
     * at 10:15 is one EVENT row and not one per tick for the rest of the trade.
     *
     * <p>Bounded by {@link #retainOpen(Collection)} rather than by eviction: the
     * position monitor knows exactly which trades are still open each tick, so
     * the state for a closed one is dropped on the next tick with no guessing.
     */
    private final Map<Long, Set<String>> emitted = new ConcurrentHashMap<>();

    /**
     * Drops per-trade event state for trades that are no longer open. Called at
     * the top of a monitor pass with the ids it is about to walk.
     */
    public void retainOpen(Collection<Long> openOrderIds) {
        try {
            if (openOrderIds == null || openOrderIds.isEmpty()) {
                emitted.clear();
                return;
            }
            emitted.keySet().retainAll(openOrderIds);
        } catch (Exception ex) {
            log.debug("[journal] retainOpen failed — ignored: {}", ex.toString());
        }
    }

    /**
     * Records one monitor tick for one open trade.
     *
     * @param observedAt the quote's as-of time — the candle time in backtest, so
     *                   a replay journals the simulated moment rather than
     *                   wall-clock
     * @param pnl        unrealised per-share P&amp;L the monitor computed
     * @param decision   the threshold the monitor decided was breached
     *                   ({@code TARGET} / {@code TRAIL_SL} / {@code STOP_LOSS}),
     *                   or null for a tick that held
     */
    public void observe(TradeOrder order, LocalDateTime observedAt, BigDecimal pnl, String decision) {
        if (!journal.isEnabled() || order == null || observedAt == null) {
            return;
        }
        try {
            ObservationContext ctx = observations.forOpenPosition(order, observedAt);
            if (ctx == null) {
                return;
            }
            // selected=true: a MONITOR row always describes a leg that was
            // actually traded, the same sense ENTRY and EXIT use it in. Only
            // CANDIDATE rows carry a false there.
            journal.record(ctx, true, monitorFeatures(order, observedAt, pnl, decision));
            recordStructureEvents(ctx, order, observedAt, pnl);
        } catch (Exception ex) {
            log.debug("[journal] monitor observation failed for orderId={} — ignored: {}",
                    order.getId(), ex.toString());
        }
    }

    /** What the monitor knew and decided, which no contributor can see. */
    private Map<String, Object> monitorFeatures(TradeOrder order,
                                                LocalDateTime observedAt,
                                                BigDecimal pnl,
                                                String decision) {
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("monitor_decision", decision == null ? HOLD : decision);
        f.put("monitor_pnl", pnl);
        f.put("monitor_price", order.getLastMonitoredPrice());
        f.put("monitor_peak_profit", order.getPeakProfit());
        f.put("monitor_peak_loss", order.getPeakLoss());
        f.put("monitor_target_at_entry", order.getTargetAtEntry());
        f.put("monitor_stop_loss_at_entry", order.getStopLossAtEntry());
        f.put("monitor_trail_sl_at", order.getTrailSlAt());
        f.put("monitor_minutes_since_entry", minutesBetween(order.getEntryTime(), observedAt));
        return f;
    }

    /**
     * One EVENT row per structure break that became knowable during this trade
     * and has not been journalled for it yet.
     */
    private void recordStructureEvents(ObservationContext ctx,
                                       TradeOrder order,
                                       LocalDateTime observedAt,
                                       BigDecimal pnl) {
        if (order.getEntryTime() == null || order.getId() == null) {
            return;
        }
        Set<String> seen = emitted.computeIfAbsent(order.getId(), id -> ConcurrentHashMap.newKeySet());
        emitFrom(ctx, order, observedAt, pnl, seen,
                MarketStructureAnalyzer.SERIES_OPTION, ctx.optionCandles());
        emitFrom(ctx, order, observedAt, pnl, seen,
                MarketStructureAnalyzer.SERIES_UNDERLYING, ctx.underlyingCandles());
    }

    private void emitFrom(ObservationContext ctx,
                          TradeOrder order,
                          LocalDateTime observedAt,
                          BigDecimal pnl,
                          Set<String> seen,
                          String series,
                          List<MarketData> candles) {
        for (StructureEvent e : structureEvents.eventsFor(candles)) {
            if (!e.isConfirmedBy(observedAt)) {
                continue;                                   // not knowable yet
            }
            if (e.confirmableAt().isBefore(order.getEntryTime())) {
                continue;                                   // knowable before the trade existed
            }
            String key = series + "|" + e.type() + "|" + e.occurredAt() + "|" + e.level();
            if (!seen.add(key)) {
                continue;                                   // already journalled for this trade
            }
            journal.recordEvent(ctx,
                    e.type().name(),
                    analyzer.directionFor(series, e.bias(), ctx.optionType(), ctx.entryIsSell()),
                    e.confirmableAt(),
                    eventFeatures(e, series, order, observedAt, pnl));
        }
    }

    /**
     * <p>{@code break_series} is a feature rather than the row's {@code series}
     * column because that column is leg identity — an EVENT on the index during
     * an option trade is still a row about that option leg.
     */
    private Map<String, Object> eventFeatures(StructureEvent e,
                                              String series,
                                              TradeOrder order,
                                              LocalDateTime observedAt,
                                              BigDecimal pnl) {
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("break_series", series);
        f.put("event_occurred_at", String.valueOf(e.occurredAt()));
        // The lag between a swing printing and it becoming actionable, recorded
        // so the cost of confirmation is measurable rather than assumed.
        f.put("event_confirm_lag_min", minutesBetween(e.occurredAt(), e.confirmableAt()));
        f.put("event_level", e.level());
        f.put("event_structure_before", e.structureBefore().name());
        f.put("event_structure_after", e.structureAfter().name());
        // How much warning this break gave, and what the trade was worth when it
        // arrived — the two halves of the question the journal exists to answer.
        f.put("monitor_minutes_since_entry", minutesBetween(order.getEntryTime(), observedAt));
        f.put("monitor_pnl", pnl);
        f.put("monitor_peak_profit", order.getPeakProfit());
        return f;
    }

    private static Long minutesBetween(LocalDateTime from, LocalDateTime to) {
        if (from == null || to == null) {
            return null;
        }
        return Duration.between(from, to).toMinutes();
    }
}
