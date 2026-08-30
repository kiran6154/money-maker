package com.moneymaker.structure;

import com.moneymaker.entity.MarketData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Price-structure analysis: swing points, Break of Structure (BOS) and Change of
 * Character (CHoCH).
 *
 * <h3>Definitions</h3>
 * A <b>swing high</b> at bar {@code i} is a high strictly greater than the highs
 * of the {@code fractalN} bars either side; a <b>swing low</b> is the mirror.
 * The sequence of confirmed swings gives a structure state: higher-high /
 * higher-low is bullish, lower-high / lower-low is bearish.
 *
 * <ul>
 *   <li><b>BOS</b> — a close beyond the last swing <i>in the direction of the
 *       prevailing structure</i>. The trend continues.</li>
 *   <li><b>CHoCH</b> — a close beyond the last swing <i>against</i> the
 *       prevailing structure. That first contrary break is the change of
 *       character, and it flips the structure state.</li>
 * </ul>
 *
 * <h3>Confirmation lag is the whole problem</h3>
 * A swing cannot be recognised when it prints. Bar {@code i} is only known to be
 * a swing high once {@code fractalN} further bars have closed below it, so the
 * earliest a strategy could act on that level is bar {@code i + fractalN}.
 *
 * <p>Every {@link StructureEvent} therefore carries both {@code occurredAt} (the
 * bar whose close broke the level) and {@code confirmableAt} (the bar by which
 * the broken swing had itself been confirmed). <b>Analysis must filter on
 * {@code confirmableAt}.</b> Reading these events at {@code occurredAt} would
 * reintroduce precisely the look-ahead this codebase has just been cleaned of —
 * crediting the strategy with a level before the market finished drawing it.
 *
 * <p>Stateless and side-effect free: it reads a candle list and returns events.
 */
@Slf4j
@Component
public class MarketStructureAnalyzer {

    /**
     * Bars required either side of a swing. Two is the usual intraday choice —
     * one is noise, three lags badly across a 75-bar session.
     *
     * <p>A <i>measurement</i> parameter, not a trading rule: nothing here decides
     * when to enter or exit, so it stays a constant rather than a TradeConfig
     * field. If structure ever drives an entry it must move to config
     * (CLAUDE.md invariant 9).
     */
    public static final int DEFAULT_FRACTAL_N = 2;

    public enum Structure { BULLISH, BEARISH, UNDEFINED }

    public enum EventType { BOS, CHOCH }

    /** Which way the break points, before any position is taken into account. */
    public enum Bias { BULLISH, BEARISH }

    /** Series a structure reading was taken on. */
    public static final String SERIES_UNDERLYING = "UNDERLYING";
    public static final String SERIES_OPTION = "OPTION";

    /**
     * One structure break.
     *
     * @param occurredAt    close of the bar that broke the level
     * @param confirmableAt earliest bar at which the broken swing was itself
     *                      confirmed; never earlier than {@code occurredAt}
     * @param level         the swing price that was broken
     */
    public record StructureEvent(
            EventType type,
            Bias bias,
            LocalDateTime occurredAt,
            LocalDateTime confirmableAt,
            BigDecimal level,
            Structure structureBefore,
            Structure structureAfter
    ) {
        /** True when this break was already knowable at {@code asOf}. */
        public boolean isConfirmedBy(LocalDateTime asOf) {
            return asOf != null && !confirmableAt.isAfter(asOf);
        }
    }

    private record Swing(int index, LocalDateTime time, BigDecimal price, boolean high,
                         LocalDateTime confirmedAt) {
    }

    public List<StructureEvent> analyze(List<MarketData> candles) {
        return analyze(candles, DEFAULT_FRACTAL_N);
    }

    /**
     * Walks the series once, emitting an event for every BOS and CHoCH. Returns
     * empty for a series too short to contain a confirmable swing.
     */
    public List<StructureEvent> analyze(List<MarketData> candles, int fractalN) {
        List<StructureEvent> events = new ArrayList<>();
        if (candles == null || fractalN < 1 || candles.size() < (2 * fractalN + 2)) {
            return events;
        }

        List<Swing> swings = detectSwings(candles, fractalN);
        if (swings.isEmpty()) {
            return events;
        }

        Structure structure = Structure.UNDEFINED;
        Swing lastHigh = null;
        Swing lastLow = null;
        int nextSwing = 0;

        for (int i = 0; i < candles.size(); i++) {
            MarketData bar = candles.get(i);
            if (bar == null || bar.getClose() == null || bar.getTimestamp() == null) {
                continue;
            }

            // Promote every swing whose confirmation bar we have now reached.
            // Done before the break test, so a level only becomes usable from the
            // bar it became knowable on — never earlier.
            while (nextSwing < swings.size() && swings.get(nextSwing).index() + fractalN <= i) {
                Swing s = swings.get(nextSwing++);
                if (s.high()) {
                    lastHigh = s;
                } else {
                    lastLow = s;
                }
            }

            BigDecimal close = bar.getClose();

            if (lastHigh != null && close.compareTo(lastHigh.price()) > 0) {
                boolean choch = structure == Structure.BEARISH;
                events.add(new StructureEvent(
                        choch ? EventType.CHOCH : EventType.BOS,
                        Bias.BULLISH,
                        bar.getTimestamp(),
                        maxOf(bar.getTimestamp(), lastHigh.confirmedAt()),
                        lastHigh.price(),
                        structure, Structure.BULLISH));
                structure = Structure.BULLISH;
                // Consumed: a level once broken cannot break again.
                lastHigh = null;
            } else if (lastLow != null && close.compareTo(lastLow.price()) < 0) {
                boolean choch = structure == Structure.BULLISH;
                events.add(new StructureEvent(
                        choch ? EventType.CHOCH : EventType.BOS,
                        Bias.BEARISH,
                        bar.getTimestamp(),
                        maxOf(bar.getTimestamp(), lastLow.confirmedAt()),
                        lastLow.price(),
                        structure, Structure.BEARISH));
                structure = Structure.BEARISH;
                lastLow = null;
            }
        }
        return events;
    }

    /**
     * Fractal swings. Bar {@code i} is a swing high when its high exceeds every
     * high in {@code [i-n, i+n]} — strict on both sides, so a flat run does not
     * emit a cluster of swings at one price.
     */
    private List<Swing> detectSwings(List<MarketData> candles, int n) {
        List<Swing> swings = new ArrayList<>();
        for (int i = n; i < candles.size() - n; i++) {
            MarketData c = candles.get(i);
            if (c == null || c.getHigh() == null || c.getLow() == null || c.getTimestamp() == null) {
                continue;
            }
            boolean isHigh = true;
            boolean isLow = true;
            for (int j = i - n; j <= i + n; j++) {
                if (j == i) {
                    continue;
                }
                MarketData o = candles.get(j);
                if (o == null || o.getHigh() == null || o.getLow() == null) {
                    isHigh = false;
                    isLow = false;
                    break;
                }
                if (o.getHigh().compareTo(c.getHigh()) >= 0) {
                    isHigh = false;
                }
                if (o.getLow().compareTo(c.getLow()) <= 0) {
                    isLow = false;
                }
                if (!isHigh && !isLow) {
                    break;
                }
            }
            MarketData confirmBar = candles.get(i + n);
            if (confirmBar == null || confirmBar.getTimestamp() == null) {
                continue;
            }
            LocalDateTime confirmedAt = confirmBar.getTimestamp();
            if (isHigh) {
                swings.add(new Swing(i, c.getTimestamp(), c.getHigh(), true, confirmedAt));
            }
            if (isLow) {
                swings.add(new Swing(i, c.getTimestamp(), c.getLow(), false, confirmedAt));
            }
        }
        return swings;
    }

    private static LocalDateTime maxOf(LocalDateTime a, LocalDateTime b) {
        if (a == null) return b;
        if (b == null) return a;
        return a.isAfter(b) ? a : b;
    }

    /**
     * Whether a break helps or hurts an open position: {@code WITH} or
     * {@code AGAINST}.
     *
     * <p>This is what makes structure comparable across CE and PE trades. A raw
     * "bullish CHoCH" means opposite things to a short call and a short put, so
     * the fact worth recording is the relationship to the position, not the
     * direction on the chart.
     *
     * @param series      {@link #SERIES_UNDERLYING} or {@link #SERIES_OPTION}
     * @param optionType  {@code CE} or {@code PE}
     * @param entryIsSell true for a short-premium position
     */
    public String directionFor(String series, Bias bias, String optionType, boolean entryIsSell) {
        boolean bullish = bias == Bias.BULLISH;

        // On the option's own premium the answer is unambiguous: a seller is hurt
        // when the premium rises, whichever leg it is.
        if (SERIES_OPTION.equalsIgnoreCase(series)) {
            return (bullish == entryIsSell) ? "AGAINST" : "WITH";
        }

        // On the underlying it depends on the leg: a rising index hurts a short
        // call and helps a short put.
        boolean isCall = "CE".equalsIgnoreCase(optionType);
        boolean hurts = entryIsSell == (bullish == isCall);
        return hurts ? "AGAINST" : "WITH";
    }
}
