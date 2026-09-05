package com.moneymaker.backtesting;

import com.moneymaker.entity.TradeOrder;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;

/**
 * The Pressure spec's own charge schedule, verbatim, for reconciling against the
 * reference run.
 *
 * <pre>
 *   Brokerage      40 round trip, flat
 *   STT            0.0625% of sell-side premium before 2024-10-01
 *                  0.10%   on/after
 *   NSE txn        0.0495% before 2024-10-01, 0.03503% on/after, BOTH legs
 *   Stamp          0.003%  on buy notional
 *   SEBI           0.0001% both legs
 *   GST            18% on (brokerage + txn + SEBI)
 * </pre>
 *
 * <h3>Why this exists alongside {@code TradeChargeService}</h3>
 * They disagree in two places, and both disagreements are real rather than a
 * mistake in either:
 *
 * <ul>
 *   <li><b>Brokerage.</b> This system's seeded rate is Zerodha's actual rule —
 *       20 per executed order <i>or</i> 0.03% of turnover, whichever is lower.
 *       At an ITM300 premium (~350 x 75 = ~26,000 a leg) the percentage wins at
 *       about 8, so a round trip costs ~16 where the spec charges a flat 40.</li>
 *   <li><b>Exchange transaction, pre-October 2024.</b> Seeded at 0.053%, the
 *       spec says 0.0495%.</li>
 * </ul>
 *
 * <p>Over 1,560 trades the brokerage gap alone is roughly 44,000 rupees
 * including its GST — about 30% of the spec's implied charge total. That is
 * far too large to average away, and too small to justify overwriting the
 * {@code charge_rate} table, which is global and date-effective: correcting
 * those rows would silently restate the net P&amp;L of every trade strategies
 * 1-4 have ever produced. So both are reported and the reader picks.
 *
 * <h3>Deliberately hardcoded</h3>
 * Normally a rate belongs in {@code charge_rate} (it is data, and a correction
 * should be an UPDATE). Not this one: these constants are not <i>our</i> broker's
 * rates and are not meant to be tuned. They are a fixed transcription of an
 * external document, used to answer one question — "does our net agree with the
 * reference run's net" — and a transcription that someone can edit in the
 * database is no longer a transcription. CLAUDE.md #9 governs numbers that
 * decide <i>when to trade</i>; nothing here touches a trading decision.
 */
final class PressureSpecCharges {

    private PressureSpecCharges() {
    }

    /** The date both statutory rates changed. */
    private static final LocalDate OCT_2024 = LocalDate.of(2024, 10, 1);

    private static final BigDecimal BROKERAGE_ROUND_TRIP = new BigDecimal("40");
    private static final BigDecimal STT_BEFORE = new BigDecimal("0.000625");
    private static final BigDecimal STT_AFTER = new BigDecimal("0.001");
    private static final BigDecimal TXN_BEFORE = new BigDecimal("0.000495");
    private static final BigDecimal TXN_AFTER = new BigDecimal("0.0003503");
    private static final BigDecimal STAMP_BUY = new BigDecimal("0.00003");
    private static final BigDecimal SEBI = new BigDecimal("0.000001");
    private static final BigDecimal GST = new BigDecimal("0.18");

    /**
     * Total charges in rupees for one completed trade, or zero when the row
     * cannot be costed (still OPEN, or no quantity recorded).
     */
    static BigDecimal forTrade(TradeOrder order) {
        if (order == null || order.getQuantity() == null || order.getQuantity() <= 0) return BigDecimal.ZERO;
        if (order.getEntryPrice() == null || order.getExitPrice() == null || order.getEntryTime() == null) {
            return BigDecimal.ZERO;
        }

        BigDecimal qty = BigDecimal.valueOf(order.getQuantity());
        LocalDate on = order.getEntryTime().toLocalDate();
        boolean beforeChange = on.isBefore(OCT_2024);

        boolean sellEntry = "SELL".equalsIgnoreCase(order.getEntryDirection());
        BigDecimal sellTurnover = (sellEntry ? order.getEntryPrice() : order.getExitPrice()).multiply(qty);
        BigDecimal buyTurnover = (sellEntry ? order.getExitPrice() : order.getEntryPrice()).multiply(qty);
        BigDecimal turnover = sellTurnover.add(buyTurnover);

        BigDecimal stt = sellTurnover.multiply(beforeChange ? STT_BEFORE : STT_AFTER);
        BigDecimal txn = turnover.multiply(beforeChange ? TXN_BEFORE : TXN_AFTER);
        BigDecimal sebi = turnover.multiply(SEBI);
        BigDecimal stamp = buyTurnover.multiply(STAMP_BUY);
        BigDecimal gst = BROKERAGE_ROUND_TRIP.add(txn).add(sebi).multiply(GST);

        return BROKERAGE_ROUND_TRIP.add(stt).add(txn).add(sebi).add(stamp).add(gst)
                .setScale(2, RoundingMode.HALF_UP);
    }
}
