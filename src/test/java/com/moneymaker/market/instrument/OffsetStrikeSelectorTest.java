package com.moneymaker.market.instrument;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Pins the strike arithmetic.
 *
 * <p>An off-by-one-step here is close to undetectable at runtime: every book
 * still trades, every book still shows a plausible P&amp;L, and the only symptom
 * is that ITM300 was quietly ITM250 all year. The three things asserted below —
 * rounding, sign convention per option side, and fallback order — are exactly
 * the three that a reader would otherwise have to take on trust.</p>
 */
class OffsetStrikeSelectorTest {

    // ------------------------------------------------------------------ ATM

    @Test
    @DisplayName("ATM ROUNDS to the nearest step — it does not floor")
    void atmRounds() {
        // The shared AnalysisScheduler path floors. On a 50-point grid that
        // biases every chosen strike down by an average of 25 points, which is
        // systematically less ITM on a CE and more on a PE. The Pressure spec
        // says round, so this rounds, and the two paths stay separate.
        assertThat(OffsetStrikeSelector.atm(22424.85, 50)).isEqualTo(22400);
        assertThat(OffsetStrikeSelector.atm(22425.00, 50)).isEqualTo(22425 / 50 * 50 + 50); // .5 rounds up
        assertThat(OffsetStrikeSelector.atm(22426.00, 50)).isEqualTo(22450);
        assertThat(OffsetStrikeSelector.atm(22400.00, 50)).isEqualTo(22400);

        // The flooring alternative would have produced 22400 for all four.
        assertThat(OffsetStrikeSelector.atm(22449.99, 50))
                .as("just below the midpoint rounds down")
                .isEqualTo(22450);
    }

    @Test
    @DisplayName("ATM honours the step it is given, not a hardcoded 50")
    void atmHonoursStep() {
        assertThat(OffsetStrikeSelector.atm(22424.85, 100)).isEqualTo(22400);
        assertThat(OffsetStrikeSelector.atm(22451.00, 100)).isEqualTo(22500);
    }

    @Test
    @DisplayName("a non-positive step is refused rather than producing a divide-by-zero strike")
    void rejectsBadStep() {
        assertThatThrownBy(() -> OffsetStrikeSelector.atm(22400, 0))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> OffsetStrikeSelector.candidates(22400, "CE", 300, -50))
                .isInstanceOf(IllegalArgumentException.class);
    }

    // --------------------------------------------------------------- offset

    @Test
    @DisplayName("a positive offset is ITM for BOTH sides — which means opposite directions")
    void positiveOffsetIsItmForBothSides() {
        // This is the sign convention the whole thing turns on. "ITM 300" is
        // ATM-300 for a call and ATM+300 for a put; getting it backwards
        // produces a deep OTM leg that still trades and still reports numbers.
        assertThat(OffsetStrikeSelector.exactStrike(22400, "CE", 300)).isEqualTo(22100);
        assertThat(OffsetStrikeSelector.exactStrike(22400, "PE", 300)).isEqualTo(22700);
    }

    @Test
    @DisplayName("offset 0 is ATM on both sides")
    void zeroOffsetIsAtm() {
        assertThat(OffsetStrikeSelector.exactStrike(22400, "CE", 0)).isEqualTo(22400);
        assertThat(OffsetStrikeSelector.exactStrike(22400, "PE", 0)).isEqualTo(22400);
    }

    @Test
    @DisplayName("a negative offset is OTM — the mirror of ITM")
    void negativeOffsetIsOtm() {
        assertThat(OffsetStrikeSelector.exactStrike(22400, "CE", -200)).isEqualTo(22600);
        assertThat(OffsetStrikeSelector.exactStrike(22400, "PE", -200)).isEqualTo(22200);
    }

    @Test
    @DisplayName("side is matched on the leading C, so CE / CALL / ce all read as a call")
    void sideParsingIsForgiving() {
        assertThat(OffsetStrikeSelector.exactStrike(22400, "ce", 300)).isEqualTo(22100);
        assertThat(OffsetStrikeSelector.exactStrike(22400, "CALL", 300)).isEqualTo(22100);
        assertThat(OffsetStrikeSelector.exactStrike(22400, "pe", 300)).isEqualTo(22700);
    }

    // ------------------------------------------------------------ fallback

    @Test
    @DisplayName("candidates lead with the exact strike, then widen one step at a time")
    void candidateOrder() {
        List<Integer> c = OffsetStrikeSelector.candidates(22400, "CE", 300, 50);

        // Exact first. The caller stops at the first with data, so on the dense
        // ladder our 2024 import actually has, this is a single fetch.
        assertThat(c.get(0)).isEqualTo(22100);
        // Then +/-1 step, then +/-2 steps. Lower before higher, uniformly and
        // regardless of side, so the CE and PE books stay comparable.
        assertThat(c).containsExactly(22100, 22050, 22150, 22000, 22200);
    }

    @Test
    @DisplayName("the fallback stops at two steps — it never wanders arbitrarily far")
    void fallbackIsBounded() {
        List<Integer> c = OffsetStrikeSelector.candidates(22400, "PE", 200, 50);
        assertThat(c).hasSize(5);
        assertThat(c.get(0)).isEqualTo(22600);
        // +/-100 is the spec's limit; a strike further away is a different trade,
        // not a substitute for the one that was missing.
        assertThat(c).allSatisfy(s -> assertThat(Math.abs(s - 22600)).isLessThanOrEqualTo(100));
    }

    @Test
    @DisplayName("the three SELL books resolve to three DIFFERENT strikes")
    void booksDoNotCollide() {
        // The regression this guards: all Pressure configs write into one shared
        // strike cache and leave the depth columns null, so their keys differ
        // only in strike. An earlier resolver took the first key with a matching
        // side, and SELL_ITM300 / SELL_ITM200 / SELL_ATM silently traded the same
        // leg — three books that ARE the comparison collapsing into one.
        int atm = OffsetStrikeSelector.atm(22424.85, 50);

        int itm300 = OffsetStrikeSelector.exactStrike(atm, "PE", 300);
        int itm200 = OffsetStrikeSelector.exactStrike(atm, "PE", 200);
        int atmLeg = OffsetStrikeSelector.exactStrike(atm, "PE", 0);

        assertThat(List.of(itm300, itm200, atmLeg))
                .containsExactly(22700, 22600, 22400)
                .doesNotHaveDuplicates();
    }
}
