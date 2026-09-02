package com.moneymaker.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The one owner of the {@code sma_downtrend_rule} grid columns' encoding
 * (changeset 039). Hand-edited SQL is the expected writer, so leniency is the
 * contract, not a convenience.
 */
class IntCsvTest {

    @Test
    @DisplayName("parses ascending and de-duplicated, whatever the input order")
    void ascendingDistinct() {
        assertThat(IntCsv.parse("15,5,15")).containsExactly(5, 15);
        assertThat(IntCsv.parse("500,50,200,100")).containsExactly(50, 100, 200, 500);
    }

    @Test
    @DisplayName("lenient about whitespace and stray separators")
    void lenient() {
        assertThat(IntCsv.parse(" 15 , 5 ,")).containsExactly(5, 15);
        assertThat(IntCsv.parse(",,5")).containsExactly(5);
    }

    @Test
    @DisplayName("a malformed fragment is skipped, not fatal")
    void malformedFragmentSkipped() {
        assertThat(IntCsv.parse("50,abc,100")).containsExactly(50, 100);
    }

    @Test
    @DisplayName("non-positive values are dropped — a period or timeframe of 0 is meaningless")
    void nonPositiveDropped() {
        assertThat(IntCsv.parse("0,-5,50")).containsExactly(50);
    }

    @Test
    @DisplayName("blank and null yield empty, which callers read as 'use the default grid'")
    void blankYieldsEmpty() {
        assertThat(IntCsv.parse(null)).isEmpty();
        assertThat(IntCsv.parse("  ")).isEmpty();
    }
}
