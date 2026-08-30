package com.moneymaker.journal.contributors;

import com.moneymaker.entity.MarketData;
import com.moneymaker.journal.FeatureContributor;
import com.moneymaker.journal.ObservationContext;
import com.moneymaker.structure.MarketStructureAnalyzer;
import com.moneymaker.structure.MarketStructureAnalyzer.StructureEvent;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Market-structure state (CHoCH / BOS) for both the option leg and the index, as
 * it stood at the observed moment.
 *
 * <h3>Only confirmed breaks count</h3>
 * A swing is knowable only {@code fractalN} bars after it prints, so this reads
 * the most recent event whose {@code confirmableAt} is at or before
 * {@code observedAt}. Taking the latest event by {@code occurredAt} instead would
 * report a level the strategy could not yet have seen — the same class of
 * look-ahead that inflated this codebase's results by 640 points per share before
 * the settled-bar rule landed.
 *
 * <h3>WITH / AGAINST, not bullish / bearish</h3>
 * A bullish CHoCH means opposite things to a short call and a short put, so the
 * recorded fact is the relationship to the position. That is what makes structure
 * comparable across legs and across strategies.
 */
@Component
@RequiredArgsConstructor
public class StructureContributor implements FeatureContributor {

    private final MarketStructureAnalyzer analyzer;

    /**
     * Memo of {@code analyze(series)} keyed on the series instance.
     *
     * <p>Every leg evaluated in a tick is handed the <em>same</em> underlying
     * list object - {@code SharedData} holds one per (symbol, interval) - so
     * without this the ~2000-bar index series is re-analysed once per candidate,
     * and that term dominates journalling cost across a ~138k-row run.
     *
     * <p>Keyed on identity plus size and last timestamp: a fresh slice is a new
     * object and misses, and a list that somehow grew in place would miss too.
     * Bounded and cleared wholesale, because entries are only ever useful within
     * the tick that created them.
     */
    private final Map<String, List<StructureEvent>> memo = new ConcurrentHashMap<>();

    private static final int MEMO_MAX = 512;

    @Override
    public String name() {
        return "structure";
    }

    /** Analyse once per distinct series instance. */
    private List<StructureEvent> analyzed(List<MarketData> candles) {
        MarketData last = candles.get(candles.size() - 1);
        String key = System.identityHashCode(candles) + ":" + candles.size()
                + ":" + (last == null ? "?" : String.valueOf(last.getTimestamp()));
        List<StructureEvent> hit = memo.get(key);
        if (hit != null) {
            return hit;
        }
        if (memo.size() >= MEMO_MAX) {
            memo.clear();
        }
        List<StructureEvent> computed = analyzer.analyze(candles);
        memo.put(key, computed);
        return computed;
    }

    @Override
    public Map<String, Object> contribute(ObservationContext ctx) {
        Map<String, Object> f = new LinkedHashMap<>();
        if (ctx == null || ctx.observedAt() == null) {
            return f;
        }
        addFor(f, "option", ctx.optionCandles(), MarketStructureAnalyzer.SERIES_OPTION, ctx);
        addFor(f, "spot", ctx.underlyingCandles(), MarketStructureAnalyzer.SERIES_UNDERLYING, ctx);
        return f;
    }

    private void addFor(Map<String, Object> f,
                        String prefix,
                        List<MarketData> candles,
                        String series,
                        ObservationContext ctx) {
        if (candles == null || candles.isEmpty()) {
            return;
        }
        List<StructureEvent> events = analyzed(candles);
        if (events.isEmpty()) {
            return;
        }

        StructureEvent latest = null;
        StructureEvent latestChoch = null;
        for (StructureEvent e : events) {
            if (!e.isConfirmedBy(ctx.observedAt())) {
                continue;   // not knowable yet at this moment
            }
            latest = e;
            if (e.type() == MarketStructureAnalyzer.EventType.CHOCH) {
                latestChoch = e;
            }
        }
        if (latest == null) {
            return;
        }

        f.put(prefix + "_structure", latest.structureAfter().name());
        f.put(prefix + "_last_break_type", latest.type().name());
        f.put(prefix + "_last_break_level", latest.level());
        f.put(prefix + "_last_break_direction",
                analyzer.directionFor(series, latest.bias(), ctx.optionType(), ctx.entryIsSell()));
        f.put(prefix + "_bars_since_break", minutesBetween(latest.confirmableAt(), ctx.observedAt()));

        if (latestChoch != null) {
            f.put(prefix + "_last_choch_direction",
                    analyzer.directionFor(series, latestChoch.bias(), ctx.optionType(), ctx.entryIsSell()));
            f.put(prefix + "_minutes_since_choch",
                    minutesBetween(latestChoch.confirmableAt(), ctx.observedAt()));
            // Lag between the swing printing and it becoming actionable. Recorded
            // so the cost of confirmation is measurable rather than assumed.
            f.put(prefix + "_choch_confirm_lag_min",
                    minutesBetween(latestChoch.occurredAt(), latestChoch.confirmableAt()));
        }
    }

    private Long minutesBetween(LocalDateTime from, LocalDateTime to) {
        if (from == null || to == null) {
            return null;
        }
        return Duration.between(from, to).toMinutes();
    }
}
