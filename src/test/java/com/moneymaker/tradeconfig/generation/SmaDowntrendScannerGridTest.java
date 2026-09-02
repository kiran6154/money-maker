package com.moneymaker.tradeconfig.generation;

import com.moneymaker.entity.SmaDowntrendRule;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Grid resolution — the part of the scanner changeset 039 made data-driven,
 * and the part hand-edited SQL can break.
 *
 * <p>The contract: a rule's {@code sma_periods} / {@code timeframes_minutes}
 * select from the supported grid; blank means the old hardcoded defaults, so a
 * pre-039 database behaves unchanged; an unsupported period is dropped loudly
 * rather than trend-tested against a flag that can never be set.</p>
 */
class SmaDowntrendScannerGridTest {

    private SmaDowntrendScanner scanner;

    @BeforeEach
    void setUp() {
        // Grid resolution never touches the data or indicator collaborators
        // (and IndicatorService is final, so Mockito could not mock it anyway).
        scanner = new SmaDowntrendScanner(null, null);
    }

    private static SmaDowntrendRule rule(String smaPeriods, String timeframes) {
        SmaDowntrendRule r = new SmaDowntrendRule();
        r.setId(1);
        r.setSmaPeriods(smaPeriods);
        r.setTimeframesMinutes(timeframes);
        return r;
    }

    @Test
    @DisplayName("blank columns fall back to the old hardcoded grid — pre-039 rows behave unchanged")
    void blankColumnsUseDefaults() {
        SmaDowntrendRule r = rule(null, null);
        assertThat(scanner.usablePeriods(r)).containsExactly(50, 100, 200, 500);
        assertThat(scanner.timeframes(r)).containsExactly(5, 15);
    }

    @Test
    @DisplayName("a rule can skip periods and timeframes")
    void subsetSelected() {
        SmaDowntrendRule r = rule("50,100", "5");
        assertThat(scanner.usablePeriods(r)).containsExactly(50, 100);
        assertThat(scanner.timeframes(r)).containsExactly(5);
    }

    @Test
    @DisplayName("SMA-20 is selectable for detection — MarketData carries its flag")
    void sma20Selectable() {
        assertThat(scanner.usablePeriods(rule("20,50", null))).containsExactly(20, 50);
    }

    @Test
    @DisplayName("an unsupported period is dropped, the rest of the grid survives")
    void unsupportedPeriodDropped() {
        // 60 has no MarketData trend flag — trend-testing it could only ever
        // return false silently, so it must not stay in the grid.
        assertThat(scanner.usablePeriods(rule("50,60,200", null))).containsExactly(50, 200);
    }

    @Test
    @DisplayName("a grid of only unsupported periods scans nothing rather than reverting to defaults")
    void allUnsupportedScansNothing() {
        // The user explicitly chose periods; silently substituting the default
        // grid would run a scan they did not ask for. The empty grid is loud in
        // the log and generates nothing.
        assertThat(scanner.usablePeriods(rule("60,75", null))).isEmpty();
    }

    @Test
    @DisplayName("hand-typed spacing and duplicates are tolerated")
    void lenientParsing() {
        SmaDowntrendRule r = rule(" 200 , 50 , 50 ", " 15 , 5 ,");
        assertThat(scanner.usablePeriods(r)).containsExactly(50, 200);
        assertThat(scanner.timeframes(r)).containsExactly(5, 15);
    }
}
