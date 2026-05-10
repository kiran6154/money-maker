package com.moneymaker.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * Latest known fill state for a broker-side order, returned by
 * {@code OrderPlacementService.syncFill(brokerOrderId)}.
 *
 * <p>{@link #status} is the placement-service-normalised status (typically
 * {@code COMPLETE} / {@code PENDING} / {@code REJECTED} / {@code CANCELLED}),
 * not the broker's raw status string.
 *
 * <p>{@link #averagePrice} is the volume-weighted average fill price across
 * partial fills. {@code null} until at least one fill has happened.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class FillSnapshot {
    private String status;
    private BigDecimal averagePrice;
    private Integer filledQuantity;
}
