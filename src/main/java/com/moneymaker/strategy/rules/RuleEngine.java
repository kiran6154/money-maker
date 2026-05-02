package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.SmaTimeframe;

/**
 * Strategy-agnostic rule execution. Strategies bring their own {@link TradeRules};
 * this class just composes them.
 *
 * <ul>
 *   <li>{@link #evaluate(RuleContext, TradeRules)} — pure AND/OR composition.</li>
 *   <li>{@link #decide(RuleContext, TradeRules, TradeRules)} — SMA-cross gate
 *       plus rule evaluation, returning a {@link TradeAction}.</li>
 *   <li>{@link #resolvePrimarySmaPeriod(TradeConfigCombinedDTO)} — picks the
 *       SMA period to gate on from the config.</li>
 * </ul>
 */
public final class RuleEngine {
    private RuleEngine() {}

    /**
     * Reads {@code config.timeframes[*].sma} and returns the first non-null
     * period, or {@code null} if no SMA is configured.
     */
    public static Integer resolvePrimarySmaPeriod(TradeConfigCombinedDTO config) {
        if (config == null || config.getTimeframes() == null) return null;
        for (SmaTimeframe tf : config.getTimeframes()) {
            if (tf != null && tf.getSma() != null) return tf.getSma();
        }
        return null;
    }

    /**
     * SMA-cross gate + rules:
     * <pre>
     *   open &gt; primarySMA &amp;&amp; close &lt; primarySMA  → SELL candidate
     *   open &lt; primarySMA &amp;&amp; close &gt; primarySMA  → BUY  candidate
     * </pre>
     * Then evaluates the matching {@link TradeRules}. Returns
     * {@link TradeAction#NONE} when no gate fires or its rules fail.
     */
    public static TradeAction decide(RuleContext ctx, TradeRules sellRules, TradeRules buyRules) {
        if (ctx.primarySmaPeriod == null) return TradeAction.NONE;
        double primarySma = CommonRules.smaValue(ctx.candle, ctx.primarySmaPeriod);
        if (primarySma <= 0) return TradeAction.NONE;

        double open  = CommonRules.openValue(ctx.candle);
        double close = CommonRules.closeValue(ctx.candle);

        boolean sellGate = open > primarySma && close < primarySma;
        if (sellGate && evaluate(ctx, sellRules)) return TradeAction.SELL;

        boolean buyGate = open < primarySma && close > primarySma;
        if (buyGate && evaluate(ctx, buyRules)) return TradeAction.BUY;

        return TradeAction.NONE;
    }

    /**
     * Pure rule composition: every {@code required} rule must pass AND
     * ({@code anyOf} is empty OR at least one of its rules passes). A null or
     * empty {@link TradeRules} returns true.
     */
    public static boolean evaluate(RuleContext ctx, TradeRules rules) {
        if (rules == null) return true;
        for (TradeRule r : rules.required) {
            if (!r.test(ctx)) return false;
        }
        if (rules.anyOf.isEmpty()) return true;
        for (TradeRule r : rules.anyOf) {
            if (r.test(ctx)) return true;
        }
        return false;
    }
}
