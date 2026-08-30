package com.moneymaker.order.dto;

import com.fasterxml.jackson.annotation.JsonUnwrapped;
import com.moneymaker.entity.TradeOrder;

/**
 * A ledger row plus its rupee economics.
 *
 * <p>{@code GET /api/orders} used to return the raw {@link TradeOrder} entity.
 * It still does, field for field — {@link JsonUnwrapped} flattens it — so every
 * existing reader keeps working; {@code charges} is additive.
 *
 * <p>{@code charges} is null when the row cannot be costed: an OPEN position
 * (no exit leg yet), or a row written before changeset 029 that carries no
 * quantity. Reported as null rather than zero so the UI can say "not costed"
 * instead of implying the trade was free.
 */
public record TradeOrderView(
        @JsonUnwrapped TradeOrder order,
        TradeCharges charges
) {
}
