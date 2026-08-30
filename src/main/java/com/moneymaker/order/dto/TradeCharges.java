package com.moneymaker.order.dto;

import java.math.BigDecimal;

/**
 * Rupee economics for one trade: quantity, gross P&L, the charge breakdown for
 * both legs, and net.
 *
 * <p>Computed on read by {@code TradeChargeService} from date-effective
 * {@code charge_rate} rows — never stored — so correcting a rate re-costs the
 * whole ledger. See {@code TradeChargeService} for the assumptions.
 *
 * <p>All amounts are rupees at 2dp. {@code grossPl} is per-share
 * {@code trade_order.profit} × {@code quantity}.
 */
public record TradeCharges(
        Integer quantity,
        BigDecimal grossPl,
        BigDecimal brokerage,
        BigDecimal stt,
        BigDecimal exchangeTxn,
        BigDecimal sebiFee,
        BigDecimal stampDuty,
        BigDecimal gst,
        BigDecimal totalCharges,
        BigDecimal netPl
) {
}
