package com.moneymaker.indicator.series;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Pins the reference formula for the Pressure score's third term.
 *
 * <p><b>Why this file is worth more than it looks.</b> The Pressure spec calls
 * this term "Session VWAP". Taking that literally cost a whole invalid backtest:
 * NIFTY spot carries no volume, so an earlier implementation invented a
 * front-weekly option-volume weight to satisfy the word — producing a different
 * indicator, and therefore a different trade set, while every log line and
 * summary table still looked entirely reasonable. The strategy's author later
 * confirmed (2026-09-05) that the reference used no volume at all.</p>
 *
 * <p>So the first test below is not a formality. It is the assertion that this
 * term is an unweighted mean, and it should fail loudly if anyone "fixes" the
 * naming by reintroducing a weight.</p>
 */
class SessionAnchoredPriceTest {

    @Test
    @DisplayName("the default is an UNWEIGHTED expanding mean of typical price")
    void defaultIsUnweightedExpandingMean() {
        // typical prices for four bars
        double[] tp = {100, 110, 120, 130};

        double[] anchor = SessionAnchoredPrice.compute(tp);

        assertThat(anchor[0]).isCloseTo(100, within(1e-9));                 // 100
        assertThat(anchor[1]).isCloseTo(105, within(1e-9));                 // (100+110)/2
        assertThat(anchor[2]).isCloseTo(110, within(1e-9));                 // (100+110+120)/3
        assertThat(anchor[3]).isCloseTo(115, within(1e-9));                 // (…+130)/4
    }

    @Test
    @DisplayName("typical price is (H+L+C)/3, the convention the spec names")
    void typicalPriceConvention() {
        com.moneymaker.entity.MarketData bar = new com.moneymaker.entity.MarketData();
        bar.setHigh(new java.math.BigDecimal("120"));
        bar.setLow(new java.math.BigDecimal("90"));
        bar.setClose(new java.math.BigDecimal("105"));
        bar.setOpen(new java.math.BigDecimal("100"));
        bar.setTimestamp(java.time.LocalDateTime.of(2024, 1, 2, 9, 15));

        double[] tp = Bars.typicalPrices(java.util.List.of(bar));

        // (120 + 90 + 105) / 3 = 105. Note OPEN is deliberately not part of it.
        assertThat(tp[0]).isCloseTo(105, within(1e-9));
    }

    @Test
    @DisplayName("passing weights changes the answer — which is why the default must not")
    void weightsChangeTheResult() {
        double[] tp = {100, 200};

        double[] plain = SessionAnchoredPrice.compute(tp);
        double[] weighted = SessionAnchoredPrice.compute(tp, new double[]{1, 9});

        assertThat(plain[1]).isCloseTo(150, within(1e-9));            // (100+200)/2
        assertThat(weighted[1]).isCloseTo(190, within(1e-9));         // (100*1 + 200*9)/10

        // 40 points apart on two bars. Across a session this is a different
        // indicator, not a refinement of the same one — which is the whole
        // reason OPTION_TAPE_VWAP is opt-in and the reference book would need
        // re-marking before its figures could be compared against it.
        assertThat(Math.abs(plain[1] - weighted[1])).isGreaterThan(1);
    }

    @Test
    @DisplayName("a zero or missing weight falls back to the unweighted mean, it does not drop the bar")
    void degenerateWeightsFallBack() {
        double[] tp = {100, 110, 120};

        // All-zero weights must behave exactly like no weights at all. Dropping
        // the bars instead would silently shorten the session and shift the
        // anchor for every later bar.
        assertThat(SessionAnchoredPrice.compute(tp, new double[]{0, 0, 0}))
                .containsExactly(SessionAnchoredPrice.compute(tp), within(1e-9));

        assertThat(SessionAnchoredPrice.compute(tp, new double[]{Bars.NA, Bars.NA, Bars.NA}))
                .containsExactly(SessionAnchoredPrice.compute(tp), within(1e-9));
    }

    @Test
    @DisplayName("an unusable bar carries the previous anchor rather than blanking it")
    void naBarCarriesPreviousValue() {
        double[] tp = {100, Bars.NA, 120};

        double[] anchor = SessionAnchoredPrice.compute(tp);

        assertThat(anchor[0]).isCloseTo(100, within(1e-9));
        // Carried, not NA: PressureScore reads NA as "this term does not score",
        // so blanking here would silently drop a point for the rest of the bar.
        assertThat(anchor[1]).isCloseTo(100, within(1e-9));
        assertThat(anchor[2]).isCloseTo(110, within(1e-9));           // (100+120)/2
    }

    @Test
    @DisplayName("the anchor resets per session — it is built from session bars only")
    void resetsPerSession() {
        // SpotFeatures passes only today's session bars, so "reset" is a
        // property of the caller rather than of this function. Asserted here so
        // the contract is written down where the formula lives: given one
        // session's bars, the first value is that session's first typical price
        // and nothing before it leaks in.
        double[] day2 = {500, 520};
        assertThat(SessionAnchoredPrice.compute(day2)[0]).isCloseTo(500, within(1e-9));
    }
}
