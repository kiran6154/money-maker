package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.SmaTimeframe;

/**
 * Strategy-agnostic rule execution. Strategies bring their own {@link TradeRules};
 * this class just composes them.
 *
 * <p>{@link #decide(RuleContext, TradeRules, TradeRules)} returns a
 * {@link Decision} that carries both the action and a human-readable reason —
 * the caller (typically Strategy1) prints the reason on the tick log so you can
 * see at-a-glance WHY a gate did/didn't fire and which rule passed or failed.
 */
public final class RuleEngine {
    private RuleEngine() {}

    /** Action + reason. Reason is a short one-liner suitable for the [tick] log. */
    public record Decision(TradeAction action, String reason) {}

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
     *   open &lt; primarySMA &amp;&amp; close &gt; primarySMA  → BUY  candidate (currently disabled)
     * </pre>
     */
    public static Decision decide(RuleContext ctx, TradeRules sellRules, TradeRules buyRules) {
        if (ctx.primarySmaPeriod == null) {
            return new Decision(TradeAction.NONE, "primarySma=null");
        }
        double primarySma = CommonRules.smaValue(ctx.candle, ctx.primarySmaPeriod);
        if (primarySma <= 0) {
            return new Decision(TradeAction.NONE,
                    "sma" + ctx.primarySmaPeriod + "=N/A (need more historical candles)");
        }

        double open  = CommonRules.openValue(ctx.candle);
        double close = CommonRules.closeValue(ctx.candle);

        boolean sellGate   = open > primarySma && close < primarySma;
        boolean rawBuyGate = open < primarySma && close > primarySma;

        if (sellGate) {
            EvalResult r = evaluateWithReason(ctx, sellRules);
            if (r.pass) return new Decision(TradeAction.SELL,
                    "sellGate=true, sell rules OK [" + r.reason + "]");
            return new Decision(TradeAction.NONE,
                    "sellGate=true, sell rules FAIL [" + r.reason + "]");
        }

        // Raw buy gate is intentionally disabled. Buy rules still run (e.g. an
        // end-of-day close); buyGate=false is reported for clarity.
        EvalResult r = evaluateWithReason(ctx, buyRules);
        if (r.pass) return new Decision(TradeAction.BUY,
                "sellGate=false, rawBuyGate=" + rawBuyGate + " (disabled), buy rules OK [" + r.reason + "]");
        return new Decision(TradeAction.NONE,
                "sellGate=false, rawBuyGate=" + rawBuyGate + " (disabled), buy rules FAIL [" + r.reason + "]");
    }

    /**
     * Pure rule composition retained for callers that only want a boolean.
     * Uses the same logic as {@link #evaluateWithReason} but discards the reason.
     */
    public static boolean evaluate(RuleContext ctx, TradeRules rules) {
        return evaluateWithReason(ctx, rules).pass;
    }

    /**
     * Evaluates {@link TradeRules} (required AND, anyOf OR) and returns both
     * the boolean and a one-line reason naming the first failing required rule
     * or the matching anyOf rule. A null or fully-empty rules object returns
     * {@code pass=true, reason="no rules"}.
     */
    private static EvalResult evaluateWithReason(RuleContext ctx, TradeRules rules) {
        if (rules == null
                || (rules.required.isEmpty() && rules.anyOf.isEmpty())) {
            return new EvalResult(true, "no rules");
        }
        for (int i = 0; i < rules.required.size(); i++) {
            TradeRule r = rules.required.get(i);
            if (!r.test(ctx)) {
                return new EvalResult(false, "required[" + i + ":" + r.name() + "]=FAIL");
            }
        }
        if (rules.anyOf.isEmpty()) {
            return new EvalResult(true, "required all OK");
        }
        for (int i = 0; i < rules.anyOf.size(); i++) {
            TradeRule r = rules.anyOf.get(i);
            if (r.test(ctx)) {
                return new EvalResult(true, "anyOf[" + i + ":" + r.name() + "]=OK");
            }
        }
        return new EvalResult(false, "all " + rules.anyOf.size() + " anyOf FAIL");
    }

    private record EvalResult(boolean pass, String reason) {}
}
