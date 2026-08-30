package com.moneymaker.order.service;

import com.moneymaker.entity.ChargeRate;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.dto.TradeCharges;
import com.moneymaker.repository.ChargeRateRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Turns a {@link TradeOrder} into its rupee economics: gross P&L, the brokerage
 * and statutory charges on both legs, and net.
 *
 * <h3>Computed on read, not stored</h3>
 * Nothing is written back onto {@code trade_order}. The rates are seeded as
 * documented-but-unverified defaults, so the first real contract note will almost
 * certainly correct one of them — and when it does, every historical trade should
 * re-cost itself rather than carry a number frozen from a wrong rate. Charges are
 * a view over the ledger, not part of it.
 *
 * <h3>Rates are date-effective</h3>
 * Each trade is costed with the rates in force on <em>its own entry date</em>.
 * A 2024 backtest spans the 2024-10-01 change to both STT and the NSE
 * transaction charge, so a single flat rate would misstate roughly a quarter of
 * the trades — and in the direction that flatters the earlier ones.
 *
 * <h3>Assumptions worth knowing</h3>
 * <ul>
 *   <li>Both legs are assumed to execute on the entry date. These are intraday
 *       strategies and {@code forceCloseOpenPositions} squares off at 15:20, so
 *       that holds today; a positional variant would need the exit date too.</li>
 *   <li>Turnover for an option leg is {@code premium × quantity} — premium
 *       turnover, not notional. Statutory charges on F&O options are levied on
 *       premium.</li>
 *   <li>Quantity comes from {@code trade_order.quantity}, snapshotted at entry.
 *       Rows written before changeset 029 have none; those are reported with a
 *       null net rather than being silently costed at some assumed lot size.</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TradeChargeService {

    private static final int MONEY_SCALE = 2;

    private final ChargeRateRepository chargeRateRepository;

    /**
     * Costs one trade. Returns {@code null} when the row cannot be costed — no
     * quantity, or no entry/exit price yet (an OPEN position has no exit leg).
     */
    public TradeCharges compute(TradeOrder order, RateResolver rates) {
        if (order == null || order.getQuantity() == null || order.getQuantity() <= 0) {
            return null;
        }
        if (order.getEntryPrice() == null || order.getExitPrice() == null || order.getEntryTime() == null) {
            return null;
        }

        BigDecimal qty = BigDecimal.valueOf(order.getQuantity());
        LocalDate on = order.getEntryTime().toLocalDate();

        boolean sellEntry = "SELL".equalsIgnoreCase(order.getEntryDirection());
        // For a SELL entry the sell leg is the entry and the buy leg is the exit.
        BigDecimal sellTurnover = (sellEntry ? order.getEntryPrice() : order.getExitPrice()).multiply(qty);
        BigDecimal buyTurnover  = (sellEntry ? order.getExitPrice()  : order.getEntryPrice()).multiply(qty);
        BigDecimal turnover = sellTurnover.add(buyTurnover);

        BigDecimal flat    = rates.value(ChargeRate.BROKERAGE_FLAT_PER_ORDER, on);
        BigDecimal pct     = rates.value(ChargeRate.BROKERAGE_PCT_OF_TURNOVER, on);
        BigDecimal brokerage = legBrokerage(sellTurnover, flat, pct).add(legBrokerage(buyTurnover, flat, pct));

        BigDecimal stt      = sellTurnover.multiply(rates.value(ChargeRate.STT_SELL_PCT, on));
        BigDecimal exchange = turnover.multiply(rates.value(ChargeRate.EXCHANGE_TXN_PCT, on));
        BigDecimal sebi     = turnover.multiply(rates.value(ChargeRate.SEBI_PCT, on));
        BigDecimal stamp    = buyTurnover.multiply(rates.value(ChargeRate.STAMP_DUTY_BUY_PCT, on));
        BigDecimal gst      = brokerage.add(exchange).add(sebi).multiply(rates.value(ChargeRate.GST_PCT, on));

        BigDecimal total = brokerage.add(stt).add(exchange).add(sebi).add(stamp).add(gst);
        BigDecimal gross = order.getProfit() == null ? BigDecimal.ZERO : order.getProfit().multiply(qty);

        return new TradeCharges(
                order.getQuantity(),
                money(gross),
                money(brokerage), money(stt), money(exchange),
                money(sebi), money(stamp), money(gst),
                money(total),
                money(gross.subtract(total)));
    }

    /** Zerodha-style "flat or percentage, whichever is lower", per executed order. */
    private BigDecimal legBrokerage(BigDecimal legTurnover, BigDecimal flat, BigDecimal pct) {
        BigDecimal byPct = legTurnover.multiply(pct);
        return byPct.compareTo(flat) < 0 ? byPct : flat;
    }

    private static BigDecimal money(BigDecimal v) {
        return v.setScale(MONEY_SCALE, RoundingMode.HALF_UP);
    }

    /** Loads every rate once so a whole ledger costs in a single query. */
    @Transactional(readOnly = true)
    public RateResolver resolver() {
        return new RateResolver(chargeRateRepository
                .findBySegmentOrderByChargeTypeAscEffectiveFromAsc(ChargeRate.SEGMENT_NFO_OPT));
    }

    /**
     * Date-keyed lookup over the rate table. For each charge type it keeps the
     * rows sorted by {@code effective_from}; the rate in force on a date is the
     * latest row not after it.
     */
    public static final class RateResolver {

        private final Map<String, TreeMap<LocalDate, BigDecimal>> byType = new HashMap<>();
        private final List<String> missingReported = new ArrayList<>();

        RateResolver(List<ChargeRate> rows) {
            for (ChargeRate r : rows) {
                byType.computeIfAbsent(r.getChargeType(), k -> new TreeMap<>())
                        .put(r.getEffectiveFrom(), r.getValue());
            }
        }

        public boolean isEmpty() {
            return byType.isEmpty();
        }

        /**
         * The rate in force for {@code type} on {@code date}, or zero when the
         * table has no row covering it.
         *
         * <p>Zero rather than an exception on purpose: a missing rate should
         * understate charges visibly in the totals, not abort a ledger read. It
         * is logged once per type so it cannot pass unnoticed.
         */
        BigDecimal value(String type, LocalDate date) {
            TreeMap<LocalDate, BigDecimal> byDate = byType.get(type);
            if (byDate != null) {
                Map.Entry<LocalDate, BigDecimal> e = byDate.floorEntry(date);
                if (e != null) {
                    return e.getValue();
                }
            }
            if (!missingReported.contains(type)) {
                missingReported.add(type);
                log.warn("[charges] no {} rate in force on {} - treating as zero. Charges will be understated. "
                        + "Add a charge_rate row with an earlier effective_from.", type, date);
            }
            return BigDecimal.ZERO;
        }
    }
}
