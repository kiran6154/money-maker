package com.moneymaker.journal.contributors;

import com.moneymaker.entity.MarketData;
import com.moneymaker.journal.FeatureContributor;
import com.moneymaker.journal.ObservationContext;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The context you cannot reconstruct after the fact: what the leg and the index
 * were doing at this moment, and where in the session it happened.
 *
 * <p>Everything here is derived only from bars already settled at
 * {@code observedAt} — the series handed in has been narrowed by
 * {@code MarketDataService.dropIncompleteBars}, and this contributor must not
 * widen it.
 */
@Component
public class PriceContextContributor implements FeatureContributor {

    private static final LocalTime SESSION_OPEN = LocalTime.of(9, 15);
    private static final int SCALE = 4;

    @Override
    public String name() {
        return "price-context";
    }

    @Override
    public Map<String, Object> contribute(ObservationContext ctx) {
        Map<String, Object> f = new LinkedHashMap<>();
        if (ctx == null || ctx.observedAt() == null) {
            return f;
        }

        f.put("minutes_since_open",
                Duration.between(SESSION_OPEN, ctx.observedAt().toLocalTime()).toMinutes());

        MarketData opt = ctx.lastOptionCandle();
        if (opt != null && opt.getClose() != null) {
            f.put("premium", opt.getClose());

            // Where the premium sits inside the day's range so far. A sell at the
            // top of the day's range is a different trade to one at the bottom,
            // and the ledger's entry_price alone cannot tell them apart.
            Range dayRange = rangeForDay(ctx.optionCandles(), ctx.observedAt().toLocalDate());
            if (dayRange != null && dayRange.span().signum() > 0) {
                f.put("premium_pct_of_day_range",
                        opt.getClose().subtract(dayRange.low())
                                .divide(dayRange.span(), SCALE, RoundingMode.HALF_UP));
                f.put("option_day_high", dayRange.high());
                f.put("option_day_low", dayRange.low());
            }
        }

        MarketData und = ctx.lastUnderlyingCandle();
        if (und != null && und.getClose() != null) {
            f.put("spot", und.getClose());

            // How far the traded strike sits from spot, in points and in strikes.
            // Moneyness drives almost everything about an option's behaviour, and
            // is not recoverable later once spot has moved.
            if (ctx.strike() != null) {
                BigDecimal strike = BigDecimal.valueOf(ctx.strike());
                f.put("strike_minus_spot", strike.subtract(und.getClose()));
            }

            Range dayRange = rangeForDay(ctx.underlyingCandles(), ctx.observedAt().toLocalDate());
            if (dayRange != null) {
                f.put("spot_day_high", dayRange.high());
                f.put("spot_day_low", dayRange.low());
                if (dayRange.span().signum() > 0) {
                    f.put("spot_pct_of_day_range",
                            und.getClose().subtract(dayRange.low())
                                    .divide(dayRange.span(), SCALE, RoundingMode.HALF_UP));
                }
            }
        }

        return f;
    }

    private record Range(BigDecimal high, BigDecimal low) {
        BigDecimal span() {
            return high.subtract(low);
        }
    }

    /** High / low of {@code day} using only the bars present in the series. */
    private Range rangeForDay(List<MarketData> candles, LocalDate day) {
        if (candles == null || candles.isEmpty()) {
            return null;
        }
        BigDecimal high = null;
        BigDecimal low = null;
        for (MarketData c : candles) {
            if (c == null || c.getTimestamp() == null
                    || !day.equals(c.getTimestamp().toLocalDate())) {
                continue;
            }
            if (c.getHigh() != null && (high == null || c.getHigh().compareTo(high) > 0)) {
                high = c.getHigh();
            }
            if (c.getLow() != null && (low == null || c.getLow().compareTo(low) < 0)) {
                low = c.getLow();
            }
        }
        return (high == null || low == null) ? null : new Range(high, low);
    }
}
