package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.indicator.series.SpotFeatures;
import com.moneymaker.market.instrument.OffsetStrikeSelector;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.market.instrument.SyntheticUnderlyingContract;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.pressure.PressureScore;
import com.moneymaker.strategy.pressure.SpotFeatureCache;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * <b>Pressure</b> — a one-position-at-a-time intraday continuation engine on
 * NIFTY 5-minute spot.
 *
 * <p>Full specification, worked example and the deviations from it:
 * {@code docs/PRESSURE_STRATEGY.md}. This javadoc covers what the class does and
 * why it is shaped differently from every other strategy here.</p>
 *
 * <h3>What it does</h3>
 * Each tick it scores the latest settled <b>spot</b> bar on two integer pressure
 * scores (see {@link PressureScore}) and, when one side reaches 3, emits a single
 * entry signal on the leg its config trades. Continuation, not fade: a
 * down-pressured bar sells the CE (or buys the PE), an up-pressured bar sells the
 * PE (or buys the CE).
 *
 * <h3>Three ways it differs from strategies 1-4, all deliberate</h3>
 * <ol>
 *   <li><b>It reads spot, not premium.</b> {@link AbstractSmaCrossStrategy} scans
 *       {@code SharedData.strikeMarketDataByInstrumentAndInterval} and computes
 *       its SMA on the option's own premium series. Every Pressure input — RSI,
 *       VWAP, Supertrend, opening range, ADX — is defined on the underlying, so
 *       this class reads {@code SharedData.marketDataByInstrumentAndInterval}
 *       instead and touches the strike cache only to price the leg it is about
 *       to trade. Extending the SMA base would have meant inheriting a scan loop
 *       whose every step is wrong for this strategy.</li>
 *   <li><b>It emits entries only.</b> There is no exit signal at all. Every exit
 *       — target, stop, trail, time stop, 15:15 flatten — is a position-level
 *       rule that {@code PositionService} applies off the bracket snapshotted at
 *       entry. So there is no {@code isMarketCloseTime} rule here and no
 *       opposite-direction signal that {@code OrderService} would read as a
 *       close.</li>
 *   <li><b>It picks one exact strike.</b> The depth-count strike <i>set</i> and
 *       the premium-ranked scan that goes with it are replaced by
 *       {@code trade_config.strike_offset_points} resolving to a single
 *       contract. There is nothing to rank.</li>
 * </ol>
 *
 * <h3>What it does NOT do, on purpose</h3>
 * No SMA, no MACD, no extra session bans, no second wing on the same bar. The
 * score is the four terms and the one penalty, and the spec is explicit that
 * nothing else may be added. A filter that "obviously helps" belongs in
 * {@code docs/STRATEGY_ANALYSIS_TODO.md} as a measured proposal, not here — see
 * Rule 0(c).
 *
 * <h3>Config prerequisites</h3>
 * A config running this strategy must set {@code strike_offset_points} (or
 * {@code underlying_leg} for the spot baseline book), {@code book_id}, and the
 * clock columns from changeset 042. Without them the config still runs, but as
 * an unbounded-clock, depth-count config — which is not this strategy. The
 * generator ({@code PressureConfigGenerator}) is the supported way to create
 * them.
 */
@Component
public class Strategy5 extends AbstractSmaCrossStrategy {

    public static final int ID = 5;

    /**
     * Strike grid used when a config leaves {@code strike_step_points} unset.
     * 50 is the real grid of the imported NIFTY chain; {@code instrument.strike_points}
     * says 100 and is deliberately not consulted here - see changeset 042.
     */
    private static final int DEFAULT_STRIKE_STEP = 50;

    /**
     * Bound to this class rather than inherited, for the same reason the base
     * class binds its own: a {@code [pressure]} line must name the strategy that
     * emitted it.
     */
    private final Logger pressureLog = LoggerFactory.getLogger(Strategy5.class);

    private final SpotFeatureCache spotFeatures;

    public Strategy5(OptionInstrumentResolver instrumentResolver, SpotFeatureCache spotFeatures) {
        super(instrumentResolver);
        this.spotFeatures = spotFeatures;
    }

    @Override
    public int getId() {
        return ID;
    }

    /**
     * <b>Fully replaces</b> the inherited SMA-cross scan. Nothing from
     * {@link AbstractSmaCrossStrategy#execute} runs for this strategy.
     *
     * <p>The class still extends that base only to inherit its small helpers
     * ({@code resolveOptionType}, {@code depthOf}, {@code keyMatches}, the price
     * band) and to keep one registration shape across all five strategies. If a
     * future change makes the base's {@code execute} do something this strategy
     * needs, it must be lifted into a shared helper rather than called via
     * {@code super} — the two scan models are not compatible.</p>
     */
    @Override
    public void execute(TradeConfigCombinedDTO config, LocalDateTime asOf) {
        if (config == null || config.getTradeConfig() == null || asOf == null) return;
        TradeConfig tc = config.getTradeConfig();
        Integer tradeConfigId = tc.getId();

        // ---- 1. the spot series this config's underlying trades on ----------
        String underlying = instrumentResolver.underlyingSymbol(config);
        if (underlying == null) {
            pressureLog.warn("[pressure] tradeConfigId={} — no underlying symbol resolved", tradeConfigId);
            return;
        }
        String interval = intervalOf(config);
        if (interval == null) {
            pressureLog.warn("[pressure] tradeConfigId={} — no timeframe configured", tradeConfigId);
            return;
        }
        List<MarketData> spot = SharedData.marketDataByInstrumentAndInterval.get(underlying + "|" + interval);
        if (spot == null || spot.isEmpty()) {
            pressureLog.debug("[pressure] tradeConfigId={} — no spot series cached for {}|{}",
                    tradeConfigId, underlying, interval);
            return;
        }

        // ---- 2. score the latest settled spot bar ---------------------------
        SpotFeatures features = spotFeatures.get(config.getInstrument(), asOf.toLocalDate(), spot);
        if (features == null) return;
        SpotFeatures.Snapshot snap = features.at(asOf);
        if (snap == null) return;

        // A settled bar from an earlier session is not a decision bar - the same
        // guard the SMA base applies, and for the same reason: before the day's
        // first bucket completes, "latest" is still yesterday's close, and acting
        // on it stamps a signal with yesterday's timestamp and price.
        if (!snap.timestamp().toLocalDate().equals(asOf.toLocalDate())) {
            return;
        }

        PressureScore.Decision decision = PressureScore.decide(snap);
        if (pressureLog.isDebugEnabled()) {
            pressureLog.debug("[pressure] tradeConfigId={} ts={} close={} rsi={} anchor={} st={} adx={} or=[{}, {}]{} -> {} ({})",
                    tradeConfigId, snap.timestamp(), snap.close(),
                    fmt(snap.rsi()), fmt(snap.anchorPrice()), snap.supertrendDirection(), fmt(snap.adx()),
                    fmt(snap.openingRangeLow()), fmt(snap.openingRangeHigh()),
                    snap.openingRangeComplete() ? "" : " (OR incomplete)",
                    decision.direction(), decision.reason());
        }
        if (decision.bothSides()) {
            // Rare by construction and worth seeing when it happens - a bar that
            // is simultaneously three points down- and up-pressured is a bar the
            // model does not understand, and a rising count would be a signal
            // that one of the five inputs is misbehaving.
            pressureLog.info("[pressure] tradeConfigId={} ts={} BOTH sides fired - skipped ({})",
                    tradeConfigId, snap.timestamp(), decision.reason());
            return;
        }
        if (decision.direction() == PressureScore.Direction.NONE) return;

        // ---- 3. does this config trade the side that fired? -----------------
        // A book is two configs - one CE, one PE - and each only trades its own
        // leg. The cross-config "one position at a time" cap lives in
        // OrderService (trade_config.book_id); this is just the side match.
        TradeAction action = actionFor(config, decision.direction());
        if (action == null) return;

        // ---- 4. price the leg and emit --------------------------------------
        String strikeKey = resolveTradableKey(config, underlying, interval, asOf, snap.close());
        if (strikeKey == null) {
            pressureLog.debug("[pressure] tradeConfigId={} ts={} {} fired but no tradable leg cached",
                    tradeConfigId, snap.timestamp(), decision.direction());
            return;
        }
        List<MarketData> legSeries = SharedData.strikeMarketDataByInstrumentAndInterval.get(strikeKey);
        MarketData leg = legSeries.get(legSeries.size() - 1);
        BigDecimal premium = leg.getClose();
        if (premium == null) return;

        pressureLog.info("[pressure] SIGNAL {} {} tradeConfigId={} book={} spotTs={} spot={} premium={} ({})",
                action, strikeKey, tradeConfigId, tc.getBookId(),
                snap.timestamp(), snap.close(), premium, decision.reason());

        // Signal time is the SPOT bar's timestamp, not the leg's. The two are the
        // same in a healthy replay, but if a leg's series is one bar stale the
        // decision was still taken on the spot bar and the ledger must say so -
        // otherwise entry_time and the reason string disagree about which bar
        // fired, and the exact-duplicate guard in OrderService keys on the wrong
        // moment.
        SharedData.tradeSignals.add(new TradeSignal(
                strikeKey, action, tradeConfigId, getId(),
                snap.timestamp(), null, interval, premium));
    }

    /**
     * The order direction this config takes when {@code direction} fires, or
     * {@code null} when this config's leg is not the one that side trades.
     *
     * <pre>
     *   P_down &gt;= 3   SELL CE   or   BUY PE
     *   P_up   &gt;= 3   SELL PE   or   BUY CE
     * </pre>
     *
     * <p>Derived from the config's own {@code trading_side} and
     * {@code transaction_type} rather than from a table here, so a book is
     * described entirely by its config rows and adding the BUY books needed no
     * code change.</p>
     */
    private TradeAction actionFor(TradeConfigCombinedDTO config, PressureScore.Direction direction) {
        TradeConfig tc = config.getTradeConfig();

        // The spot baseline book has no CE/PE leg, so its two configs split by
        // DIRECTION instead: the SELL config takes down-pressure (short the
        // index), the BUY config takes up-pressure (long it). That mirrors the
        // option books, where each config also handles exactly one side of the
        // signal.
        //
        // Each must therefore emit ONLY its own direction. Emitting both from
        // both would not open a wrong trade - OrderService discards a signal
        // whose direction contradicts the config's transaction_type - but it
        // would put a rejected signal on the queue for every bar the book fires,
        // and "silently discarded downstream" is a bad thing to rely on.
        if (tc.tradesUnderlyingLeg()) {
            boolean wantsLong = "BUY".equalsIgnoreCase(tc.getTransactionType());
            boolean isUp = direction == PressureScore.Direction.UP;
            if (wantsLong != isUp) return null;
            return wantsLong ? TradeAction.BUY : TradeAction.SELL;
        }

        String side = resolveOptionType(config);
        if (side == null) return null;
        boolean call = "CE".equalsIgnoreCase(side);
        boolean buy = "BUY".equalsIgnoreCase(tc.getTransactionType());

        boolean legTradesThisSide = buy
                // BUY CE on up-pressure, BUY PE on down-pressure
                ? (call == (direction == PressureScore.Direction.UP))
                // SELL CE on down-pressure, SELL PE on up-pressure
                : (call == (direction == PressureScore.Direction.DOWN));

        if (!legTradesThisSide) return null;
        return buy ? TradeAction.BUY : TradeAction.SELL;
    }

    /**
     * The cache key of the single leg this config trades, or {@code null} when
     * nothing usable is cached for this tick.
     *
     * <p>Walks the strike cache for keys matching this config's underlying,
     * interval and side, and takes the one written by <i>this</i> tick. In offset
     * mode {@code AnalysisScheduler} caches exactly one strike per config, so
     * there is nothing to choose between — unlike the SMA strategies, which rank
     * a whole set by premium.</p>
     */
    private String resolveTradableKey(TradeConfigCombinedDTO config, String underlying,
                                      String interval, LocalDateTime asOf, double spotClose) {
        TradeConfig tc = config.getTradeConfig();

        // The spot baseline book has exactly one pseudo-contract, so a prefix
        // match is unambiguous.
        if (tc.tradesUnderlyingLeg()) {
            return firstFreshKey(underlying + "|" + interval + "|"
                    + SyntheticUnderlyingContract.SIDE + "|", asOf);
        }

        String side = resolveOptionType(config);
        if (side == null) return null;

        // Match this config's OWN strike, never "the first key with the right
        // side".
        //
        // Every Pressure config writes into the one shared strike cache, and
        // because they all leave itm_depth / otm_depth null their keys differ
        // ONLY in the strike and contract segments. A prefix scan on
        // underlying|interval|side therefore matched whichever entry
        // ConcurrentHashMap happened to iterate first - so SELL_ITM300,
        // SELL_ITM200 and SELL_ATM all traded the same leg, and which leg it was
        // varied between runs. Three books that are supposed to be the
        // comparison silently collapsed into one.
        //
        // Recomputing the strike here from the same spot close and the same
        // selector AnalysisScheduler used makes the lookup exact, and walking
        // the candidate list in preference order reproduces the spec's
        // "nearest available +/-50 then +/-100" fallback against whatever the
        // fetch actually managed to cache.
        Integer offset = tc.getStrikeOffsetPoints();
        if (offset == null) {
            // Not an offset config. Nothing sensible to pick - a depth-count
            // config belongs to the SMA strategies, not to this one.
            log.warn("[pressure] tradeConfigId={} has no strike_offset_points — cannot resolve a leg",
                    tc.getId());
            return null;
        }
        int step = tc.getStrikeStepPoints() != null && tc.getStrikeStepPoints() > 0
                ? tc.getStrikeStepPoints()
                : DEFAULT_STRIKE_STEP;
        int atm = OffsetStrikeSelector.atm(spotClose, step);

        for (Integer strike : OffsetStrikeSelector.candidates(atm, side, offset, step)) {
            String key = firstFreshKey(underlying + "|" + interval + "|" + side + "|" + strike + "|", asOf);
            if (key != null) return key;
        }
        return null;
    }

    /**
     * The first cache key under {@code prefix} that carries a non-empty series
     * written by <i>this</i> tick, or null.
     *
     * <p>The freshness check is S8: a strike that dropped out of the fetch
     * window keeps its last cached candle indefinitely, and entering off it
     * prices the trade at a premium that stopped updating — which is how a
     * position once got opened 48 points away from the market.</p>
     */
    private String firstFreshKey(String prefix, LocalDateTime asOf) {
        for (Map.Entry<String, List<MarketData>> e
                : SharedData.strikeMarketDataByInstrumentAndInterval.entrySet()) {
            String key = e.getKey();
            if (!key.startsWith(prefix)) continue;
            List<MarketData> series = e.getValue();
            if (series == null || series.isEmpty()) continue;
            if (!asOf.equals(SharedData.strikeMarketDataTick.get(key))) continue;
            return key;
        }
        return null;
    }

    /** This config's single timeframe as a market-data interval string. */
    private String intervalOf(TradeConfigCombinedDTO config) {
        List<SmaTimeframe> tfs = config.getTimeframes();
        if (tfs == null || tfs.isEmpty()) return null;
        for (SmaTimeframe tf : tfs) {
            if (tf != null && tf.getTimePeriod() != null) {
                return tf.getTimePeriod() + "minute";
            }
        }
        return null;
    }

    private static String fmt(double v) {
        return Double.isNaN(v) ? "-" : String.format("%.2f", v);
    }

    // ------------------------------------------------------------------
    // The rule hooks below exist only because AbstractSmaCrossStrategy declares
    // them abstract-ish. This strategy never evaluates TradeRules: its decision
    // is PressureScore, and execute() above does not call RuleEngine at all.
    // Returning the fail-closed sentinel makes that explicit and guarantees that
    // if some future refactor ever routed this class through the inherited scan,
    // it would emit nothing rather than start trading on SMA crosses.
    // ------------------------------------------------------------------

    @Override
    protected com.moneymaker.strategy.rules.TradeRules sellRulesFor(Integer primarySmaPeriod) {
        return com.moneymaker.strategy.rules.TradeRules.empty();
    }

    @Override
    protected com.moneymaker.strategy.rules.TradeRules buyRulesFor(Integer primarySmaPeriod) {
        return com.moneymaker.strategy.rules.TradeRules.empty();
    }
}
