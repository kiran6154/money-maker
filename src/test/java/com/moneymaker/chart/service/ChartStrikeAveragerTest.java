package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Pins {@link ChartStrikeAverager}, which backs the dashboard's ATM±1 / ATM±2
 * panes.
 *
 * <p>The all-legs rule is the load-bearing behaviour here. Averaging whichever
 * legs happen to be present would keep the series unbroken while silently
 * changing what a bar means — the mean of five premiums sits well below the mean
 * of the three innermost — and an SMA dragged through that step reads as a
 * crossover the market never printed.</p>
 */
class ChartStrikeAveragerTest {

    private final ChartStrikeAverager averager = new ChartStrikeAverager();

    private static final OffsetDateTime T0 =
            OffsetDateTime.of(2024, 6, 6, 9, 15, 0, 0, ZoneOffset.ofHoursMinutes(5, 30));
    private static final OffsetDateTime T1 = T0.plusMinutes(5);
    private static final OffsetDateTime T2 = T0.plusMinutes(10);

    private static ChartCandleResponse candle(OffsetDateTime time,
                                              String open, String high, String low, String close) {
        return ChartCandleResponse.ohlc(time,
                new BigDecimal(open), new BigDecimal(high),
                new BigDecimal(low), new BigDecimal(close));
    }

    @Test
    @DisplayName("averages every OHLC component across the legs, bar for bar")
    void averagesEachComponent() {
        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(candle(T0, "100", "110", "90", "105")),
                List.of(candle(T0, "200", "210", "190", "205")),
                List.of(candle(T0, "300", "310", "290", "315"))
        ));

        assertThat(result).hasSize(1);
        ChartCandleResponse bar = result.get(0);
        assertThat(bar.getTime()).isEqualTo(T0);
        assertThat(bar.getOpen()).isEqualByComparingTo("200");
        assertThat(bar.getHigh()).isEqualByComparingTo("210");
        assertThat(bar.getLow()).isEqualByComparingTo("190");
        // Deliberately not the mean of open/high/low: close is averaged in its
        // own right, so a leg that closed above its neighbours still shows.
        assertThat(bar.getClose()).isEqualByComparingTo("208.3333");
    }

    @Test
    @DisplayName("the synthetic bar is always a valid candle")
    void resultIsAValidCandle() {
        // Each leg satisfies low <= open,close <= high, and the mean preserves
        // every one of those inequalities — so the pane can never render an
        // inverted bar however far apart the legs' premiums are.
        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(candle(T0, "12.5", "80", "11", "79")),
                List.of(candle(T0, "300", "301", "120", "121"))
        ));

        ChartCandleResponse bar = result.get(0);
        assertThat(bar.getLow()).isLessThanOrEqualTo(bar.getOpen());
        assertThat(bar.getLow()).isLessThanOrEqualTo(bar.getClose());
        assertThat(bar.getHigh()).isGreaterThanOrEqualTo(bar.getOpen());
        assertThat(bar.getHigh()).isGreaterThanOrEqualTo(bar.getClose());
    }

    @Test
    @DisplayName("a timestamp missing from any leg is dropped, not averaged short")
    void dropsBarsMissingALeg() {
        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(candle(T0, "100", "100", "100", "100"),
                        candle(T1, "100", "100", "100", "100"),
                        candle(T2, "100", "100", "100", "100")),
                // The outer strike did not trade at T1.
                List.of(candle(T0, "200", "200", "200", "200"),
                        candle(T2, "200", "200", "200", "200"))
        ));

        assertThat(result).extracting(ChartCandleResponse::getTime)
                .containsExactly(T0, T2);
        // Every surviving bar is the mean of BOTH legs. Had T1 been kept as the
        // 100-only average, the series would step 150 -> 100 -> 150 on nothing.
        assertThat(result).allSatisfy(bar ->
                assertThat(bar.getClose()).isEqualByComparingTo("150"));
    }

    @Test
    @DisplayName("a leg with no candles at all yields an empty series")
    void emptyLegYieldsNothing() {
        List<ChartCandleResponse> result = averager.average(Arrays.asList(
                List.of(candle(T0, "100", "100", "100", "100")),
                List.of()
        ));

        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("a single leg passes through, ascending — the plain-contract case")
    void singleLegPassesThrough() {
        // Both chart services route the ordinary single-strike chart through
        // here, so this path must not perturb it.
        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(candle(T2, "3", "3", "3", "3"),
                        candle(T0, "1", "1", "1", "1"),
                        candle(T1, "2", "2", "2", "2"))
        ));

        assertThat(result).extracting(ChartCandleResponse::getTime)
                .containsExactly(T0, T1, T2);
        assertThat(result.get(0).getClose()).isEqualByComparingTo("1");
    }

    @Test
    @DisplayName("output is ascending by time regardless of input order")
    void outputIsAscending() {
        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(candle(T2, "10", "10", "10", "10"),
                        candle(T0, "10", "10", "10", "10"),
                        candle(T1, "10", "10", "10", "10")),
                List.of(candle(T1, "20", "20", "20", "20"),
                        candle(T2, "20", "20", "20", "20"),
                        candle(T0, "20", "20", "20", "20"))
        ));

        assertThat(result).extracting(ChartCandleResponse::getTime)
                .containsExactly(T0, T1, T2);
    }

    @Test
    @DisplayName("a duplicate timestamp within one leg counts once, not twice")
    void duplicateWithinALegCountsOnce() {
        // The candle tables are natural-keyed on (series, datetime) so this
        // should not arise — but if it did, a naive count of matching rows would
        // read one leg's duplicate as two legs agreeing and emit a bar built
        // from a single strike.
        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(candle(T0, "100", "100", "100", "100"),
                        candle(T0, "100", "100", "100", "100")),
                List.of(candle(T0, "300", "300", "300", "300"))
        ));

        assertThat(result).hasSize(1);
        assertThat(result.get(0).getClose()).isEqualByComparingTo("200");
    }

    @Test
    @DisplayName("a null OHLC component drops that bar rather than skewing it")
    void nullComponentDropsTheBar() {
        ChartCandleResponse partial = ChartCandleResponse.ohlc(
                T0, new BigDecimal("100"), null, new BigDecimal("90"), new BigDecimal("95"));

        List<ChartCandleResponse> result = averager.average(List.of(
                List.of(partial, candle(T1, "100", "100", "100", "100")),
                List.of(candle(T0, "200", "200", "200", "200"),
                        candle(T1, "200", "200", "200", "200"))
        ));

        assertThat(result).extracting(ChartCandleResponse::getTime).containsExactly(T1);
    }

    @Test
    @DisplayName("no legs at all is an empty series, not a failure")
    void noLegsIsEmpty() {
        assertThat(averager.average(List.of())).isEmpty();
        assertThat(averager.average(null)).isEmpty();
    }

    @Test
    @DisplayName("overlays are left null for the indicator pass to fill in")
    void overlaysAreNotComputedHere() {
        // Order matters in both chart services: aggregate, THEN compute
        // indicators on the bars actually drawn. Averaging must not pre-empt it.
        ChartCandleResponse bar = averager.average(List.of(
                List.of(candle(T0, "100", "100", "100", "100")),
                List.of(candle(T0, "200", "200", "200", "200"))
        )).get(0);

        assertThat(bar.getSma20Low()).isNull();
        assertThat(bar.getSma20High()).isNull();
        assertThat(bar.getSupertrend()).isNull();
        assertThat(bar.getSupertrendUp()).isNull();
    }
}
