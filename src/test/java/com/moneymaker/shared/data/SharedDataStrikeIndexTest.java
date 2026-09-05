package com.moneymaker.shared.data;

import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Pins {@link SharedData#latestCachedCandle} across the GAPS #27 rewrite.
 *
 * <p>That change replaced a full scan of the strike cache — which parsed every
 * key with {@code split("\\|")} to read one segment — with a contract-id index
 * maintained at write time. It is a <b>pure performance change</b>: the answer
 * must be identical for every input, which is exactly what a lookup rewrite is
 * easiest to get subtly wrong about.</p>
 *
 * <p>The three behaviours that carry real risk if they drift:</p>
 * <ol>
 *   <li><b>Finest interval wins.</b> A bar stamped {@code T} on a 15-minute
 *       series only closes at {@code T+15}, so quoting off it reads fifteen
 *       minutes of price that had not happened at the exit timestamp written to
 *       the row. The old code chose the finest interval; so must this.</li>
 *   <li><b>{@code atOrBefore} is respected.</b> Returning a later bar is
 *       lookahead in the position monitor.</li>
 *   <li><b>An unindexed write is invisible.</b> The index is only sound while
 *       nothing writes the cache behind its back, so that failure mode is
 *       asserted rather than left to a comment.</li>
 * </ol>
 */
class SharedDataStrikeIndexTest {

    private static final String TOKEN = "HIST:NIFTY:NFO:2024-01-04:21600:CE";
    private static final LocalDateTime T0 = LocalDateTime.of(2024, 1, 2, 9, 15);

    @BeforeEach
    void reset() {
        SharedData.clearStrikeCaches();
    }

    private static MarketData bar(LocalDateTime ts, String close) {
        MarketData md = new MarketData();
        md.setTimestamp(ts);
        md.setClose(new BigDecimal(close));
        md.setHigh(new BigDecimal(close));
        md.setLow(new BigDecimal(close));
        md.setOpen(new BigDecimal(close));
        return md;
    }

    private static List<MarketData> series(int intervalMinutes, int count, int basePrice) {
        List<MarketData> out = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            out.add(bar(T0.plusMinutes((long) i * intervalMinutes), String.valueOf(basePrice + i)));
        }
        return out;
    }

    private static String key(String interval, String token) {
        return "NIFTY|" + interval + "|CE|21600|" + token + "|null|null";
    }

    @Test
    @DisplayName("returns the newest bar for the requested contract")
    void returnsNewestBar() {
        SharedData.putStrikeSeries(key("5minute", TOKEN), series(5, 4, 100), T0);

        MarketData md = SharedData.latestCachedCandle(TOKEN, null);

        assertThat(md).isNotNull();
        assertThat(md.getClose()).isEqualByComparingTo("103");
    }

    @Test
    @DisplayName("the FINEST interval wins — a coarse bar would quote price that has not happened yet")
    void finestIntervalWins() {
        // Same contract cached at two widths. The 15-minute bar stamped 09:15
        // does not close until 09:30, so quoting off it at 09:20 reads ten
        // minutes into the future of the recorded exit timestamp.
        SharedData.putStrikeSeries(key("15minute", TOKEN), series(15, 3, 900), T0);
        SharedData.putStrikeSeries(key("5minute", TOKEN), series(5, 3, 100), T0);

        MarketData md = SharedData.latestCachedCandle(TOKEN, null);

        assertThat(md.getClose())
                .as("must come from the 5-minute series, not the 15-minute one")
                .isEqualByComparingTo("102");
    }

    @Test
    @DisplayName("atOrBefore is respected — never returns a bar from the future")
    void respectsAtOrBefore() {
        SharedData.putStrikeSeries(key("5minute", TOKEN), series(5, 6, 100), T0);

        // Bars at 09:15,20,25,30,35,40 -> closes 100..105. Ask as of 09:27.
        MarketData md = SharedData.latestCachedCandle(TOKEN, T0.plusMinutes(12));

        assertThat(md.getTimestamp()).isEqualTo(T0.plusMinutes(10));
        assertThat(md.getClose()).isEqualByComparingTo("102");
    }

    @Test
    @DisplayName("an unknown contract is null, not the first thing in the cache")
    void unknownTokenIsNull() {
        SharedData.putStrikeSeries(key("5minute", TOKEN), series(5, 3, 100), T0);

        assertThat(SharedData.latestCachedCandle("HIST:NIFTY:NFO:2024-01-04:21700:PE", null)).isNull();
        assertThat(SharedData.latestCachedCandle(null, null)).isNull();
    }

    @Test
    @DisplayName("contracts do not bleed into each other — the bug the old scan risked")
    void contractsAreIsolated() {
        String other = "HIST:NIFTY:NFO:2024-01-04:21700:PE";
        SharedData.putStrikeSeries(key("5minute", TOKEN), series(5, 3, 100), T0);
        SharedData.putStrikeSeries("NIFTY|5minute|PE|21700|" + other + "|null|null", series(5, 3, 500), T0);

        assertThat(SharedData.latestCachedCandle(TOKEN, null).getClose()).isEqualByComparingTo("102");
        assertThat(SharedData.latestCachedCandle(other, null).getClose()).isEqualByComparingTo("502");
    }

    @Test
    @DisplayName("clearStrikeCaches clears the index too — otherwise stale prices survive the day boundary")
    void clearAlsoClearsIndex() {
        SharedData.putStrikeSeries(key("5minute", TOKEN), series(5, 3, 100), T0);
        assertThat(SharedData.latestCachedCandle(TOKEN, null)).isNotNull();

        SharedData.clearStrikeCaches();

        // If the index outlived the map, the position monitor would keep quoting
        // yesterday's candles for a contract that is no longer cached — and
        // nothing in the ledger would look wrong.
        assertThat(SharedData.latestCachedCandle(TOKEN, null)).isNull();
        assertThat(SharedData.strikeMarketDataByInstrumentAndInterval).isEmpty();
        assertThat(SharedData.strikeMarketDataTick).isEmpty();
        assertThat(SharedData.strikeSeriesByToken).isEmpty();
    }

    @Test
    @DisplayName("putStrikeSeries writes the S8 freshness stamp alongside the series")
    void writesFreshnessStamp() {
        String k = key("5minute", TOKEN);
        SharedData.putStrikeSeries(k, series(5, 3, 100), T0);

        // Strategies refuse a series whose stamp is not this tick's; if the stamp
        // were not written here, every leg would look stale and nothing would
        // ever trade.
        assertThat(SharedData.strikeMarketDataTick.get(k)).isEqualTo(T0);
    }

    @Test
    @DisplayName("a write that bypasses putStrikeSeries is invisible — the index's one hard requirement")
    void directWriteIsNotIndexed() {
        // Documented as a hazard on SharedData.strikeSeriesByToken and asserted
        // here so the contract is executable: a key put straight into the map is
        // NOT findable by contract id, which in production means the position
        // stops being quoted and its stop-loss can never fire.
        SharedData.strikeMarketDataByInstrumentAndInterval.put(key("5minute", TOKEN), series(5, 3, 100));

        assertThat(SharedData.latestCachedCandle(TOKEN, null))
                .as("bypassing putStrikeSeries must not silently work — if this starts passing, "
                        + "someone added a scan fallback and reintroduced GAPS #27")
                .isNull();
    }

    @Test
    @DisplayName("empty and malformed inputs are ignored rather than corrupting the index")
    void ignoresEmptyAndMalformed() {
        SharedData.putStrikeSeries(key("5minute", TOKEN), List.of(), T0);
        SharedData.putStrikeSeries(null, series(5, 3, 100), T0);
        SharedData.putStrikeSeries("too|few|segments", series(5, 3, 100), T0);

        assertThat(SharedData.latestCachedCandle(TOKEN, null)).isNull();
        assertThat(SharedData.strikeSeriesByToken).isEmpty();
    }
}
