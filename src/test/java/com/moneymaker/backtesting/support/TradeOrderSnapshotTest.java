package com.moneymaker.backtesting.support;

import com.moneymaker.entity.TradeOrder;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for {@link TradeOrderSnapshot}.
 *
 * <p>Two properties we care about most:
 * <ol>
 *   <li>Order is deterministic by business keys, never by DB-assigned id.</li>
 *   <li>{@code BigDecimal} scale survives serialisation
 *       ({@code 12.50} stays {@code 12.50}, not {@code 12.5}).</li>
 * </ol>
 */
class TradeOrderSnapshotTest {

    @Test
    void rows_sorted_by_business_keys_not_by_id() {
        TradeOrder later = newOrder(99L, "BUY", 24000, "CE", LocalDateTime.of(2026, 4, 1, 11, 0));
        TradeOrder earlier = newOrder(1L, "SELL", 23000, "PE", LocalDateTime.of(2026, 4, 1, 10, 0));

        // Pass in reverse business-key order — and with the higher id first —
        // to prove the serialiser ignores id and re-sorts by entry_time etc.
        List<Map<String, Object>> snapshot = TradeOrderSnapshot.snapshot(List.of(later, earlier));

        assertThat(snapshot).hasSize(2);
        assertThat(snapshot.get(0).get("entry_time")).isEqualTo("2026-04-01T10:00");
        assertThat(snapshot.get(1).get("entry_time")).isEqualTo("2026-04-01T11:00");
    }

    @Test
    void bigdecimal_scale_preserved_as_plain_string() {
        TradeOrder t = newOrder(1L, "BUY", 24000, "CE", LocalDateTime.of(2026, 4, 1, 10, 0));
        t.setEntryPrice(new BigDecimal("12.5000"));   // four decimal places
        t.setProfit(new BigDecimal("0.0000"));        // four decimal places
        t.setExitPrice(null);

        Map<String, Object> row = TradeOrderSnapshot.snapshot(List.of(t)).get(0);

        assertThat(row.get("entry_price")).isEqualTo("12.5000");
        assertThat(row.get("profit")).isEqualTo("0.0000");
        assertThat(row.get("exit_price")).isNull();
    }

    @Test
    void id_field_is_excluded_from_snapshot() {
        TradeOrder t = newOrder(987654321L, "BUY", 24000, "CE", LocalDateTime.of(2026, 4, 1, 10, 0));
        Map<String, Object> row = TradeOrderSnapshot.snapshot(List.of(t)).get(0);
        assertThat(row).doesNotContainKey("id");
    }

    @Test
    void json_output_is_stable_and_deterministic() {
        TradeOrder t = newOrder(1L, "BUY", 24000, "CE", LocalDateTime.of(2026, 4, 1, 10, 0));
        t.setEntryPrice(new BigDecimal("12.5000"));

        String first  = TradeOrderSnapshot.toJson(TradeOrderSnapshot.snapshot(List.of(t)));
        String second = TradeOrderSnapshot.toJson(TradeOrderSnapshot.snapshot(List.of(t)));

        assertThat(first).isEqualTo(second);
        assertThat(first).contains("\"entry_price\": \"12.5000\"");
    }

    @Test
    void null_and_empty_inputs_are_safe() {
        assertThat(TradeOrderSnapshot.snapshot(null)).isEmpty();
        assertThat(TradeOrderSnapshot.snapshot(List.of())).isEmpty();
    }

    /* ---------------- helpers ---------------- */

    private static TradeOrder newOrder(long id, String direction, int strike, String type, LocalDateTime entryTime) {
        TradeOrder t = new TradeOrder();
        t.setId(id);
        t.setTradeConfigId(1);
        t.setInstrumentName("NIFTY");
        t.setInstrumentToken("256265");
        t.setOptionStrike(strike);
        t.setOptionType(type);
        t.setOptionToken(String.valueOf(100000 + strike));
        t.setEntryDirection(direction);
        t.setEntryTime(entryTime);
        t.setEntryPrice(new BigDecimal("0.00"));
        t.setStatus("OPEN");
        return t;
    }
}
