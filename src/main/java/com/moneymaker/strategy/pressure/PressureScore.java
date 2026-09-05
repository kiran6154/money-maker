package com.moneymaker.strategy.pressure;

import com.moneymaker.indicator.series.Bars;
import com.moneymaker.indicator.series.SpotFeatures;
import com.moneymaker.indicator.series.Supertrend;

/**
 * The Pressure strategy's two integer scores and the direction they resolve to.
 *
 * <pre>
 *   P_down = (RSI &lt; 40) + (close &lt; VWAP) + (ST_dir == -1) + (close &lt; OR_low)
 *            - 1  if  (ADX &gt; 40  AND  -DI now &lt; -DI three bars ago)
 *
 *   P_up   = (RSI &gt; 60) + (close &gt; VWAP) + (ST_dir == +1) + (close &gt; OR_high)
 *            - 1  if  (ADX &gt; 40  AND  +DI now &lt; +DI three bars ago)
 *
 *   signal if P_down &gt;= 3 or P_up &gt;= 3; if BOTH, skip
 * </pre>
 *
 * <p>Four confirming terms, one exhaustion penalty. The penalty is what stops
 * the engine from entering a continuation trade into a trend that is already
 * extended and whose own directional pressure has started to fade — "strong but
 * weakening" is the one configuration where continuation is most likely to be
 * the last entry before a reversal.</p>
 *
 * <h3>Missing inputs subtract, they do not default</h3>
 * Every term is scored {@code false} when its input is {@link Bars#NA} or, for
 * the opening range, when the window has not finished forming. A term that
 * cannot be evaluated must not be counted as satisfied — with a threshold of 3
 * out of 4, treating one unknown as a pass turns a 3-of-4 requirement into
 * 2-of-3 and materially loosens entry. This is why the strategy takes no trades
 * before the opening range completes, independently of the configured entry
 * window.
 *
 * <h3>The penalty applies even when it cannot be evaluated? No.</h3>
 * The reverse of the above: an unevaluable penalty is <b>not</b> applied. A
 * penalty is a reason not to trade, and inventing one from missing data would
 * suppress valid entries. So NA on ADX or DI means "no penalty", NA on a
 * confirming term means "no point". Both readings are the conservative one for
 * the term in question, and they differ in sign because the terms do.
 *
 * <h3>Both sides firing is skipped, not tie-broken</h3>
 * The spec says skip, and skipping is right: a bar that is simultaneously three
 * points down-pressured and three points up-pressured is a bar the model does
 * not understand. Picking the larger score would manufacture a decision out of
 * self-contradiction. It should be rare; {@link Decision#bothSides()} exists so
 * the strategy can log and count it rather than let it pass silently.
 */
public record PressureScore(int down, int up, String downDetail, String upDetail) {

    /** RSI below this scores a down point. */
    public static final double RSI_DOWN = 40d;
    /** RSI above this scores an up point. */
    public static final double RSI_UP = 60d;
    /** ADX above this arms the exhaustion penalty. */
    public static final double ADX_STRONG = 40d;
    /** Score at or above which a side fires. */
    public static final int THRESHOLD = 3;

    /** What the scores resolve to for one bar. */
    public enum Direction {
        /** {@code P_down >= 3}: sell CE, or buy PE. */
        DOWN,
        /** {@code P_up >= 3}: sell PE, or buy CE. */
        UP,
        /** Neither side reached the threshold, or both did. */
        NONE
    }

    /** A scored bar: the two scores, the resolved direction, and why. */
    public record Decision(PressureScore score, Direction direction, boolean bothSides) {
        public String reason() {
            return "P_down=" + score.down() + "[" + score.downDetail() + "] "
                    + "P_up=" + score.up() + "[" + score.upDetail() + "]"
                    + (bothSides ? " BOTH-SIDES-SKIPPED" : "");
        }
    }

    /**
     * Scores one bar. {@code null} snapshot yields a no-signal decision rather
     * than an exception — a tick before the session's first bar is normal.
     */
    public static Decision decide(SpotFeatures.Snapshot s) {
        if (s == null) {
            return new Decision(new PressureScore(0, 0, "no-bar", "no-bar"), Direction.NONE, false);
        }

        boolean orUsable = s.openingRangeComplete()
                && !Bars.isNa(s.openingRangeHigh()) && !Bars.isNa(s.openingRangeLow());
        boolean closeOk = !Bars.isNa(s.close());

        // ---- P_down -------------------------------------------------------
        boolean dRsi = !Bars.isNa(s.rsi()) && s.rsi() < RSI_DOWN;
        boolean dAnchor = closeOk && !Bars.isNa(s.anchorPrice()) && s.close() < s.anchorPrice();
        boolean dSt = s.supertrendDirection() == Supertrend.DOWN;
        boolean dOr = orUsable && closeOk && s.close() < s.openingRangeLow();
        boolean dPenalty = !Bars.isNa(s.adx()) && s.adx() > ADX_STRONG
                && !Bars.isNa(s.minusDi()) && !Bars.isNa(s.minusDi3BarsAgo())
                && s.minusDi() < s.minusDi3BarsAgo();
        int down = count(dRsi, dAnchor, dSt, dOr) - (dPenalty ? 1 : 0);

        // ---- P_up ---------------------------------------------------------
        boolean uRsi = !Bars.isNa(s.rsi()) && s.rsi() > RSI_UP;
        boolean uAnchor = closeOk && !Bars.isNa(s.anchorPrice()) && s.close() > s.anchorPrice();
        boolean uSt = s.supertrendDirection() == Supertrend.UP;
        boolean uOr = orUsable && closeOk && s.close() > s.openingRangeHigh();
        boolean uPenalty = !Bars.isNa(s.adx()) && s.adx() > ADX_STRONG
                && !Bars.isNa(s.plusDi()) && !Bars.isNa(s.plusDi3BarsAgo())
                && s.plusDi() < s.plusDi3BarsAgo();
        int up = count(uRsi, uAnchor, uSt, uOr) - (uPenalty ? 1 : 0);

        PressureScore score = new PressureScore(down, up,
                detail("rsi", dRsi, "anchor", dAnchor, "st", dSt, "or", dOr, dPenalty),
                detail("rsi", uRsi, "anchor", uAnchor, "st", uSt, "or", uOr, uPenalty));

        boolean downFires = down >= THRESHOLD;
        boolean upFires = up >= THRESHOLD;
        if (downFires && upFires) {
            return new Decision(score, Direction.NONE, true);
        }
        if (downFires) return new Decision(score, Direction.DOWN, false);
        if (upFires) return new Decision(score, Direction.UP, false);
        return new Decision(score, Direction.NONE, false);
    }

    private static int count(boolean... flags) {
        int n = 0;
        for (boolean f : flags) if (f) n++;
        return n;
    }

    /** Compact per-term breakdown for the {@code [pressure]} log line. */
    private static String detail(String n1, boolean b1, String n2, boolean b2,
                                 String n3, boolean b3, String n4, boolean b4, boolean penalty) {
        StringBuilder sb = new StringBuilder();
        if (b1) sb.append(n1).append(' ');
        if (b2) sb.append(n2).append(' ');
        if (b3) sb.append(n3).append(' ');
        if (b4) sb.append(n4).append(' ');
        if (penalty) sb.append("-adxfade ");
        return sb.length() == 0 ? "none" : sb.toString().trim();
    }
}
