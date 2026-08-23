package com.moneymaker.chart.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * One candle as the dashboard renders it, plus the overlays computed for it.
 *
 * <h3>SMA is paired, over low and high</h3>
 * Each period carries two values: {@code sma{N}Low} and {@code sma{N}High}. The
 * low series is the one the trading strategy actually gates on — see
 * {@code SMAIndicatorImpl}, which averages candle lows deliberately — so plotting
 * it means the chart and the strategy finally agree. The high series gives the
 * other edge of the envelope. There is no close-based SMA any more.
 *
 * <h3>Construction</h3>
 * Built with the no-arg constructor plus setters, deliberately. An all-args
 * constructor would now take seventeen positional arguments of which fourteen are
 * {@code BigDecimal}, so a transposed pair would compile happily and silently
 * mis-plot.
 */
@Data
@NoArgsConstructor
public class ChartCandleResponse {

    private OffsetDateTime time;
    private BigDecimal open;
    private BigDecimal high;
    private BigDecimal low;
    private BigDecimal close;

    private BigDecimal sma20Low;
    private BigDecimal sma20High;
    private BigDecimal sma50Low;
    private BigDecimal sma50High;
    private BigDecimal sma100Low;
    private BigDecimal sma100High;
    private BigDecimal sma200Low;
    private BigDecimal sma200High;
    private BigDecimal sma500Low;
    private BigDecimal sma500High;

    /** SuperTrend(7, 3) band value for this candle; {@code null} until ATR warms up. */
    private BigDecimal supertrend;

    /**
     * {@code TRUE} while SuperTrend is in an uptrend (band sits below price),
     * {@code FALSE} in a downtrend, {@code null} before the indicator warms up.
     * Drives the green/red split on the rendered line.
     */
    private Boolean supertrendUp;

    /** OHLC-only copy; overlays are left null for the indicator pass to fill in. */
    public static ChartCandleResponse ohlc(OffsetDateTime time,
                                           BigDecimal open,
                                           BigDecimal high,
                                           BigDecimal low,
                                           BigDecimal close) {
        ChartCandleResponse candle = new ChartCandleResponse();
        candle.setTime(time);
        candle.setOpen(open);
        candle.setHigh(high);
        candle.setLow(low);
        candle.setClose(close);
        return candle;
    }
}
