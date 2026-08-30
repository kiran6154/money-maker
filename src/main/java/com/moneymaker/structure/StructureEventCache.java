package com.moneymaker.structure;

import com.moneymaker.entity.MarketData;
import com.moneymaker.structure.MarketStructureAnalyzer.StructureEvent;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Memo of {@link MarketStructureAnalyzer#analyze(List)} keyed on the series
 * instance, shared by every reader of structure inside one tick.
 *
 * <h3>Why a shared bean rather than a field on one contributor</h3>
 * Every leg evaluated in a tick is handed the <em>same</em> underlying list
 * object — {@code SharedData} holds one series per (symbol, interval) — so
 * without a memo the ~2000-bar index series is re-analysed once per candidate,
 * and that term dominates journalling cost across a ~138k-row run.
 *
 * <p>It lives here rather than inside {@code StructureContributor} because there
 * are now two readers: the contributor, which records the structure <i>state</i>
 * on every observation, and {@code PositionJournal}, which emits an
 * {@code EVENT} row for each discrete break seen while a position is open. Both
 * must agree — an EVENT row that disagreed with the MONITOR row written at the
 * same tick would be unexplainable in analysis — and they agree by construction
 * when they read the same analysis.
 *
 * <h3>Keying</h3>
 * Identity plus size and last timestamp: a fresh slice is a new object and
 * misses, and a list that somehow grew in place would miss too. Bounded and
 * cleared wholesale, because entries are only ever useful within the tick that
 * created them.
 */
@Component
@RequiredArgsConstructor
public class StructureEventCache {

    private static final int MEMO_MAX = 512;

    private final MarketStructureAnalyzer analyzer;

    private final Map<String, List<StructureEvent>> memo = new ConcurrentHashMap<>();

    /** Structure breaks on {@code candles}, analysed once per distinct series. */
    public List<StructureEvent> eventsFor(List<MarketData> candles) {
        if (candles == null || candles.isEmpty()) {
            return List.of();
        }
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
}
