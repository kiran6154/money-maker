package com.moneymaker.strategy.rules;

import com.moneymaker.entity.MarketData;

import java.time.LocalDate;
import java.util.List;

/**
 * Marks each {@link MarketData} candle's {@code smaXxDownTrending} and
 * {@code smaXxUpTrending} flags based on intra-day SMA progression.
 *
 * <p>For each SMA period and each trading day, a running count of "deviations"
 * is kept:
 * <ul>
 *   <li>Down-trend deviation = current SMA &gt;= previous SMA.</li>
 *   <li>Up-trend deviation   = current SMA &lt;= previous SMA.</li>
 * </ul>
 * The corresponding flag stays true while its deviation count is at most
 * {@code maxDeviations}. Both counters reset at every new day. Candles whose
 * SMA isn't yet calculated (null or 0) are flagged false for that period.
 */
public final class SmaTrendCalculator {
    private SmaTrendCalculator() {}

    public static void compute(List<MarketData> data, int maxDeviations) {
        if (data == null || data.isEmpty()) return;

        LocalDate currentDay = null;
        int dDev50 = 0, dDev100 = 0, dDev200 = 0, dDev500 = 0;
        int uDev50 = 0, uDev100 = 0, uDev200 = 0, uDev500 = 0;
        MarketData prev = null;

        for (MarketData c : data) {
            LocalDate day = c.getTimestamp().toLocalDate();
            if (!day.equals(currentDay)) {
                currentDay = day;
                dDev50 = dDev100 = dDev200 = dDev500 = 0;
                uDev50 = uDev100 = uDev200 = uDev500 = 0;
                prev = null;
            }

            if (prev == null) {
                // First candle of the day — flag true if SMA is available.
                c.setSma50DownTrending(c.getSmaValue50() != null);
                c.setSma100DownTrending(c.getSmaValue100() != null);
                c.setSma200DownTrending(c.getSmaValue200() != null);
                c.setSma500DownTrending(c.getSmaValue500() != null);

                c.setSma50UpTrending(c.getSmaValue50() != null);
                c.setSma100UpTrending(c.getSmaValue100() != null);
                c.setSma200UpTrending(c.getSmaValue200() != null);
                c.setSma500UpTrending(c.getSmaValue500() != null);
            } else {
                dDev50  += downDeviation(prev.getSmaValue50(),  c.getSmaValue50());
                dDev100 += downDeviation(prev.getSmaValue100(), c.getSmaValue100());
                dDev200 += downDeviation(prev.getSmaValue200(), c.getSmaValue200());
                dDev500 += downDeviation(prev.getSmaValue500(), c.getSmaValue500());

                uDev50  += upDeviation(prev.getSmaValue50(),  c.getSmaValue50());
                uDev100 += upDeviation(prev.getSmaValue100(), c.getSmaValue100());
                uDev200 += upDeviation(prev.getSmaValue200(), c.getSmaValue200());
                uDev500 += upDeviation(prev.getSmaValue500(), c.getSmaValue500());

                c.setSma50DownTrending(available(prev.getSmaValue50(),  c.getSmaValue50())  && dDev50  <= maxDeviations);
                c.setSma100DownTrending(available(prev.getSmaValue100(), c.getSmaValue100()) && dDev100 <= maxDeviations);
                c.setSma200DownTrending(available(prev.getSmaValue200(), c.getSmaValue200()) && dDev200 <= maxDeviations);
                c.setSma500DownTrending(available(prev.getSmaValue500(), c.getSmaValue500()) && dDev500 <= maxDeviations);

                c.setSma50UpTrending(available(prev.getSmaValue50(),  c.getSmaValue50())  && uDev50  <= maxDeviations);
                c.setSma100UpTrending(available(prev.getSmaValue100(), c.getSmaValue100()) && uDev100 <= maxDeviations);
                c.setSma200UpTrending(available(prev.getSmaValue200(), c.getSmaValue200()) && uDev200 <= maxDeviations);
                c.setSma500UpTrending(available(prev.getSmaValue500(), c.getSmaValue500()) && uDev500 <= maxDeviations);
            }
            prev = c;
        }
    }

    private static int downDeviation(Double prev, Double curr) {
        if (!available(prev, curr)) return 0;
        return curr >= prev ? 1 : 0;
    }

    private static int upDeviation(Double prev, Double curr) {
        if (!available(prev, curr)) return 0;
        return curr <= prev ? 1 : 0;
    }

    private static boolean available(Double prev, Double curr) {
        return prev != null && curr != null && prev > 0 && curr > 0;
    }
}
