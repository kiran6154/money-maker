package com.moneymaker.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * A comma-separated column is only as sound as the one class that owns its
 * encoding. These pin that contract: ascending, de-duplicated, whitespace-tolerant,
 * and never throwing on input a human typed into a SQL client.
 *
 * <p>{@code trade_config.strategy_ids} decides which strategies scan a config, so
 * a parsing slip here does not corrupt data — it silently stops a strategy from
 * trading, or starts one that should not.</p>
 */
class StrategyIdsTest {

    @Test
    @DisplayName("parses the canonical form")
    void parsesCanonical() {
        assertThat(StrategyIds.parse("1,2")).containsExactly(1, 2);
        assertThat(StrategyIds.parse("1")).containsExactly(1);
    }

    @Test
    @DisplayName("blank and null mean no tags, not an error")
    void blankMeansNoTags() {
        // Callers read empty as "fall back to stratergy_id", so this must not throw
        // and must not yield a list containing null.
        assertThat(StrategyIds.parse(null)).isEmpty();
        assertThat(StrategyIds.parse("")).isEmpty();
        assertThat(StrategyIds.parse("   ")).isEmpty();
    }

    @Test
    @DisplayName("tolerates whitespace and stray separators typed by hand")
    void tolerantOfHandEditing() {
        assertThat(StrategyIds.parse(" 2 , 1 ,")).containsExactly(1, 2);
        assertThat(StrategyIds.parse(",,1,,2,,")).containsExactly(1, 2);
    }

    @Test
    @DisplayName("sorts ascending and de-duplicates")
    void sortsAndDeduplicates() {
        // Order fixes the dispatch sequence, so a replayed backtest behaves the same.
        assertThat(StrategyIds.parse("2,1,2")).containsExactly(1, 2);
    }

    @Test
    @DisplayName("a malformed fragment is skipped, the rest survive")
    void malformedFragmentDoesNotLoseTheRow() {
        // One typo must not stop the whole day's configs from loading.
        assertThat(StrategyIds.parse("1,abc,2")).containsExactly(1, 2);
        assertThat(StrategyIds.parse("abc")).isEmpty();
    }

    @Test
    @DisplayName("format produces the canonical string")
    void formatsCanonically() {
        assertThat(StrategyIds.format(List.of(2, 1, 2))).isEqualTo("1,2");
        assertThat(StrategyIds.format(List.of(1))).isEqualTo("1");
    }

    @Test
    @DisplayName("format yields null for nothing, so the column stays NULL")
    void formatsEmptyAsNull() {
        // Not "" — both read as "no tags", but only NULL reads that way in SQL.
        assertThat(StrategyIds.format(List.of())).isNull();
        assertThat(StrategyIds.format(null)).isNull();
    }

    @Test
    @DisplayName("parse and format round-trip")
    void roundTrips() {
        assertThat(StrategyIds.format(StrategyIds.parse(" 3 ,1,, 2 "))).isEqualTo("1,2,3");
    }

    @Test
    @DisplayName("with() adds an id idempotently")
    void withAddsIdempotently() {
        assertThat(StrategyIds.with("1", 2)).isEqualTo("1,2");
        assertThat(StrategyIds.with("1,2", 2)).isEqualTo("1,2");
        assertThat(StrategyIds.with(null, 1)).isEqualTo("1");
    }

    @Test
    @DisplayName("without() removes an id and nulls out an emptied column")
    void withoutRemoves() {
        assertThat(StrategyIds.without("1,2", 1)).isEqualTo("2");
        assertThat(StrategyIds.without("1,2", 9)).isEqualTo("1,2");
        assertThat(StrategyIds.without("1", 1)).isNull();
    }
}
