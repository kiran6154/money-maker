package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.IndexSymbol;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Pins {@link ChartStrikeLadder} — the exchange's strike grid, now shared by the
 * ATM rounding and the averaged-pane ladders in both chart services.
 *
 * <p>Sharing is the point: an ATM rounded on a 50-point grid with a ladder
 * stepped by 100 would centre the average somewhere the underlying never was.
 * These tests are what keeps the two readings of "one strike" identical.</p>
 */
class ChartStrikeLadderTest {

    @Test
    @DisplayName("the step is the index's own listed grid")
    void stepPerIndex() {
        assertThat(ChartStrikeLadder.stepFor(IndexSymbol.NIFTY)).isEqualTo(50);
        assertThat(ChartStrikeLadder.stepFor(IndexSymbol.BANKNIFTY)).isEqualTo(100);
    }

    @Test
    @DisplayName("ATM rounds to the nearest listed strike")
    void atmRoundsToNearest() {
        assertThat(ChartStrikeLadder.atmStrike(IndexSymbol.NIFTY, new BigDecimal("24473.15")))
                .isEqualByComparingTo("24450");
        assertThat(ChartStrikeLadder.atmStrike(IndexSymbol.NIFTY, new BigDecimal("24476.00")))
                .isEqualByComparingTo("24500");
        assertThat(ChartStrikeLadder.atmStrike(IndexSymbol.BANKNIFTY, new BigDecimal("51949.90")))
                .isEqualByComparingTo("51900");
    }

    @Test
    @DisplayName("span 0 is the single strike — the ordinary chart needs no special case")
    void spanZeroIsTheStrikeItself() {
        assertThat(ChartStrikeLadder.around(IndexSymbol.NIFTY, new BigDecimal("24500"), 0))
                .containsExactly(new BigDecimal("24500"));
    }

    @Test
    @DisplayName("span 1 is ATM-1, ATM, ATM+1 on the index's grid")
    void spanOneStraddlesByOneStep() {
        List<BigDecimal> ladder =
                ChartStrikeLadder.around(IndexSymbol.NIFTY, new BigDecimal("24500"), 1);

        assertThat(ladder).hasSize(3);
        assertThat(ladder.get(0)).isEqualByComparingTo("24450");
        assertThat(ladder.get(1)).isEqualByComparingTo("24500");
        assertThat(ladder.get(2)).isEqualByComparingTo("24550");
    }

    @Test
    @DisplayName("span 2 widens to five legs, still symmetric about the centre")
    void spanTwoIsFiveLegs() {
        // Symmetry is what makes one series read the same for a CE and a PE:
        // whichever right is charted, the same count of legs sits ITM and OTM.
        List<BigDecimal> ladder =
                ChartStrikeLadder.around(IndexSymbol.BANKNIFTY, new BigDecimal("52000"), 2);

        assertThat(ladder).hasSize(5);
        assertThat(ladder.get(0)).isEqualByComparingTo("51800");
        assertThat(ladder.get(2)).isEqualByComparingTo("52000");
        assertThat(ladder.get(4)).isEqualByComparingTo("52200");
    }

    @Test
    @DisplayName("legs at or below zero are dropped, not requested")
    void skipsNonPositiveStrikes() {
        // Only reachable with junk input, but a strike of 0 or -50 is not a
        // contract the DB should be asked about.
        List<BigDecimal> ladder =
                ChartStrikeLadder.around(IndexSymbol.NIFTY, new BigDecimal("50"), 2);

        assertThat(ladder).allSatisfy(strike -> assertThat(strike.signum()).isPositive());
        assertThat(ladder).hasSize(3);
    }

    @Test
    @DisplayName("a null centre yields no ladder at all")
    void nullCentreYieldsEmpty() {
        assertThat(ChartStrikeLadder.around(IndexSymbol.NIFTY, null, 2)).isEmpty();
        assertThat(ChartStrikeLadder.around(IndexSymbol.NIFTY, null, 0)).isEmpty();
    }
}
