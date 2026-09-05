package com.moneymaker.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Pins {@link BracketMode}, the sole owner of the
 * {@code strategy_defaults.target_mode} / {@code sl_mode} columns (changeset 041).
 *
 * <p>The default matters more than the parsing here: {@code PERCENT} is what
 * makes 041 behaviour-neutral on an existing database, so a change that made
 * a missing value mean anything else would silently move every ledger.</p>
 */
class BracketModeTest {

    @Test
    @DisplayName("a missing mode reads as PERCENT — the pre-041 rule")
    void nullIsPercent() {
        // This is the behaviour-neutrality guarantee. Strategies with no
        // strategy_defaults row at all (033 seeded only strategy 1) land here.
        assertThat(BracketMode.parse(null)).isEqualTo(BracketMode.PERCENT);
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "   ", "\t"})
    @DisplayName("a blank mode reads as PERCENT too")
    void blankIsPercent(String raw) {
        assertThat(BracketMode.parse(raw)).isEqualTo(BracketMode.PERCENT);
    }

    @ParameterizedTest
    @ValueSource(strings = {"POINTS", "points", "  Points  "})
    @DisplayName("POINTS parses case- and whitespace-insensitively")
    void pointsParses(String raw) {
        assertThat(BracketMode.parse(raw)).isEqualTo(BracketMode.POINTS);
    }

    @ParameterizedTest
    @ValueSource(strings = {"PERCENT", "percent", " PerCent "})
    @DisplayName("PERCENT parses case- and whitespace-insensitively")
    void percentParses(String raw) {
        assertThat(BracketMode.parse(raw)).isEqualTo(BracketMode.PERCENT);
    }

    @ParameterizedTest
    @ValueSource(strings = {"POINT", "PCT", "%", "PERCENTAGE", "ABSOLUTE"})
    @DisplayName("a near-miss throws rather than defaulting silently")
    void unknownThrows(String raw) {
        // A typo must be visible somewhere. The Strategy bracket panel turns it
        // into a rejected save (StrategyDefaultsAdminService lets it through),
        // while OrderService logs it and carries on; swallowing it here would
        // mean a hand-edited "POINT" quietly kept trading the percentage
        // bracket forever.
        assertThatThrownBy(() -> BracketMode.parse(raw))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining(raw)
                .hasMessageContaining("POINTS or PERCENT");
    }
}
