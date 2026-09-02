package com.moneymaker.util;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

/**
 * The only place {@code sma_downtrend_rule.sma_periods} and
 * {@code sma_downtrend_rule.timeframes_minutes} are split or joined
 * (changeset 039).
 *
 * <p>Same discipline as {@link StrategyIds}, and deliberately a separate class
 * rather than a reuse of it: that one owns the {@code strategy_ids} encoding,
 * this one owns the detection-grid columns, and sharing a parser would couple
 * two columns whose rules are allowed to diverge.</p>
 *
 * <p>Lenient about whitespace and stray separators because both columns are
 * edited by hand in SQL — {@code " 15 , 5 ,"} means {@code "5,15"}. Non-numeric
 * fragments and non-positive values are skipped rather than throwing: one typo
 * must not stop the detector loading its rules. Output is ascending and
 * de-duplicated, so a re-run of the same rule walks the grid in the same order.</p>
 *
 * <p><b>Do not parse these columns anywhere else.</b></p>
 */
public final class IntCsv {

    private IntCsv() {
    }

    /**
     * Parses to ascending, de-duplicated, strictly positive ints. Blank or null
     * yields an empty list — callers fall back to their documented default grid,
     * never to "nothing" (disabling a rule is {@code enabled=false}, not a
     * blanked column).
     */
    public static List<Integer> parse(String csv) {
        if (csv == null || csv.isBlank()) return List.of();
        Set<Integer> values = new TreeSet<>();
        for (String part : csv.split(",")) {
            String trimmed = part.trim();
            if (trimmed.isEmpty()) continue;
            try {
                int value = Integer.parseInt(trimmed);
                if (value > 0) values.add(value);
            } catch (NumberFormatException ex) {
                // Skip the fragment, keep the rest — a typo in one period must
                // not cost the rule its whole grid.
            }
        }
        return new ArrayList<>(values);
    }

    /**
     * Renders to the columns' canonical form: ascending, de-duplicated,
     * comma-separated, no spaces. What the rules UI stores, so a hand-typed
     * {@code " 15 , 5 "} round-trips as {@code "5,15"}.
     */
    public static String format(List<Integer> values) {
        if (values == null || values.isEmpty()) return "";
        Set<Integer> sorted = new TreeSet<>();
        for (Integer v : values) {
            if (v != null && v > 0) sorted.add(v);
        }
        StringBuilder sb = new StringBuilder();
        for (Integer v : sorted) {
            if (sb.length() > 0) sb.append(',');
            sb.append(v);
        }
        return sb.toString();
    }
}
