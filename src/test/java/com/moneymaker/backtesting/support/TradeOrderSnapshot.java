package com.moneymaker.backtesting.support;

import com.moneymaker.entity.TradeOrder;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Deterministic, human-readable JSON-ish serialisation of {@link TradeOrder}
 * rows for parity comparisons.
 *
 * <p>Rows are sorted by business keys
 * {@code (entry_time, instrument_token, option_strike, option_type, entry_direction)}
 * — never by DB-assigned {@code id}, which varies between containers.
 *
 * <p>{@link BigDecimal} fields use {@code toPlainString()} so scale differences
 * ({@code 12.50} vs {@code 12.5000}) become visible diffs rather than silent
 * equality. The {@code id} column is intentionally dropped from the output —
 * it is a meaningless DB artefact for parity purposes.
 *
 * <p>Lenient comparison: a real test will compare expected JSON to actual
 * JSON with {@code usingRecursiveComparison()}; extra fields in actual are
 * tolerated. Missing fields fail. Schema-level coverage is enforced
 * separately by {@code ColumnCoverageTest} (M2).
 */
public final class TradeOrderSnapshot {

    private TradeOrderSnapshot() {}

    /**
     * Produces a sorted {@code List<Map>} representation of the given rows.
     * Suitable for AssertJ {@code usingRecursiveComparison()} or JSON serialisation.
     */
    public static List<Map<String, Object>> snapshot(List<TradeOrder> rows) {
        if (rows == null) return List.of();
        return rows.stream()
                .filter(java.util.Objects::nonNull)
                .sorted(BUSINESS_KEY_ORDER)
                .map(TradeOrderSnapshot::toMap)
                .toList();
    }

    /**
     * Pretty-prints the snapshot as JSON. Caller responsibility: write to a
     * file or feed to AssertJ. Format: one row per object, fields in fixed
     * alphabetical order, indented 2 spaces. Hand-rolled so we don't pull
     * in Jackson just for tests (Spring Boot test brings it transitively
     * anyway, but using a hand format keeps the diff output stable across
     * Jackson version bumps).
     */
    public static String toJson(List<Map<String, Object>> snapshot) {
        StringBuilder sb = new StringBuilder();
        sb.append("[\n");
        for (int i = 0; i < snapshot.size(); i++) {
            sb.append("  {\n");
            Map<String, Object> row = snapshot.get(i);
            int j = 0;
            for (Map.Entry<String, Object> e : row.entrySet()) {
                sb.append("    \"").append(e.getKey()).append("\": ").append(formatValue(e.getValue()));
                if (++j < row.size()) sb.append(',');
                sb.append('\n');
            }
            sb.append("  }");
            if (i < snapshot.size() - 1) sb.append(',');
            sb.append('\n');
        }
        sb.append("]\n");
        return sb.toString();
    }

    /* ---------------- helpers ---------------- */

    /** Sort by deterministic business keys, never by DB-assigned id. */
    private static final Comparator<TradeOrder> BUSINESS_KEY_ORDER = Comparator
            .comparing((TradeOrder t) -> nullSafe(t.getEntryTime()), Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(t -> nullSafe(t.getInstrumentToken()), Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(t -> nullSafe(t.getOptionStrike()), Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(t -> nullSafe(t.getOptionType()), Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(t -> nullSafe(t.getEntryDirection()), Comparator.nullsLast(Comparator.naturalOrder()));

    private static <T> T nullSafe(T v) { return v; }

    /**
     * Fields in alphabetical order so a JSON diff highlights *value* changes,
     * not noise from reordered keys. {@code id} excluded by design.
     */
    private static Map<String, Object> toMap(TradeOrder t) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("entry_broker_order_id", t.getEntryBrokerOrderId());
        m.put("entry_direction",       t.getEntryDirection());
        m.put("entry_price",           plainString(t.getEntryPrice()));
        m.put("entry_reason",          t.getEntryReason());
        m.put("entry_time",            isoString(t.getEntryTime()));
        m.put("exit_broker_order_id",  t.getExitBrokerOrderId());
        m.put("exit_price",            plainString(t.getExitPrice()));
        m.put("exit_reason",           t.getExitReason());
        m.put("exit_time",             isoString(t.getExitTime()));
        m.put("fill_status",           t.getFillStatus());
        m.put("instrument_name",       t.getInstrumentName());
        m.put("instrument_token",      t.getInstrumentToken());
        m.put("last_monitored_at",     isoString(t.getLastMonitoredAt()));
        m.put("last_monitored_price",  plainString(t.getLastMonitoredPrice()));
        m.put("option_strike",         t.getOptionStrike());
        m.put("option_token",          t.getOptionToken());
        m.put("option_type",           t.getOptionType());
        m.put("peak_loss",             plainString(t.getPeakLoss()));
        m.put("peak_profit",           plainString(t.getPeakProfit()));
        m.put("profit",                plainString(t.getProfit()));
        m.put("status",                t.getStatus());
        m.put("stop_loss_at_entry",    plainString(t.getStopLossAtEntry()));
        m.put("strategy_id",           t.getStrategyId());
        m.put("target_at_entry",       plainString(t.getTargetAtEntry()));
        m.put("trade_config_id",       t.getTradeConfigId());
        return m;
    }

    /** Stable string for BigDecimal — preserves scale. {@code null} → {@code null}. */
    private static String plainString(BigDecimal v) {
        return v == null ? null : v.toPlainString();
    }

    /** ISO-8601 for LocalDateTime. {@code null} → {@code null}. */
    private static String isoString(LocalDateTime v) {
        return v == null ? null : v.toString();
    }

    /** JSON-ish literal for the value. Strings quoted, nulls as {@code null}, numbers raw. */
    private static String formatValue(Object v) {
        if (v == null) return "null";
        if (v instanceof Number) return v.toString();
        // Strings, BigDecimal-as-plain-string, ISO timestamps — all quoted.
        return "\"" + v.toString().replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }
}
