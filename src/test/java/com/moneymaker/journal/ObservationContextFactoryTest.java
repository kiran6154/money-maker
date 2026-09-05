package com.moneymaker.journal;

import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.shared.data.SharedData;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Which cached series describes an observation.
 *
 * <p>The same leg is cached once per interval any config asked for, so "the
 * series for this option token" is a choice, not a lookup. Taking the first hit
 * is {@code ConcurrentHashMap} iteration order — the defect
 * {@code SharedData.latestCachedCandle} was already fixed for, where a monitor
 * could price a 5-minute tick off a 15-minute bar.
 */
class ObservationContextFactoryTest {

    private static final LocalDateTime AT = LocalDateTime.of(2026, 5, 8, 10, 0);
    private static final String TOKEN = "OPT-1";

    private final ObservationContextFactory factory = new ObservationContextFactory();

    @BeforeEach
    @AfterEach
    void clearCaches() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.marketDataByInstrumentAndInterval.clear();
    }

    private static List<MarketData> seriesOf(String close) {
        MarketData md = new MarketData();
        md.setTimestamp(AT);
        md.setInstrumenttoken(TOKEN);
        md.setOpen(new BigDecimal(close));
        md.setHigh(new BigDecimal(close));
        md.setLow(new BigDecimal(close));
        md.setClose(new BigDecimal(close));
        return List.of(md);
    }

    /** key = symbol|interval|optionType|strike|optionToken|itmDepth|otmDepth */
    private static void cacheLeg(String interval, String close) {
        SharedData.putStrikeSeries(
                "NIFTY|" + interval + "|CE|21000|" + TOKEN + "|1|1", seriesOf(close), null);
    }

    private static TradeOrder openOrder() {
        TradeOrder order = new TradeOrder();
        order.setId(1L);
        order.setOptionToken(TOKEN);
        order.setOptionType("CE");
        order.setOptionStrike(21000);
        order.setEntryDirection("SELL");
        order.setEntryTime(AT.minusMinutes(30));
        return order;
    }

    @Test
    @DisplayName("a monitor tick is described by the leg's finest cached series — what it priced off")
    void openPositionTakesTheFinestInterval() {
        cacheLeg("15minute", "150");
        cacheLeg("5minute", "120");

        ObservationContext ctx = factory.forOpenPosition(openOrder(), AT);

        assertThat(ctx).isNotNull();
        assertThat(ctx.kind()).isEqualTo(ObservationKind.MONITOR);
        assertThat(ctx.lastOptionCandle().getClose()).isEqualByComparingTo("120");
        // Stamped, so analysis can see which timeframe a row describes rather
        // than having to assume one.
        assertThat(ctx.intervalMinutes()).isEqualTo(5);
    }

    @Test
    @DisplayName("a caller that knows the timeframe gets that one — an ENTRY describes what the strategy read")
    void orderPrefersTheCallersInterval() {
        cacheLeg("5minute", "120");
        cacheLeg("15minute", "150");

        ObservationContext ctx = factory.forOrder(ObservationKind.ENTRY, openOrder(), AT, 15);

        assertThat(ctx.lastOptionCandle().getClose()).isEqualByComparingTo("150");
        assertThat(ctx.intervalMinutes()).isEqualTo(15);
    }

    @Test
    @DisplayName("an uncached leg yields a context with no series rather than no context")
    void missingSeriesStillDescribesTheLeg() {
        ObservationContext ctx = factory.forOpenPosition(openOrder(), AT);

        assertThat(ctx).isNotNull();
        assertThat(ctx.optionCandles()).isEmpty();
        assertThat(ctx.intervalMinutes()).isNull();
        assertThat(ctx.entryIsSell()).isTrue();
    }

    @Test
    @DisplayName("no order and no timestamp means no observation")
    void nullsYieldNoContext() {
        assertThat(factory.forOpenPosition(null, AT)).isNull();
        assertThat(factory.forOpenPosition(openOrder(), null)).isNull();
    }
}
