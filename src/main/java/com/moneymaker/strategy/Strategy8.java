package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.RuleEngine;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * The "20SMA 15min candle" rule (analysis 2026-09-06, S29 in
 * {@code docs/STRATEGY_ANALYSIS_TODO.md}): sell the leg when, on its own
 * <b>15-minute</b> candles, the 20-period SMA of closes is sloping down
 * ({@code SMA20[t] < SMA20[t-1]}) <i>and</i> the newest settled candle closes
 * below the previous candle's close. There is no SMA-cross gate and no
 * whole-day down-trend requirement: this strategy does not inherit Strategy 1's
 * trigger, it replaces it ({@link #decide} routes the rules through
 * {@link RuleEngine#decideWithoutCrossGate}).
 *
 * <p><b>Exit.</b> A chandelier trailing stop: lowest low since entry plus
 * {@code strategy_defaults.trail_atr_multiple} × ATR-14 of the same 15-minute
 * series (measured on the signal bar and frozen onto the order as
 * {@code trade_order.trail_atr_distance_at_entry}), ratcheting down only, no
 * profit target ({@code target_mode = NONE}). The config's {@code sl_pct} /
 * {@code max_sl_points} stay as the hard cap on the first stop, and the 15:15
 * close signal / 15:20 force-close end the day as for every other strategy —
 * this is the <i>intraday</i> form of the rule; carrying to expiry is S29.</p>
 *
 * <p><b>What it reads.</b> Only the config's 15-minute {@code sma_timeframe}
 * row: {@link #execute} narrows the config to its first 15-minute row so a leg
 * is judged once per tick however many periods the detector wrote for it, and
 * a config without a 15-minute row trades nothing (logged once a day). The
 * row's SMA period is irrelevant to the rule and is used only for the
 * {@code [tick]} log.</p>
 *
 * <p><b>Config prerequisites.</b> {@code transaction_type = SELL}; a
 * {@code strategy_defaults} row (changeset 048 seeds one as a copy of strategy
 * 1's block with {@code target_mode = NONE} and {@code trail_atr_multiple =
 * 2.00}); for {@code AUTO_DOWNTREND} generation a
 * {@code sma_downtrend_rule_strategy} tag, which changeset 048 deliberately
 * does not add (CLAUDE.md Rule 0(c)).</p>
 *
 * <p>The four numbers below are strategy identity in the same sense as
 * Strategy 6's constants (S21 open question (a)): the signal timeframe, the SMA
 * period, the ATR period and the 14:45 cut-off are what makes a config tagged
 * 8 different from one tagged 1. The trail multiple and the stop cap are
 * exit parameters and come from configuration.</p>
 */
@Component
public class Strategy8 extends AbstractSmaCrossStrategy {

    public static final int ID = 8;

    /** Candle width of the series the rule is evaluated on, in minutes. */
    public static final int SIGNAL_TIMEFRAME_MINUTES = 15;

    /** Period of the SMA of closes whose slope must be down on the signal bar. */
    public static final int SIGNAL_SMA_PERIOD = 20;

    /** ATR period (simple mean of true range) behind the chandelier distance. */
    public static final int ATR_PERIOD = 14;

    /** Last admissible entry bar starts this many minutes before the close signal (14:45). */
    public static final int ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE_SIGNAL = 30;

    static final String SIGNAL_INTERVAL = SIGNAL_TIMEFRAME_MINUTES + "minute";

    private static final java.util.Set<String> noRowLoggedToday =
            java.util.concurrent.ConcurrentHashMap.newKeySet();

    public Strategy8(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    /**
     * Runs the shared scan on a view of the config that carries only its first
     * 15-minute {@code sma_timeframe} row. The engine evaluates every row it is
     * given, so a config with two 15-minute periods would otherwise emit the
     * same signal twice per tick, and a 5-minute row can never satisfy
     * {@code is15MinuteSeries} — skipping it here saves the scan.
     */
    @Override
    public void execute(TradeConfigCombinedDTO config, LocalDateTime asOf) {
        if (config == null || config.getTradeConfig() == null) return;
        List<SmaTimeframe> rows = config.getTimeframes();
        SmaTimeframe row = null;
        if (rows != null) {
            for (SmaTimeframe tf : rows) {
                if (tf != null && tf.getTimePeriod() != null
                        && tf.getTimePeriod().intValue() == SIGNAL_TIMEFRAME_MINUTES) {
                    row = tf;
                    break;
                }
            }
        }
        if (row == null) {
            String onceKey = (asOf != null ? asOf.toLocalDate() : "?") + "|" + config.getTradeConfig().getId();
            if (noRowLoggedToday.size() > 1024) noRowLoggedToday.clear();
            if (noRowLoggedToday.add(onceKey)) {
                log.warn("[strategy{}] tradeConfigId={} has no {}-minute sma_timeframe row — nothing to scan "
                                + "(add one; the SMA period on it does not matter to this strategy)",
                        ID, config.getTradeConfig().getId(), SIGNAL_TIMEFRAME_MINUTES);
            }
            return;
        }
        TradeConfigCombinedDTO view = new TradeConfigCombinedDTO();
        view.setTradeConfig(config.getTradeConfig());
        view.setInstrument(config.getInstrument());
        view.setInstrumentDetails(config.getInstrumentDetails());
        view.setTimeframes(List.of(row));
        view.setStrategyId(config.getStrategyId());
        super.execute(view, asOf);
    }

    /** No cross gate: SELL when the sell rules pass, else BUY when the buy rules pass. */
    @Override
    protected RuleEngine.Decision decide(RuleContext ctx, TradeRules sellRules, TradeRules buyRules) {
        return RuleEngine.decideWithoutCrossGate(ctx, sellRules, buyRules);
    }

    /**
     * The rule, period-independent. Required, in the order a blocked entry
     * should name them: the series must be the 15-minute one, the SMA-20 slope
     * must be down, the candle must close below the previous close, and the bar
     * must start at or before 14:45.
     */
    @Override
    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("is15MinuteSeries", Strategy8::isSignalTimeframe));
        required.add(TradeRule.named("sma20SlopeDown", Strategy8::smaSlopeDown));
        required.add(TradeRule.named("closeBelowPrevClose", Strategy8::closeBelowPreviousClose));
        required.add(TradeRule.named("entryAtOrBefore1445",
                ctx -> CommonRules.isAtOrBeforeEntryCutoff(ctx, ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE_SIGNAL)));
        return new TradeRules(required, new ArrayList<>());
    }

    /** The close-time BUY exit, as every SELL strategy has it. */
    @Override
    protected TradeRules buyRulesFor(Integer primarySmaPeriod) {
        List<TradeRule> anyOf = new ArrayList<>();
        anyOf.add(TradeRule.named("isMarketCloseTime", CommonRules::isMarketCloseTime));
        return new TradeRules(new ArrayList<>(), anyOf);
    }

    /** ATR-14 of the signal bar's series, carried on the signal for the chandelier distance. */
    @Override
    protected BigDecimal signalAtr(RuleContext ctx) {
        if (ctx == null || ctx.allCandles == null) return null;
        return atr(ctx.allCandles, ctx.index, ATR_PERIOD);
    }

    // ------------------------------------------------------------ rules

    static boolean isSignalTimeframe(RuleContext ctx) {
        if (ctx == null || ctx.strikeKey == null) return false;
        String[] parts = ctx.strikeKey.split("\\|");
        return parts.length >= 2 && SIGNAL_INTERVAL.equals(parts[1]);
    }

    static boolean smaSlopeDown(RuleContext ctx) {
        if (ctx == null || ctx.allCandles == null) return false;
        Double current = smaOfCloses(ctx.allCandles, ctx.index, SIGNAL_SMA_PERIOD);
        Double previous = smaOfCloses(ctx.allCandles, ctx.index - 1, SIGNAL_SMA_PERIOD);
        return current != null && previous != null && current < previous;
    }

    static boolean closeBelowPreviousClose(RuleContext ctx) {
        if (ctx == null || ctx.allCandles == null || ctx.index < 1 || ctx.index >= ctx.allCandles.size()) return false;
        MarketData now = ctx.allCandles.get(ctx.index);
        MarketData prev = ctx.allCandles.get(ctx.index - 1);
        if (now == null || prev == null || now.getClose() == null || prev.getClose() == null) return false;
        return now.getClose().compareTo(prev.getClose()) < 0;
    }

    /**
     * Mean of the last {@code n} closes ending at {@code endIndex}, or null when
     * the series is too short or a close is missing. Consecutive bars of the
     * series, across sessions: the 20-bar window of the 09:15 candle reaches
     * into the previous day, exactly as a 15-minute chart draws it.
     */
    static Double smaOfCloses(List<MarketData> candles, int endIndex, int n) {
        if (candles == null || endIndex < n - 1 || endIndex >= candles.size()) return null;
        double sum = 0d;
        for (int i = endIndex - n + 1; i <= endIndex; i++) {
            MarketData c = candles.get(i);
            if (c == null || c.getClose() == null) return null;
            sum += c.getClose().doubleValue();
        }
        return sum / n;
    }

    /**
     * Simple-mean ATR over the last {@code n} bars ending at {@code endIndex}:
     * true range = max(high − low, |high − previous close|, |low − previous
     * close|). Needs {@code n + 1} bars (a previous close for the first one).
     */
    static BigDecimal atr(List<MarketData> candles, int endIndex, int n) {
        if (candles == null || endIndex < n || endIndex >= candles.size()) return null;
        double sum = 0d;
        for (int i = endIndex - n + 1; i <= endIndex; i++) {
            MarketData c = candles.get(i);
            MarketData p = candles.get(i - 1);
            if (c == null || p == null || c.getHigh() == null || c.getLow() == null || p.getClose() == null) return null;
            double h = c.getHigh().doubleValue(), l = c.getLow().doubleValue(), pc = p.getClose().doubleValue();
            sum += Math.max(h - l, Math.max(Math.abs(h - pc), Math.abs(l - pc)));
        }
        return BigDecimal.valueOf(sum / n).setScale(4, RoundingMode.HALF_UP);
    }
}
