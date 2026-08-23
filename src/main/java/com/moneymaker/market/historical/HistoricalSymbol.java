package com.moneymaker.market.historical;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Locale;

/**
 * Codec for the synthetic {@code symbol} strings used when a backtest reads its
 * candles from {@code historical_spot_candles} / {@code historical_option_candles}.
 *
 * <h3>Why synthetic</h3>
 * Everywhere in the pipeline the {@code symbol} argument of
 * {@code MarketDataService.fetchHistoricalData} is a broker instrument token.
 * The historical tables deliberately carry no token — they are natural-keyed on
 * {@code stock_code / exchange_code / expiry_date / strike_price / option_right}
 * (see {@code docs/HISTORICAL_CHART_DATA_PLAN.md}, which explicitly rules out
 * introducing tokens or {@code instrument_details} rows for this data). Encoding
 * the natural key into the symbol string lets the historical source reuse the
 * existing token-shaped seam without touching any downstream consumer.
 *
 * <h3>Format</h3>
 * <pre>
 *   spot    HIST:NIFTY:NSE:SPOT
 *   option  HIST:NIFTY:NFO:2024-01-04:21700:CE
 * </pre>
 *
 * <p><b>The separator must not be {@code |}.</b> {@code SharedData} strike keys
 * are {@code token|interval|optionType|strike|optionToken|itmDepth|otmDepth} and
 * are split on {@code \|} by {@code OrderService.ParsedKey}, {@code Strategy1}
 * and {@code BacktestingPositionMonitorService}; a {@code |} inside the symbol
 * would shift every field. The longest encoded form is well under the
 * {@code trade_order.option_token} limit of {@code VARCHAR(100)}.
 */
public final class HistoricalSymbol {

    /** Marks a symbol as historical rather than a broker instrument token. */
    public static final String PREFIX = "HIST";

    /** Field separator — deliberately not {@code |}; see class javadoc. */
    public static final String SEPARATOR = ":";

    /** Trailing marker on the spot form, so the two shapes cannot be confused. */
    private static final String SPOT_MARKER = "SPOT";

    private HistoricalSymbol() {
    }

    /** {@code HIST:NIFTY:NSE:SPOT} */
    public static String encodeSpot(String stockCode, String exchangeCode) {
        return String.join(SEPARATOR, PREFIX, upper(stockCode), upper(exchangeCode), SPOT_MARKER);
    }

    /** {@code HIST:NIFTY:NFO:2024-01-04:21700:CE} */
    public static String encodeOption(String stockCode,
                                      String exchangeCode,
                                      LocalDate expiryDate,
                                      BigDecimal strikePrice,
                                      String optionRight) {
        return String.join(SEPARATOR,
                PREFIX,
                upper(stockCode),
                upper(exchangeCode),
                expiryDate.toString(),
                strikePrice.stripTrailingZeros().toPlainString(),
                upper(optionRight));
    }

    /** True when {@code symbol} was produced by this codec rather than being a broker token. */
    public static boolean isHistorical(String symbol) {
        return symbol != null && symbol.startsWith(PREFIX + SEPARATOR);
    }

    /**
     * Decodes a symbol produced by {@link #encodeSpot} or {@link #encodeOption}.
     *
     * @throws IllegalArgumentException if the string is not a valid historical symbol
     */
    public static Parsed parse(String symbol) {
        if (!isHistorical(symbol)) {
            throw new IllegalArgumentException("Not a historical symbol: " + symbol);
        }
        String[] parts = symbol.split(SEPARATOR, -1);

        if (parts.length == 4 && SPOT_MARKER.equals(parts[3])) {
            return new Parsed(parts[1], parts[2], null, null, null);
        }
        if (parts.length == 6) {
            try {
                return new Parsed(
                        parts[1],
                        parts[2],
                        LocalDate.parse(parts[3]),
                        new BigDecimal(parts[4]),
                        parts[5]);
            } catch (RuntimeException ex) {
                throw new IllegalArgumentException("Malformed historical option symbol: " + symbol, ex);
            }
        }
        throw new IllegalArgumentException("Malformed historical symbol: " + symbol);
    }

    private static String upper(String value) {
        return value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
    }

    /**
     * Decoded natural key. {@code expiryDate} / {@code strikePrice} /
     * {@code optionRight} are {@code null} for the spot form — use {@link #isSpot()}.
     */
    public record Parsed(String stockCode,
                         String exchangeCode,
                         LocalDate expiryDate,
                         BigDecimal strikePrice,
                         String optionRight) {

        public boolean isSpot() {
            return expiryDate == null;
        }
    }
}
