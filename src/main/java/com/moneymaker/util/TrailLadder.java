package com.moneymaker.util;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * The only place {@code trade_config.trail_ladder} is parsed or rendered.
 *
 * <p>The column holds the trailing stop-loss rungs as ascending
 * {@code trigger:lock} pairs in premium points — {@code "25:2,50:25,75:50"}
 * reads as "once the trade has been 25 points in profit, the stop moves to +2;
 * at 50 it moves to +25; at 75 to +50". See changeset 036.</p>
 *
 * <p>A rung may lock at <b>exactly</b> its own trigger ({@code "25:25"}): that is
 * a pure give-back trail — "reach +25, then exit if you fall back to +25" — and
 * it is what the Pressure strategy uses. It is safe because
 * {@code PositionService} arms rungs after its breach check, so such a floor
 * cannot fire on the bar that armed it. Only {@code lock > trigger} is refused.
 * See the check in {@link #parse} for the full argument.</p>
 *
 * <p>Same discipline as {@link StrategyIds}, for the same reason: a
 * multi-value column is only as sound as the guarantee that nothing else
 * invents its own splitting, ordering or whitespace rules. <b>Do not parse this
 * column anywhere else.</b></p>
 *
 * <p>Unlike {@code StrategyIds}, parsing here is <b>strict</b>. A dropped
 * strategy id is visible immediately — that strategy stops trading. A dropped
 * rung is invisible: the trade still opens, still monitors, and only behaves
 * differently in the minority of trades that reach the rung, which is exactly
 * the case nobody is watching. So a malformed ladder is rejected at the form
 * ({@code TradeConfigAdminService}) and refused at entry
 * ({@code OrderService}), never silently trimmed.</p>
 */
public final class TrailLadder {

    private TrailLadder() {
    }

    /**
     * One step of the ladder: once peak profit reaches {@code trigger} premium
     * points, the stop-loss moves to {@code lock} points.
     *
     * <p>{@code lock} is signed and read the same way P&amp;L is: {@code +2} is a
     * stop two points into profit, {@code -30} a stop still 30 points underwater.
     * Negative locks are legitimate — tightening a 60-point stop to 30 before the
     * trade is green is risk reduction, not profit protection.</p>
     */
    public record Rung(BigDecimal trigger, BigDecimal lock) {
    }

    /**
     * Parses the column into rungs ordered by ascending trigger.
     *
     * <p>Null or blank yields an empty list, which callers read as "no trailing"
     * — the fixed {@code stop_loss_at_entry} then applies alone, which is how
     * every config behaved before changeset 036.</p>
     *
     * @throws IllegalArgumentException if any fragment is malformed, or if the
     *         rungs do not form a valid ratchet (see the checks below — each one
     *         describes a ladder that would misbehave silently at runtime).
     */
    public static List<Rung> parse(String ladder) {
        if (ladder == null || ladder.isBlank()) return List.of();

        List<Rung> rungs = new ArrayList<>();
        for (String part : ladder.split(",")) {
            String fragment = part.trim();
            if (fragment.isEmpty()) continue;

            String[] halves = fragment.split(":");
            if (halves.length != 2) {
                throw new IllegalArgumentException("trailLadder rung \"" + fragment
                        + "\" must be trigger:lock, e.g. \"25:2\"");
            }
            BigDecimal trigger = number(halves[0], fragment, "trigger");
            BigDecimal lock = number(halves[1], fragment, "lock");

            if (trigger.signum() <= 0) {
                throw new IllegalArgumentException("trailLadder rung \"" + fragment
                        + "\" has a non-positive trigger — a rung arms on profit, so it must be above 0");
            }
            // lock > trigger is still refused: the floor would sit ABOVE the
            // peak that armed it, so the trade exits at a P&L it has never
            // reached. That is not a trailing stop under any reading.
            //
            // lock == trigger is ALLOWED, and used to be refused. The original
            // objection was "the trade would exit the moment the rung arms",
            // and it is wrong about this codebase: PositionService.handleOne
            // arms rungs (applyTrail) strictly AFTER its breach check, so the
            // bar whose excursion earns a rung cannot also exit on it. The
            // earliest a lock == trigger floor can fire is the NEXT bar, which
            // is exactly "give back everything above +N and you are out" — a
            // real give-back trail, and the shape the Pressure strategy's
            // "arm at +25, exit on a fall back to +25" specifies.
            //
            // It is genuinely different from target_at_entry: a target exits at
            // +N on the way UP, this exits at +N on the way BACK DOWN, and only
            // after +N was reached. A trade that runs to +60 and retraces books
            // +25 here and would have booked +25 on the target long before ever
            // seeing +60.
            if (lock.compareTo(trigger) > 0) {
                throw new IllegalArgumentException("trailLadder rung \"" + fragment
                        + "\" locks above its own trigger — the floor would sit above the peak that armed it");
            }
            rungs.add(new Rung(trigger, lock));
        }

        for (int i = 1; i < rungs.size(); i++) {
            Rung prev = rungs.get(i - 1);
            Rung cur = rungs.get(i);
            // Ascending triggers are what let lockFor scan once and stop; the
            // column is hand-edited, so this is a realistic thing to get wrong.
            if (cur.trigger().compareTo(prev.trigger()) <= 0) {
                throw new IllegalArgumentException("trailLadder triggers must ascend — "
                        + prev.trigger() + " is followed by " + cur.trigger());
            }
            // A ratchet cannot loosen. A higher rung locking less than a lower one
            // would mean the stop falls back as the trade goes further in profit.
            if (cur.lock().compareTo(prev.lock()) < 0) {
                throw new IllegalArgumentException("trailLadder locks must not decrease — trigger "
                        + cur.trigger() + " locks " + cur.lock() + ", below the " + prev.lock()
                        + " already locked at " + prev.trigger());
            }
        }
        return rungs;
    }

    /**
     * The stop-loss floor earned by a peak profit of {@code peakProfit}, or
     * {@code null} if no rung has been reached yet.
     *
     * <p>Returns the <i>highest</i> rung at or below the peak, so a trade that
     * jumps straight from +5 to +80 in one candle lands on the +50 floor rather
     * than walking the ladder a rung per tick.</p>
     */
    public static BigDecimal lockFor(List<Rung> rungs, BigDecimal peakProfit) {
        if (rungs == null || rungs.isEmpty() || peakProfit == null) return null;
        BigDecimal lock = null;
        for (Rung rung : rungs) {
            if (peakProfit.compareTo(rung.trigger()) >= 0) {
                lock = rung.lock();
            } else {
                break; // parse() guarantees ascending triggers
            }
        }
        return lock;
    }

    /** Convenience for callers holding the raw column. See {@link #parse}. */
    public static BigDecimal lockFor(String ladder, BigDecimal peakProfit) {
        return lockFor(parse(ladder), peakProfit);
    }

    /**
     * Renders rungs to the column's canonical form: ascending, colon-separated,
     * comma-separated, no spaces. {@code null} for an empty ladder, so "no
     * trailing" is stored as NULL rather than an empty string.
     */
    public static String format(List<Rung> rungs) {
        if (rungs == null || rungs.isEmpty()) return null;
        StringBuilder sb = new StringBuilder();
        for (Rung rung : rungs) {
            if (sb.length() > 0) sb.append(',');
            sb.append(strip(rung.trigger())).append(':').append(strip(rung.lock()));
        }
        return sb.toString();
    }

    /**
     * Validates and canonicalises a ladder in one step — parse, then re-render.
     * Used on the write path so the column never stores the spacing someone
     * happened to type.
     *
     * @throws IllegalArgumentException as {@link #parse}
     */
    public static String canonical(String ladder) {
        return format(parse(ladder));
    }

    private static BigDecimal number(String raw, String fragment, String half) {
        try {
            return new BigDecimal(raw.trim());
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("trailLadder rung \"" + fragment
                    + "\" has a non-numeric " + half + ": \"" + raw.trim() + "\"");
        }
    }

    /** 25.0000 -> 25, so a round-tripped ladder reads the way it was typed. */
    private static String strip(BigDecimal value) {
        return value.stripTrailingZeros().toPlainString();
    }
}
