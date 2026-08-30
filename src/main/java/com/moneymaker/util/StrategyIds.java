package com.moneymaker.util;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

/**
 * The only place {@code trade_config.strategy_ids} is split or joined.
 *
 * <p>The column holds ascending strategy ids as a comma-separated string
 * ({@code "1"}, {@code "1,2"}) — see changeset 035, which replaced the
 * {@code trade_config_strategy} child table with it. Keeping the encoding behind
 * these two methods is what makes that trade safe: a CSV column is only as sound
 * as the discipline that nothing else calls {@code split(",")} on it and invents
 * its own whitespace, ordering or duplicate rules.</p>
 *
 * <p><b>Do not parse this column anywhere else.</b></p>
 */
public final class StrategyIds {

    private StrategyIds() {
    }

    /**
     * Parses the column into ascending, de-duplicated strategy ids.
     *
     * <p>Lenient about whitespace and stray separators, because this column is
     * edited by hand in SQL — {@code " 2 , 1 ,"} is a realistic thing to type and
     * means the same as {@code "1,2"}. Non-numeric fragments are skipped rather
     * than throwing: one typo must not stop the whole day's configs from loading.
     * A blank or null column yields an empty list, which callers read as "no tags"
     * and resolve to the config's primary strategy.</p>
     *
     * <p>Ascending order is not cosmetic — it fixes the sequence in which
     * strategies are dispatched and, in the EOD detector, the order generated
     * configs are written, so a replayed backtest day behaves identically.</p>
     */
    public static List<Integer> parse(String csv) {
        if (csv == null || csv.isBlank()) return List.of();
        Set<Integer> ids = new TreeSet<>();
        for (String part : csv.split(",")) {
            String trimmed = part.trim();
            if (trimmed.isEmpty()) continue;
            try {
                ids.add(Integer.valueOf(trimmed));
            } catch (NumberFormatException ex) {
                // Skip the fragment, keep the rest. A malformed id is a config
                // mistake; losing every other strategy on the row would turn it
                // into an outage.
            }
        }
        return new ArrayList<>(ids);
    }

    /**
     * Renders ids to the column's canonical form: ascending, de-duplicated,
     * comma-separated, no spaces. Returns {@code null} for an empty collection so
     * the column stays NULL rather than holding an empty string — the loader
     * treats both as "no tags", but only one of them reads that way in a query.
     */
    public static String format(Collection<Integer> ids) {
        if (ids == null || ids.isEmpty()) return null;
        Set<Integer> sorted = new TreeSet<>();
        for (Integer id : ids) {
            if (id != null) sorted.add(id);
        }
        if (sorted.isEmpty()) return null;
        StringBuilder sb = new StringBuilder();
        for (Integer id : sorted) {
            if (sb.length() > 0) sb.append(',');
            sb.append(id);
        }
        return sb.toString();
    }

    /**
     * Convenience for the common edit: add one id to an existing column value and
     * return the new canonical string. Adding an id already present is a no-op.
     */
    public static String with(String csv, Integer id) {
        Set<Integer> ids = new LinkedHashSet<>(parse(csv));
        if (id != null) ids.add(id);
        return format(ids);
    }

    /** Convenience for removing one id from an existing column value. */
    public static String without(String csv, Integer id) {
        Set<Integer> ids = new LinkedHashSet<>(parse(csv));
        ids.remove(id);
        return format(ids);
    }
}
