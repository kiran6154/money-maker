package com.moneymaker.strategy;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.StrategyDefaults;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.repository.StrategyDefaultsRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * {@link Strategy8} plus the three entry gates the indicator / price-action /
 * volume study of 2026-09-06 found to transfer (S30 in
 * {@code docs/STRATEGY_ANALYSIS_TODO.md}). Each gate is switched by one
 * nullable {@code strategy_defaults} column (changeset 049); with all three
 * null this bean trades exactly as Strategy 8.
 *
 * <ol>
 *   <li><b>Candle shape</b> — {@code min_candle_close_position}: the signal
 *       candle must close at least that fraction of its range above its low
 *       ({@code (close − low) / (high − low)}). Two thirds of Strategy 8's
 *       entries close on the candle's low and average +2.9; the rest average
 *       +9.7 to +19. A doji ({@code high == low}) cannot be judged and is
 *       allowed. Seeded 0.25.</li>
 *   <li><b>No near-ATM volume spike</b> — {@code max_volume_surge}: the
 *       signal bar's option volume summed over every cached 15-minute leg
 *       (both sides) whose strike is within {@value #VOLUME_STRIKE_WINDOW}
 *       points of the session-open ATM, divided by the median of the same
 *       sum over the previous {@value #VOLUME_LOOKBACK_BARS} bars, must not
 *       exceed the multiple. Entries on a spike (> 2×) averaged +0.5 a trade;
 *       the gate raised total points and cut the drawdown in both years on
 *       both the intraday and the hold-to-expiry replay. Unknown allows:
 *       no underlying series, no strike step, fewer than
 *       {@value #VOLUME_MIN_HISTORY} prior bars, or a zero median. Seeded
 *       2.00. <i>Measured over the legs the cache holds</i> — configs whose
 *       legs span at least ±200 points (depth ≥ 2, or a day that also runs
 *       the auto-downtrend configs) reproduce the replay; a lone depth-0 leg
 *       measures only itself.</li>
 *   <li><b>Days to expiry</b> — {@code min_days_to_expiry}: calendar days
 *       from the session to the expiry the leg trades on. Entries with 0–1
 *       days left averaged +0.5 against +10 to +14 beyond; the gate costs
 *       trades but lifts the profit factor and halves the drawdown. Unknown
 *       (no resolver, no expiry) allows. Seeded 2.</li>
 * </ol>
 *
 * <p>Replay (Python replica, dbeaver export, Jan-2024 → Dec-2025, ATM leg,
 * 1 pt/round trip): volume gate alone — intraday 1,431 trades, +2.8/trade,
 * +3,972 pts (Strategy 8: 1,780, +2.0, +3,532), drawdown −361 vs −727;
 * hold-to-expiry 898 trades, +7.6, +6,823 (base +6,366). All three gates as
 * seeded — intraday 602 trades, +4.8/trade, +2,902, PF 1.38, drawdown −265;
 * hold 457 trades, +12.5, +5,704, PF 1.79, drawdown −296, both years alike.
 * Null the expiry gate to keep more trades. The strike window, lookback and
 * minimum history are strategy identity like Strategy 8's constants; the
 * thresholds are configuration (CLAUDE.md #9).</p>
 */
@Component
public class Strategy9 extends Strategy8 {

    public static final int ID = 9;

    /** Strikes within this many points of the session-open ATM count towards the volume sum. */
    public static final int VOLUME_STRIKE_WINDOW = 200;

    /** Trailing bars whose summed volume forms the median the signal bar is compared with. */
    public static final int VOLUME_LOOKBACK_BARS = 25;

    /** Fewer prior bars than this and the volume gate cannot be judged (allows). */
    public static final int VOLUME_MIN_HISTORY = 10;

    /** Strike step used when the instrument does not say (NIFTY). */
    static final int DEFAULT_STRIKE_STEP = 100;

    /** The three thresholds; any null = that gate is off. */
    public record GateSettings(BigDecimal maxVolumeSurge, BigDecimal minCandleClosePosition, Integer minDaysToExpiry) {
        static final GateSettings OFF = new GateSettings(null, null, null);
    }

    @Autowired(required = false)
    private StrategyDefaultsRepository strategyDefaultsRepository;

    private volatile GateSettings settings = GateSettings.OFF;
    private volatile LocalDate settingsDay;
    private GateSettings pinnedSettings;

    public Strategy9(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    /** Strategy 8's rules with the three gates appended, in that order, so a blocked entry names the earlier rule first. */
    @Override
    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        TradeRules base = super.sellRulesFor(primarySmaPeriod);
        List<TradeRule> required = new ArrayList<>(base.required);
        required.add(TradeRule.named("candleNotAtLow", this::candleClosePositionOk));
        required.add(TradeRule.named("noNearAtmVolumeSpike", this::volumeSurgeOk));
        required.add(TradeRule.named("minDaysToExpiry", this::daysToExpiryOk));
        return new TradeRules(required, base.anyOf);
    }

    // ------------------------------------------------------------ settings

    /** Tests: supply the repository the container would inject. */
    void useRepository(StrategyDefaultsRepository repository) {
        this.strategyDefaultsRepository = repository;
        this.settingsDay = null;
    }

    /** Pin the thresholds (tests, or a caller without a repository); null restores the repository lookup. */
    void useSettings(GateSettings fixed) {
        this.pinnedSettings = fixed;
        this.settingsDay = null;
    }

    /**
     * The strategy's {@code strategy_defaults} thresholds, read once per session
     * so an operator edit takes effect next day and a tick never waits on the
     * database more than once. No repository (hand-built strategy) = all gates off.
     */
    GateSettings settingsFor(LocalDate day) {
        if (pinnedSettings != null) return pinnedSettings;
        if (strategyDefaultsRepository == null) return GateSettings.OFF;
        if (day != null && day.equals(settingsDay)) return settings;
        StrategyDefaults row = strategyDefaultsRepository.findById(getId()).orElse(null);
        GateSettings s = row == null ? GateSettings.OFF
                : new GateSettings(row.getMaxVolumeSurge(), row.getMinCandleClosePosition(), row.getMinDaysToExpiry());
        settings = s; settingsDay = day;
        if (row == null) {
            log.warn("[strategy{}] no strategy_defaults row — all three gates off, trading as Strategy 8", getId());
        }
        return s;
    }

    private static LocalDate sessionOf(RuleContext ctx) {
        if (ctx.asOf != null) return ctx.asOf.toLocalDate();
        return ctx.candle != null && ctx.candle.getTimestamp() != null ? ctx.candle.getTimestamp().toLocalDate() : null;
    }

    // ------------------------------------------------------------ gate 1: candle shape

    boolean candleClosePositionOk(RuleContext ctx) {
        BigDecimal min = settingsFor(sessionOf(ctx)).minCandleClosePosition();
        if (min == null) return true;
        Double pos = closePositionInRange(ctx.candle);
        return pos == null || pos >= min.doubleValue();
    }

    /** {@code (close − low) / (high − low)}, or null when the bar has no range or a missing field. */
    static Double closePositionInRange(MarketData c) {
        if (c == null || c.getHigh() == null || c.getLow() == null || c.getClose() == null) return null;
        double h = c.getHigh().doubleValue(), l = c.getLow().doubleValue();
        if (h - l <= 0) return null;
        return (c.getClose().doubleValue() - l) / (h - l);
    }

    // ------------------------------------------------------------ gate 2: near-ATM volume spike

    boolean volumeSurgeOk(RuleContext ctx) {
        BigDecimal max = settingsFor(sessionOf(ctx)).maxVolumeSurge();
        if (max == null) return true;
        Double surge = nearAtmVolumeSurge(ctx);
        return surge == null || surge <= max.doubleValue();
    }

    /**
     * Signal-bar near-ATM volume over the median of the previous
     * {@value #VOLUME_LOOKBACK_BARS} bars, or null when it cannot be judged.
     * The bar grid is the traded leg's own series; every other cached leg of
     * the same underlying and interval contributes the volume of its bar with
     * the same timestamp (nothing when it has none), de-duplicated by side and
     * strike because one leg is cached once per config depth.
     */
    Double nearAtmVolumeSurge(RuleContext ctx) {
        if (ctx == null || ctx.strikeKey == null || ctx.allCandles == null || ctx.candle == null) return null;
        String[] parts = ctx.strikeKey.split("\\|");
        if (parts.length < 7) return null;
        Integer refAtm = sessionOpenAtm(parts[0], parts[1], ctx);
        if (refAtm == null) return null;
        Map<String, List<MarketData>> cache = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) return null;
        // bar grid: signal bar and the previous LOOKBACK bars of the traded leg
        int end = Math.min(ctx.index, ctx.allCandles.size() - 1);
        int start = Math.max(0, end - VOLUME_LOOKBACK_BARS);
        List<LocalDateTime> grid = new ArrayList<>();
        for (int i = start; i <= end; i++) {
            MarketData c = ctx.allCandles.get(i);
            if (c != null && c.getTimestamp() != null) grid.add(c.getTimestamp());
        }
        if (grid.size() < VOLUME_MIN_HISTORY + 1) return null;
        Map<LocalDateTime, Long> sum = new HashMap<>();
        Set<String> seen = new HashSet<>();
        int legs = 0;
        for (Map.Entry<String, List<MarketData>> e : cache.entrySet()) {
            String[] p = e.getKey().split("\\|");
            if (p.length < 7 || !p[0].equals(parts[0]) || !p[1].equals(parts[1])) continue;
            int strike;
            try { strike = Integer.parseInt(p[3].trim()); } catch (NumberFormatException ex) { continue; }
            if (Math.abs(strike - refAtm) > VOLUME_STRIKE_WINDOW) continue;
            if (!seen.add(p[2] + "|" + strike)) continue;
            List<MarketData> series = e.getValue();
            if (series == null || series.isEmpty()) continue;
            legs++;
            Map<LocalDateTime, Long> byTs = new HashMap<>();
            for (int i = series.size() - 1, taken = 0; i >= 0 && taken <= VOLUME_LOOKBACK_BARS + 30; i--, taken++) {
                MarketData c = series.get(i);
                if (c == null || c.getTimestamp() == null || c.getVolume() == null) continue;
                byTs.put(c.getTimestamp(), c.getVolume());
            }
            for (LocalDateTime ts : grid) {
                Long v = byTs.get(ts);
                if (v != null) sum.merge(ts, v, Long::sum);
            }
        }
        if (legs == 0) return null;
        LocalDateTime signalTs = grid.get(grid.size() - 1);
        double current = sum.getOrDefault(signalTs, 0L);
        double[] prior = new double[grid.size() - 1];
        for (int i = 0; i < grid.size() - 1; i++) prior[i] = sum.getOrDefault(grid.get(i), 0L);
        Arrays.sort(prior);
        int m = prior.length;
        double median = m % 2 == 1 ? prior[m / 2] : (prior[m / 2 - 1] + prior[m / 2]) / 2.0;
        if (median <= 0) return null;
        double surge = current / median;
        log.debug("[strategy{}] volume gate: legs={} atmRef={} signal={} median={} surge={}", ID, legs, refAtm, current, median, surge);
        return surge;
    }

    /** The underlying's first settled bar of the session, closed, rounded to the strike step; null when unknown. */
    Integer sessionOpenAtm(String token, String interval, RuleContext ctx) {
        Map<String, List<MarketData>> spot = SharedData.marketDataByInstrumentAndInterval;
        if (spot == null) return null;
        List<MarketData> series = spot.get(token + "|" + interval);
        if (series == null || series.isEmpty()) return null;
        LocalDate day = sessionOf(ctx);
        if (day == null) return null;
        MarketData first = null;
        for (MarketData c : series) {
            if (c != null && c.getTimestamp() != null && c.getTimestamp().toLocalDate().equals(day)) { first = c; break; }
        }
        if (first == null || first.getClose() == null) return null;
        int step = DEFAULT_STRIKE_STEP;
        Instrument ins = ctx.config != null ? ctx.config.getInstrument() : null;
        if (ins != null && ins.getStrikePoints() != null && ins.getStrikePoints().signum() > 0) step = ins.getStrikePoints().intValue();
        return (int) (Math.round(first.getClose().doubleValue() / step) * step);
    }

    // ------------------------------------------------------------ gate 3: days to expiry

    boolean daysToExpiryOk(RuleContext ctx) {
        Integer min = settingsFor(sessionOf(ctx)).minDaysToExpiry();
        if (min == null) return true;
        LocalDate day = sessionOf(ctx);
        LocalDate expiry = day == null ? null : expiryFor(ctx, day);
        if (expiry == null) return true;
        return ChronoUnit.DAYS.between(day, expiry) >= min;
    }

    /** The expiry the leg trades on, via the resolver the scheduler used; null = unknown. Overridable for tests. */
    protected LocalDate expiryFor(RuleContext ctx, LocalDate day) {
        if (instrumentResolver == null || ctx.config == null || ctx.config.getInstrument() == null) return null;
        try {
            return instrumentResolver.resolveExpiry(ctx.config.getInstrument(), day);
        } catch (RuntimeException ex) {
            log.debug("[strategy{}] expiry unknown for {} on {}: {}", ID, ctx.strikeKey, day, ex.toString());
            return null;
        }
    }
}
