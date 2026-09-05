package com.moneymaker.strategy.pressure;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
import com.moneymaker.indicator.series.SpotFeatures;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.market.instrument.UnderlyingSymbols;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.repository.HistoricalOptionCandleRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Builds and caches one {@link SpotFeatures} per (underlying, trading date).
 *
 * <h3>Why a cache and not a computation per tick</h3>
 * The replay runs ~73 ticks per trading day and every one of them asks for the
 * same day's RSI / Supertrend / ADX / VWAP / opening range. Those are three
 * path-dependent Wilder recurrences over a multi-day warmup window; recomputing
 * them per tick is the difference between a full-year Pressure run finishing in
 * the same envelope as the existing SMA strategies and it taking an order of
 * magnitude longer. {@link SpotFeatures#at} is then a map lookup.
 *
 * <h3>Cleared per day by the same sweep that clears everything else</h3>
 * {@code BacktestAnalysisService}'s per-day {@code finally} block wipes every
 * {@code SharedData} cache so a day cannot read the previous day's state. This
 * cache is keyed by date so it cannot leak across days in the first place, but
 * {@link #clearDay} is called from the same place for the same reason: a
 * long-running replay would otherwise accumulate one entry per trading day for
 * the life of the JVM.
 *
 * <h3>The session anchor is NOT a VWAP</h3>
 * The Pressure spec calls its third score term "Session VWAP", and the reference
 * implementation behind the 1,560-ticket 2024 book <b>used no volume at all</b>
 * — it is an unweighted expanding mean of HLC typical price (confirmed by the
 * strategy's author, 2026-09-05). {@code TYPICAL_MEAN} is therefore the default
 * and is what reproduces the reference.
 *
 * <p>{@code OPTION_TAPE_VWAP} is the opt-in alternative and a genuinely
 * different indicator: it weights each bar by front-weekly option-chain volume,
 * because NIFTY itself has none (19,572 of 19,602 {@code historical_spot_candles}
 * rows for 2024 carry {@code volume = 0}). It is retained for a proposed
 * experiment, not as an improvement — switching it on changes what trades get
 * taken, so the reference book has to be re-marked before any of its figures
 * mean anything against it. See S22 in {@code docs/STRATEGY_ANALYSIS_TODO.md}.
 */
@Slf4j
@Service
public class SpotFeatureCache {

    /** Pressure spec: RSI(14) Wilder. */
    private static final int RSI_PERIOD = 14;
    /** Pressure spec: Supertrend ATR 10. */
    private static final int ATR_PERIOD = 10;
    /** Pressure spec: Supertrend multiplier 3. */
    private static final double ST_MULTIPLIER = 3d;
    /** Pressure spec: ADX(14) Wilder. */
    private static final int ADX_PERIOD = 14;

    /**
     * Exchange the imported option chain is filed under. Matches
     * {@code HistoricalOptionInstrumentResolver.OPTION_EXCHANGE}; the two must
     * agree or the volume query silently returns nothing and every bar falls
     * back to the unweighted mean.
     */
    private static final String OPTION_EXCHANGE = "NFO";

    private final MarketHoursService marketHours;
    private final OptionInstrumentResolver instrumentResolver;
    private final ObjectProvider<HistoricalOptionCandleRepository> optionCandles;

    /**
     * Opening-range window end, inclusive. Configurable because it is a
     * trading-behaviour boundary (CLAUDE.md #9) even though the spec fixes it at
     * 09:30 — the score's {@code close &lt; OR_low} term moves with it.
     */
    @Value("${app.pressure.opening-range-end:09:30}")
    private String openingRangeEndStr;

    /**
     * How the session anchor price is computed.
     *
     * <ul>
     *   <li>{@code TYPICAL_MEAN} (default) — unweighted expanding mean of
     *       {@code (H+L+C)/3}. This is the reference formula, despite the spec
     *       calling the term "VWAP".</li>
     *   <li>{@code OPTION_TAPE_VWAP} — weight each bar by front-weekly
     *       option-chain volume.</li>
     * </ul>
     *
     * <p>A property rather than a {@code TradeConfig} column, deliberately.
     * CLAUDE.md #9 governs the numbers that decide when to trade — thresholds,
     * caps, clock boundaries — and every one of those for this strategy already
     * is a column. This selects which of two <i>definitions</i> of one input is
     * used, and it must be identical across all seven comparison books or the
     * books stop being comparable. A per-config column would make that
     * invariant unenforceable. If it ever needs to vary per book, it should move
     * to {@code strategy_defaults}, alongside {@code target_mode}.</p>
     */
    @Value("${app.pressure.anchor-mode:TYPICAL_MEAN}")
    private String anchorMode;

    /** The reference formula: no volume anywhere in it. */
    private static final String ANCHOR_TYPICAL_MEAN = "TYPICAL_MEAN";
    /** Opt-in: weight by front-weekly option-chain volume. */
    private static final String ANCHOR_OPTION_TAPE = "OPTION_TAPE_VWAP";

    private final Map<String, SpotFeatures> byKey = new ConcurrentHashMap<>();

    /**
     * VWAP weights per (underlying, date), cached separately from the features.
     *
     * <p>The features are rebuilt every tick because the bar series grows; the
     * weights are not, because they are a property of the DAY. Recomputing them
     * alongside would fire one aggregate query over ~3.8M option rows per tick -
     * roughly 18,000 needless queries across a full-year run - for an answer
     * that cannot change while a replay is running.</p>
     *
     * <p>Fetching the whole day's weights at 10:00 is not lookahead: the weight
     * map is only ever read by timestamp, and {@code SessionAnchoredPrice} iterates
     * the session bars, which are bounded at the tick. A weight for 14:00 sits
     * unread in the map until the replay actually reaches 14:00.</p>
     */
    private final Map<String, Map<LocalDateTime, Double>> weightsByDay = new ConcurrentHashMap<>();

    public SpotFeatureCache(MarketHoursService marketHours,
                            OptionInstrumentResolver instrumentResolver,
                            ObjectProvider<HistoricalOptionCandleRepository> optionCandles) {
        this.marketHours = marketHours;
        this.instrumentResolver = instrumentResolver;
        this.optionCandles = optionCandles;
    }

    /**
     * Features for one underlying on one date, built on first request.
     *
     * @param bars spot bars spanning the warmup window and the day, ascending
     */
    public SpotFeatures get(Instrument instrument, LocalDate date, List<MarketData> bars) {
        if (instrument == null || date == null || bars == null || bars.isEmpty()) return null;

        // The key includes the NEWEST BAR, not just the date.
        //
        // A replay hands this method a series that grows one bar per tick -
        // fetchHistoricalData is bounded at the tick, so at 09:20 it holds bars
        // up to 09:20 and at 14:00 it holds bars up to 14:00. Keying on the date
        // alone meant the object built at the day's FIRST tick was reused for
        // every later one, so `at(asOf)` kept resolving to the 09:15 bar all day
        // and the strategy scored the same opening bar 73 times. That is what a
        // "session bars=1" line in the build log means.
        //
        // Rebuilding per tick is the correct cost and it is small: the work is
        // one linear pass over the warmup window, and the 13 other configs on
        // the same tick all hit this cache. What must NOT happen is keying so
        // coarsely that a stale snapshot is served, because nothing downstream
        // can detect it - a frozen indicator looks exactly like a quiet market.
        MarketData newest = bars.get(bars.size() - 1);
        if (newest == null || newest.getTimestamp() == null) return null;
        String key = UnderlyingSymbols.canonicalName(instrument) + "|" + date + "|" + newest.getTimestamp();

        SpotFeatures cached = byKey.get(key);
        if (cached != null) return cached;

        SpotFeatures built = build(instrument, date, bars);
        // Only this tick's entry is kept. Holding every tick's snapshot would
        // grow to ~73 full feature sets per replayed day for no benefit -
        // nothing ever asks for an earlier tick's object, because `at()` on the
        // current one already answers for every earlier bar.
        byKey.clear();
        byKey.put(key, built);
        return built;
    }

    private SpotFeatures build(Instrument instrument, LocalDate date, List<MarketData> bars) {
        LocalTime open = marketHours.open();
        LocalTime close = marketHours.close();
        LocalTime orEnd = LocalTime.parse(openingRangeEndStr.trim());

        // Null weights = the reference unweighted mean. In TYPICAL_MEAN mode the
        // volume query is not merely ignored, it is never issued - it was the
        // single hottest statement of the replay at 414 ms a call, so skipping
        // it is worth as much in wall time as it is in correctness.
        Map<LocalDateTime, Double> weights = null;
        if (ANCHOR_OPTION_TAPE.equalsIgnoreCase(anchorMode.trim())) {
            weights = weightsByDay.computeIfAbsent(
                    UnderlyingSymbols.canonicalName(instrument) + "|" + date,
                    k -> volumeWeights(instrument, date, open, close));
        } else if (!ANCHOR_TYPICAL_MEAN.equalsIgnoreCase(anchorMode.trim())) {
            // Fail loudly rather than silently falling back: a typo here would
            // otherwise change the indicator for a whole run with no signal.
            throw new IllegalStateException("app.pressure.anchor-mode=\"" + anchorMode
                    + "\" is not recognised - expected " + ANCHOR_TYPICAL_MEAN
                    + " or " + ANCHOR_OPTION_TAPE);
        }

        SpotFeatures f = SpotFeatures.build(bars, date, open, close, orEnd, weights,
                RSI_PERIOD, ATR_PERIOD, ST_MULTIPLIER, ADX_PERIOD);
        if (log.isTraceEnabled()) {
            log.trace("[pressure] built spot features for {} {} — anchor={} session bars={} warmup bars={} weighted bars={}",
                    instrument.getInsName(), date, anchorMode, f.sessionBarCount(), f.warmupBarCount(),
                    weights == null ? 0 : weights.size());
        }
        return f;
    }

    /**
     * Per-bar weight for {@code OPTION_TAPE_VWAP}: front-weekly option volume
     * summed across the chain. Empty map when no historical repository is present
     * or no expiry resolves, which degrades to the unweighted mean rather than
     * dropping the score term.
     */
    private Map<LocalDateTime, Double> volumeWeights(Instrument instrument, LocalDate date,
                                                     LocalTime open, LocalTime close) {
        Map<LocalDateTime, Double> out = new HashMap<>();
        HistoricalOptionCandleRepository repo = optionCandles.getIfAvailable();
        if (repo == null) {
            log.debug("[pressure] no historical option repository — anchor falls back to the unweighted mean for {}", date);
            return out;
        }
        LocalDate expiry = instrumentResolver.resolveExpiry(instrument, date);
        if (expiry == null) {
            log.warn("[pressure] no expiry resolved for {} on {} — anchor falls back to the unweighted mean",
                    instrument.getInsName(), date);
            return out;
        }
        String stockCode = UnderlyingSymbols.canonicalName(instrument);
        List<Object[]> rows = repo.sumVolumeByBar(stockCode, OPTION_EXCHANGE, expiry,
                date.atTime(open), date.atTime(close));
        for (Object[] r : rows) {
            if (r == null || r.length < 2 || r[0] == null) continue;
            LocalDateTime ts = toDateTime(r[0]);
            if (ts == null) continue;
            out.put(ts, toDouble(r[1]));
        }
        return out;
    }

    private static LocalDateTime toDateTime(Object v) {
        if (v instanceof LocalDateTime dt) return dt;
        if (v instanceof java.sql.Timestamp ts) return ts.toLocalDateTime();
        return null;
    }

    private static double toDouble(Object v) {
        if (v == null) return 0d;
        if (v instanceof Number n) return n.doubleValue();
        try {
            return Double.parseDouble(v.toString());
        } catch (NumberFormatException ex) {
            return 0d;
        }
    }

    /** Drops one day's cached state. Called from the replay's per-day cleanup. */
    public void clearDay(LocalDate date) {
        if (date == null) return;
        byKey.keySet().removeIf(k -> k.contains("|" + date));
        weightsByDay.keySet().removeIf(k -> k.endsWith("|" + date));
    }

    /** Drops everything. Used by tests and by a full replay teardown. */
    public void clear() {
        byKey.clear();
        weightsByDay.clear();
    }
}
