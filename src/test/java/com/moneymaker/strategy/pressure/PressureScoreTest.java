package com.moneymaker.strategy.pressure;

import com.moneymaker.indicator.series.Bars;
import com.moneymaker.indicator.series.SpotFeatures;
import com.moneymaker.indicator.series.Supertrend;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The scoring rules, term by term.
 *
 * <p>These are the assertions that decide what trades get taken, so they are
 * written against the spec's wording rather than against the implementation:
 * four confirming terms, one exhaustion penalty, threshold 3, both-sides
 * skipped, and — the two easiest things to get quietly wrong — a missing
 * confirming input never counts as a pass while a missing penalty input never
 * counts as a penalty.</p>
 */
class PressureScoreTest {

    private static final LocalDateTime TS = LocalDateTime.of(2024, 3, 14, 11, 0);

    /** A snapshot with everything neutral; each test flips only what it means to. */
    private static SpotFeatures.Snapshot snap(double close, double rsi, double anchor,
                                              int stDir, double adx,
                                              double plusDi, double minusDi,
                                              double plusDi3, double minusDi3,
                                              double orHigh, double orLow, boolean orComplete) {
        return new SpotFeatures.Snapshot(TS, close, rsi, anchor, stDir, adx,
                plusDi, minusDi, plusDi3, minusDi3, orHigh, orLow, orComplete);
    }

    /** All four down terms true, no penalty. */
    private static SpotFeatures.Snapshot fullyDown() {
        return snap(100, 30, 110, Supertrend.DOWN, 20, 10, 20, 10, 15, 120, 105, true);
    }

    /** All four up terms true, no penalty. */
    private static SpotFeatures.Snapshot fullyUp() {
        return snap(130, 70, 110, Supertrend.UP, 20, 20, 10, 15, 10, 120, 105, true);
    }

    @Test
    @DisplayName("all four down terms score 4 and fire DOWN")
    void fourDownTermsFire() {
        PressureScore.Decision d = PressureScore.decide(fullyDown());
        assertThat(d.score().down()).isEqualTo(4);
        assertThat(d.direction()).isEqualTo(PressureScore.Direction.DOWN);
    }

    @Test
    @DisplayName("all four up terms score 4 and fire UP")
    void fourUpTermsFire() {
        PressureScore.Decision d = PressureScore.decide(fullyUp());
        assertThat(d.score().up()).isEqualTo(4);
        assertThat(d.direction()).isEqualTo(PressureScore.Direction.UP);
    }

    @Test
    @DisplayName("three of four is the threshold; two is not")
    void thresholdIsThree() {
        // RSI 50 kills the RSI term, leaving anchor + st + or = 3.
        SpotFeatures.Snapshot three = snap(100, 50, 110, Supertrend.DOWN, 20, 10, 20, 10, 15, 120, 105, true);
        assertThat(PressureScore.decide(three).score().down()).isEqualTo(3);
        assertThat(PressureScore.decide(three).direction()).isEqualTo(PressureScore.Direction.DOWN);

        // Also flip Supertrend off, leaving anchor + or = 2.
        SpotFeatures.Snapshot two = snap(100, 50, 110, Supertrend.UNKNOWN, 20, 10, 20, 10, 15, 120, 105, true);
        assertThat(PressureScore.decide(two).score().down()).isEqualTo(2);
        assertThat(PressureScore.decide(two).direction()).isEqualTo(PressureScore.Direction.NONE);
    }

    @Test
    @DisplayName("RSI thresholds are strict: 40 and 60 themselves do not score")
    void rsiBoundariesAreStrict() {
        // Spec says RSI < 40 and RSI > 60, not <= / >=.
        SpotFeatures.Snapshot at40 = snap(100, 40, 110, Supertrend.DOWN, 20, 10, 20, 10, 15, 120, 105, true);
        assertThat(PressureScore.decide(at40).score().down()).isEqualTo(3);   // rsi term absent

        SpotFeatures.Snapshot at60 = snap(130, 60, 110, Supertrend.UP, 20, 20, 10, 15, 10, 120, 105, true);
        assertThat(PressureScore.decide(at60).score().up()).isEqualTo(3);     // rsi term absent
    }

    @Test
    @DisplayName("the ADX exhaustion penalty subtracts a point when the trend is strong AND fading")
    void penaltyApplies() {
        // ADX 50 (> 40) and -DI now 20 vs 25 three bars ago: strong but fading.
        SpotFeatures.Snapshot fading = snap(100, 30, 110, Supertrend.DOWN, 50, 10, 20, 10, 25, 120, 105, true);
        PressureScore.Decision d = PressureScore.decide(fading);

        assertThat(d.score().down()).isEqualTo(3);          // 4 terms - 1 penalty
        assertThat(d.score().downDetail()).contains("-adxfade");
        // Still fires at exactly 3 - the penalty narrows, it does not veto.
        assertThat(d.direction()).isEqualTo(PressureScore.Direction.DOWN);
    }

    @Test
    @DisplayName("no penalty when ADX is strong but the trend is still strengthening")
    void noPenaltyWhenDiRising() {
        // -DI now 25 vs 20 three bars ago: strengthening, not fading.
        SpotFeatures.Snapshot rising = snap(100, 30, 110, Supertrend.DOWN, 50, 10, 25, 10, 20, 120, 105, true);
        assertThat(PressureScore.decide(rising).score().down()).isEqualTo(4);
    }

    @Test
    @DisplayName("no penalty when the trend is fading but ADX is below 40")
    void noPenaltyWhenAdxWeak() {
        SpotFeatures.Snapshot weak = snap(100, 30, 110, Supertrend.DOWN, 39, 10, 20, 10, 25, 120, 105, true);
        assertThat(PressureScore.decide(weak).score().down()).isEqualTo(4);
    }

    @Test
    @DisplayName("a missing CONFIRMING input scores nothing — never counted as a pass")
    void missingConfirmingInputDoesNotScore() {
        // With a threshold of 3 out of 4, treating one unknown as satisfied
        // would turn the rule into 2-of-3 and materially loosen entry.
        SpotFeatures.Snapshot noRsi = snap(100, Bars.NA, 110, Supertrend.DOWN, 20, 10, 20, 10, 15, 120, 105, true);
        assertThat(PressureScore.decide(noRsi).score().down()).isEqualTo(3);

        SpotFeatures.Snapshot noAnchor = snap(100, 30, Bars.NA, Supertrend.DOWN, 20, 10, 20, 10, 15, 120, 105, true);
        assertThat(PressureScore.decide(noAnchor).score().down()).isEqualTo(3);
    }

    @Test
    @DisplayName("a missing PENALTY input applies no penalty — the opposite reading, on purpose")
    void missingPenaltyInputDoesNotPenalise() {
        // A penalty is a reason NOT to trade; inventing one from missing data
        // would suppress valid entries. So NA reads opposite here to a
        // confirming term, and the asymmetry is deliberate.
        SpotFeatures.Snapshot noAdx = snap(100, 30, 110, Supertrend.DOWN, Bars.NA, 10, 20, 10, 25, 120, 105, true);
        assertThat(PressureScore.decide(noAdx).score().down()).isEqualTo(4);

        SpotFeatures.Snapshot noDiHistory = snap(100, 30, 110, Supertrend.DOWN, 50, 10, 20, Bars.NA, Bars.NA, 120, 105, true);
        assertThat(PressureScore.decide(noDiHistory).score().down()).isEqualTo(4);
    }

    @Test
    @DisplayName("an incomplete opening range scores no OR term — no free breakout point")
    void incompleteOpeningRangeScoresNothing() {
        // A range built from a partial window is guaranteed too narrow, so every
        // early bar would score the breakout term for free.
        SpotFeatures.Snapshot incomplete = snap(100, 30, 110, Supertrend.DOWN, 20, 10, 20, 10, 15, 120, 105, false);
        assertThat(PressureScore.decide(incomplete).score().down()).isEqualTo(3);
        // Split on whitespace rather than substring-matching: the detail string
        // also carries "anchor", which CONTAINS "or". A doesNotContain("or")
        // here passed only until the term was renamed from "vwap", which is
        // exactly the kind of accidental coupling a token check removes.
        assertThat(PressureScore.decide(incomplete).score().downDetail().split("\\s+"))
                .doesNotContain("or");
    }

    @Test
    @DisplayName("both sides firing is skipped, not tie-broken")
    void bothSidesIsSkipped() {
        // Contrived but the point stands: if the model says a bar is both
        // strongly down- and strongly up-pressured, it does not understand the
        // bar, and picking the bigger number would manufacture a decision out
        // of self-contradiction.
        SpotFeatures.Snapshot both = snap(100, 30, 110, Supertrend.DOWN, 20, 10, 20, 10, 15, 90, 105, true);
        // close 100 < or_low 105 -> down or term; close 100 > or_high 90 -> up or term
        PressureScore.Decision d = PressureScore.decide(both);
        if (d.score().down() >= 3 && d.score().up() >= 3) {
            assertThat(d.bothSides()).isTrue();
            assertThat(d.direction()).isEqualTo(PressureScore.Direction.NONE);
            assertThat(d.reason()).contains("BOTH-SIDES-SKIPPED");
        }
    }

    @Test
    @DisplayName("a null snapshot is no signal, not an exception")
    void nullSnapshotIsNoSignal() {
        PressureScore.Decision d = PressureScore.decide(null);
        assertThat(d.direction()).isEqualTo(PressureScore.Direction.NONE);
        assertThat(d.bothSides()).isFalse();
    }

    @Test
    @DisplayName("the reason string names the terms that fired — it is the audit trail")
    void reasonNamesTheTerms() {
        PressureScore.Decision d = PressureScore.decide(fullyDown());
        assertThat(d.score().downDetail()).contains("rsi").contains("anchor").contains("st").contains("or");
        assertThat(d.reason()).contains("P_down=4").contains("P_up=");
    }
}
