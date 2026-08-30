package com.moneymaker.journal.contributors;

import com.moneymaker.entity.MarketData;
import com.moneymaker.journal.FeatureContributor;
import com.moneymaker.journal.ObservationContext;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * SMA values and trend flags on the traded leg, exactly as the strategy saw them.
 *
 * <p>Read off the candle rather than recomputed: {@code SMAIndicatorImpl} has
 * already stamped {@code smaValueN} and {@code SmaTrendCalculator} the
 * up/down flags on these very objects. Recomputing here could disagree with what
 * the gate actually evaluated — which would make the journal describe a decision
 * that never happened.
 *
 * <p>Also records the gate inputs themselves ({@code open}, {@code close}) and
 * the distance from each SMA, so "how marginal was this signal" is answerable.
 * A trade that cleared its SMA by 0.2 points is not the same trade as one that
 * cleared it by 20, and the ledger cannot currently tell them apart.
 */
@Component
public class SmaStateContributor implements FeatureContributor {

    private static final int[] PERIODS = {20, 50, 100, 200, 500};

    @Override
    public String name() {
        return "sma-state";
    }

    @Override
    public Map<String, Object> contribute(ObservationContext ctx) {
        Map<String, Object> f = new LinkedHashMap<>();
        MarketData c = ctx == null ? null : ctx.lastOptionCandle();
        if (c == null) {
            return f;
        }

        f.put("bar_open", c.getOpen());
        f.put("bar_high", c.getHigh());
        f.put("bar_low", c.getLow());
        f.put("bar_close", c.getClose());
        f.put("bar_time", String.valueOf(c.getTimestamp()));

        for (int p : PERIODS) {
            Double sma = smaValue(c, p);
            if (sma == null || sma <= 0d) {
                continue;   // not computable on this series length; a real absence
            }
            f.put("sma" + p, sma);
            f.put("sma" + p + "_down", downFlag(c, p));
            f.put("sma" + p + "_up", upFlag(c, p));

            if (c.getClose() != null) {
                // Signed distance of the close from the SMA. Negative means the
                // close sits below it, which is the sell-gate condition.
                f.put("close_minus_sma" + p,
                        c.getClose().subtract(BigDecimal.valueOf(sma)));
            }
        }
        return f;
    }

    private Double smaValue(MarketData c, int period) {
        return switch (period) {
            case 20 -> c.getSmaValue20();
            case 50 -> c.getSmaValue50();
            case 100 -> c.getSmaValue100();
            case 200 -> c.getSmaValue200();
            case 500 -> c.getSmaValue500();
            default -> null;
        };
    }

    private boolean downFlag(MarketData c, int period) {
        return switch (period) {
            case 20 -> c.isSma20DownTrending();
            case 50 -> c.isSma50DownTrending();
            case 100 -> c.isSma100DownTrending();
            case 200 -> c.isSma200DownTrending();
            case 500 -> c.isSma500DownTrending();
            default -> false;
        };
    }

    private boolean upFlag(MarketData c, int period) {
        return switch (period) {
            case 20 -> c.isSma20UpTrending();
            case 50 -> c.isSma50UpTrending();
            case 100 -> c.isSma100UpTrending();
            case 200 -> c.isSma200UpTrending();
            case 500 -> c.isSma500UpTrending();
            default -> false;
        };
    }
}
