package com.moneymaker.order.service;

import com.moneymaker.entity.TradeOrder;
import com.moneymaker.market.instrument.SyntheticUnderlyingContract;
import com.moneymaker.order.dto.TradeCharges;
import com.moneymaker.repository.ChargeRateRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * A spot-proxy row must never be costed as an option.
 *
 * <p><b>The bug this pins.</b> {@code compute} reads {@code entry_price} as a
 * <i>premium</i>. On a Pressure SPOT baseline row that field holds a NIFTY index
 * level — around 21,600 — so at a lot of 75 the method computed roughly 1.6
 * crore of "turnover" per leg and levied STT, exchange transaction and GST on
 * it. On a 78-trade January slice that invented about ₹3,150 of charges,
 * which left gross P&amp;L correct and net P&amp;L unusable.
 *
 * <p>Reported by the user 2026-09-05 against a run of the SPOT book, and it
 * reached further than the Pressure export: {@code /api/orders},
 * {@code TradeOrderView} and the day summary all cost rows through this method,
 * so every one of them would have shown the same invented number.</p>
 */
class TradeChargeServiceSpotRowTest {

    private static TradeChargeService.RateResolver rates() {
        ChargeRateRepository repo = mock(ChargeRateRepository.class);
        // No rows: every rate resolves to zero. Deliberate — the assertions below
        // are about WHETHER a row is costed at all, not about rate values, and a
        // zero-rate resolver makes an accidental pass impossible to mistake for
        // a real one (a costed option row would still produce a non-null object).
        when(repo.findBySegmentOrderByChargeTypeAscEffectiveFromAsc(org.mockito.ArgumentMatchers.anyString()))
                .thenReturn(List.of());
        return new TradeChargeService(repo).resolver();
    }

    private static TradeOrder order(String optionToken, String optionType, BigDecimal entry, BigDecimal exit) {
        TradeOrder o = new TradeOrder();
        o.setOptionToken(optionToken);
        o.setOptionType(optionType);
        o.setQuantity(75);
        o.setEntryDirection("SELL");
        o.setEntryTime(LocalDateTime.of(2024, 1, 2, 10, 0));
        o.setEntryPrice(entry);
        o.setExitPrice(exit);
        o.setProfit(entry.subtract(exit));
        return o;
    }

    @Test
    @DisplayName("a spot-proxy row is NOT costed — null, not a fabricated charge")
    void spotRowIsNotCosted() {
        TradeOrder spot = order(SyntheticUnderlyingContract.TOKEN, SyntheticUnderlyingContract.SIDE,
                new BigDecimal("21636.80"), new BigDecimal("21586.80"));

        TradeCharges charges = new TradeChargeService(mock(ChargeRateRepository.class))
                .compute(spot, rates());

        assertThat(charges)
                .as("a hypothetical index trade has no contract note, so it cannot be costed")
                .isNull();
    }

    @Test
    @DisplayName("null, not zero — 'cannot be costed' is not the same claim as 'was free'")
    void spotRowIsNullNotZero() {
        // Downstream already reads null as "not costed" (TradeOrderView documents
        // it). Zero would assert the trade genuinely cost nothing, which for a
        // baseline book is the wrong claim to make in a shared view. The Pressure
        // summary renders it as 0 in its own rupee columns, but that is a
        // presentation choice made where the context is known.
        TradeOrder spot = order(SyntheticUnderlyingContract.TOKEN, "SPOT",
                new BigDecimal("21636.80"), new BigDecimal("21686.80"));

        assertThat(new TradeChargeService(mock(ChargeRateRepository.class)).compute(spot, rates()))
                .isNull();
    }

    @Test
    @DisplayName("a real option row is still costed — the guard is narrow")
    void optionRowIsStillCosted() {
        // The guard keys on the synthetic contract id alone, so nothing about a
        // genuine leg changes. Without this assertion the test above would pass
        // just as well if compute() had been broken for everything.
        TradeOrder option = order("HIST:NIFTY:NFO:2024-01-04:21600:CE", "CE",
                new BigDecimal("180.00"), new BigDecimal("130.00"));

        TradeCharges charges = new TradeChargeService(mock(ChargeRateRepository.class))
                .compute(option, rates());

        assertThat(charges).isNotNull();
        assertThat(charges.quantity()).isEqualTo(75);
        // 50 points x 75 on a SELL entry.
        assertThat(charges.grossPl()).isEqualByComparingTo("3750.00");
    }
}
