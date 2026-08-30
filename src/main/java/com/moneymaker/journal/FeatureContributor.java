package com.moneymaker.journal;

import java.util.Map;

/**
 * Contributes named features describing one observed leg at one moment.
 *
 * <h3>Why this exists</h3>
 * The set of things worth recording about a decision is not settled and never
 * will be — today SMA state and market structure, tomorrow Supertrend, MACD,
 * OI-delta, IV, whatever the next question needs. Without an SPI, each addition
 * means editing every place an observation is taken, and the codebase already
 * shows what that costs: the strike-key format is parsed in four separate places
 * and every change has to find all four.
 *
 * <p>So features are contributed, not hardcoded. Spring injects every
 * implementation as a {@code List<FeatureContributor>} — the same auto-discovery
 * pattern {@code OrderPlacementFactory} and {@code PositionMonitorFactory}
 * already use for broker adapters. <b>Adding a new recorded feature is a new
 * bean and nothing else</b>: no call-site edit, no strategy edit, no migration,
 * because the output lands in the journal's {@code features} JSON.
 *
 * <h3>Contract</h3>
 * <ul>
 *   <li><b>Pure observation.</b> An implementation must not mutate the context,
 *       the candles, or any shared state. It is called on the trading hot path
 *       and must never be able to change a decision.</li>
 *   <li><b>Never throws.</b> Return an empty map when the inputs are
 *       insufficient — a missing feature is a gap in analysis, a thrown
 *       exception is a lost trade. The recorder guards this too, but do not
 *       rely on it.</li>
 *   <li><b>Only settled data.</b> Anything derived from a bar that has not
 *       closed, or from a swing not yet confirmed, must be reported at the point
 *       it became knowable — see {@code MarketStructureAnalyzer}. Features that
 *       silently peek ahead make every conclusion drawn from them wrong.</li>
 *   <li><b>Stable names.</b> Feature keys become column headers in analysis.
 *       Renaming one orphans historical rows, so treat a name as published.</li>
 * </ul>
 *
 * <p>Keys should be namespaced by concern and unit, e.g.
 * {@code sma50_distance_atr}, {@code oi_change_pct}, {@code structure_state}.
 */
public interface FeatureContributor {

    /** Short stable name for logs and for disabling a contributor. */
    String name();

    /**
     * Features for this observation, or an empty map when the context does not
     * carry what this contributor needs. Never null, never throws.
     */
    Map<String, Object> contribute(ObservationContext context);
}
