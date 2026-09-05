package com.moneymaker.backtesting;

import com.moneymaker.entity.TradeOrder;
import com.moneymaker.market.instrument.SyntheticUnderlyingContract;
import com.moneymaker.order.dto.TradeCharges;
import com.moneymaker.order.service.TradeChargeService;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.strategy.Strategy5;
import com.moneymaker.tradeconfig.generation.PressureBook;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Turns a completed Pressure replay into the three artefacts the spec asks for:
 * a per-trade CSV, a per-book summary, and the CE / PE wing split.
 *
 * <h3>Two charge columns, not one</h3>
 * Every trade is costed twice and both numbers are reported side by side:
 *
 * <ul>
 *   <li><b>{@code charges_broker}</b> — {@code TradeChargeService} against the
 *       seeded {@code charge_rate} rows. These are this system's own broker
 *       assumptions (Zerodha: 20/leg or 0.03% of turnover, whichever is lower)
 *       and they are what every other strategy's net P&amp;L in this codebase is
 *       measured with.</li>
 *   <li><b>{@code charges_spec}</b> — the flat schedule the Pressure spec names
 *       (40 round trip, 0.0495% exchange pre-October). Computed here, from the
 *       spec, and stored nowhere.</li>
 * </ul>
 *
 * <p>They differ by roughly 25-30 rupees a trade, dominated by brokerage: at an
 * ITM300 premium the percentage rule wins and this system charges about 16 round
 * trip where the spec charges 40. Over 1,560 trades that is around 44,000 rupees
 * — about 30% of the spec's implied charge total, so which one you read is not a
 * rounding question.
 *
 * <p>The alternative was to correct the {@code charge_rate} rows to match the
 * spec, and that was rejected: those rows are global and date-effective, so
 * editing them silently restates the net P&amp;L of every historical trade
 * strategies 1-4 have ever produced. Reporting both leaves the existing ledger
 * untouched and still lets the Pressure books be compared against the spec's own
 * figures. Neither column is "the" answer; the spec column is for reconciling
 * against the reference run, the broker column is for what this desk would
 * actually have paid.
 *
 * <h3>The SPOT book is costed at zero</h3>
 * It is a hypothetical index trade with no contract note. Applying an option's
 * charge schedule to it would invent a cost that does not exist, and the spec
 * reports it gross for exactly that reason.
 */
@Slf4j
@Service
public class PressureExportService {

    private final TradeOrderRepository tradeOrderRepository;
    private final TradeChargeService chargeService;

    public PressureExportService(TradeOrderRepository tradeOrderRepository,
                                 TradeChargeService chargeService) {
        this.tradeOrderRepository = tradeOrderRepository;
        this.chargeService = chargeService;
    }

    /** One book's aggregate line. */
    public record BookSummary(String book, int n, double winRate, double meanPoints,
                              double profitFactor, BigDecimal gross,
                              BigDecimal chargesBroker, BigDecimal netBroker,
                              BigDecimal chargesSpec, BigDecimal netSpec) {
    }

    /** One book's CE / PE split. */
    public record WingSplit(String book, String wing, int n, double winRate,
                            double meanPoints, BigDecimal gross) {
    }

    /** Everything a run produces. */
    public record Report(List<String> csvRows, List<BookSummary> summary, List<WingSplit> wings) {
    }

    @Transactional(readOnly = true)
    public Report build(LocalDate from, LocalDate to) {
        List<TradeOrder> orders = tradeOrderRepository.findByStrategyIdAndEntryTimeBetweenOrderByEntryTimeAsc(
                Strategy5.ID, from.atStartOfDay(), to.plusDays(1).atStartOfDay().minusNanos(1));

        TradeChargeService.RateResolver rates = chargeService.resolver();
        Map<Integer, String> bookByConfig = bookIdsFor(orders);

        List<String> csv = new ArrayList<>();
        csv.add(String.join(",",
                "book", "wing", "entry_time", "exit_time", "strike", "expiry",
                "direction", "entry_px", "exit_px", "exit_reason", "points", "qty",
                "gross", "charges_broker", "net_broker", "charges_spec", "net_spec"));

        Map<String, Agg> byBook = new LinkedHashMap<>();
        Map<String, Agg> byWing = new LinkedHashMap<>();

        for (TradeOrder o : orders) {
            String book = bookByConfig.getOrDefault(o.getTradeConfigId(), "UNKNOWN");
            boolean spot = SyntheticUnderlyingContract.isSyntheticUnderlying(o.getOptionToken());
            String wing = spot
                    ? ("SELL".equalsIgnoreCase(o.getEntryDirection()) ? "SHORT" : "LONG")
                    : o.getOptionType();

            BigDecimal points = o.getProfit() == null ? BigDecimal.ZERO : o.getProfit();
            int qty = o.getQuantity() == null ? 0 : o.getQuantity();
            BigDecimal gross = points.multiply(BigDecimal.valueOf(qty));

            // Broker-rate charges: null for a row that cannot be costed (still
            // OPEN, or pre-029 with no quantity), zero for the spot book.
            TradeCharges tc = spot ? null : chargeService.compute(o, rates);
            BigDecimal chargesBroker = spot || tc == null ? BigDecimal.ZERO : tc.totalCharges();
            BigDecimal chargesSpec = spot ? BigDecimal.ZERO : PressureSpecCharges.forTrade(o);

            csv.add(String.join(",",
                    book, nz(wing), str(o.getEntryTime()), str(o.getExitTime()),
                    spot ? "" : str(o.getOptionStrike()), "",
                    nz(o.getEntryDirection()), str(o.getEntryPrice()), str(o.getExitPrice()),
                    nz(o.getExitReason()), points.toPlainString(), String.valueOf(qty),
                    gross.toPlainString(), chargesBroker.toPlainString(),
                    gross.subtract(chargesBroker).toPlainString(),
                    chargesSpec.toPlainString(),
                    gross.subtract(chargesSpec).toPlainString()));

            byBook.computeIfAbsent(book, k -> new Agg()).add(points, gross, chargesBroker, chargesSpec);
            byWing.computeIfAbsent(book + "|" + nz(wing), k -> new Agg()).add(points, gross, chargesBroker, chargesSpec);
        }

        List<BookSummary> summary = new ArrayList<>();
        for (PressureBook b : PressureBook.all()) {
            Agg a = byBook.get(b.bookId());
            if (a == null) continue;
            summary.add(a.toSummary(b.bookId()));
        }
        // Any book not in the canonical list (a hand-made config) still gets a row
        // rather than vanishing from a report that claims to cover the run.
        for (Map.Entry<String, Agg> e : byBook.entrySet()) {
            if (PressureBook.byId(e.getKey()) == null) {
                summary.add(e.getValue().toSummary(e.getKey()));
            }
        }

        List<WingSplit> wings = new ArrayList<>();
        for (Map.Entry<String, Agg> e : byWing.entrySet()) {
            String[] parts = e.getKey().split("\\|", 2);
            Agg a = e.getValue();
            wings.add(new WingSplit(parts[0], parts.length > 1 ? parts[1] : "",
                    a.n, a.winRate(), a.meanPoints(), a.gross));
        }

        log.info("[pressure-export] {} .. {} — {} trade(s) across {} book(s)",
                from, to, orders.size(), summary.size());
        return new Report(csv, summary, wings);
    }

    /**
     * Book label per config id, read from {@code trade_config}.
     *
     * <p>Resolved at report time rather than stamped on the order, for the
     * reason given on {@code TradeConfig.bookId}: a book is a bucket in a
     * measurement run, and denormalising it into the permanent ledger would
     * outlive the run that gave it meaning.</p>
     */
    private Map<Integer, String> bookIdsFor(List<TradeOrder> orders) {
        Map<Integer, String> out = new LinkedHashMap<>();
        if (orders.isEmpty()) return out;
        List<Integer> ids = orders.stream().map(TradeOrder::getTradeConfigId).distinct().toList();
        for (Object[] row : tradeOrderRepository.findBookIdsForConfigs(ids)) {
            if (row == null || row.length < 2 || row[0] == null) continue;
            out.put(((Number) row[0]).intValue(), row[1] == null ? "UNKNOWN" : row[1].toString());
        }
        return out;
    }

    /** Running totals for one bucket. */
    private static final class Agg {
        int n;
        int wins;
        BigDecimal points = BigDecimal.ZERO;
        BigDecimal gross = BigDecimal.ZERO;
        BigDecimal chargesBroker = BigDecimal.ZERO;
        BigDecimal chargesSpec = BigDecimal.ZERO;
        BigDecimal grossWins = BigDecimal.ZERO;
        BigDecimal grossLosses = BigDecimal.ZERO;

        void add(BigDecimal pts, BigDecimal g, BigDecimal cb, BigDecimal cs) {
            n++;
            if (pts.signum() > 0) {
                wins++;
                grossWins = grossWins.add(g);
            } else {
                grossLosses = grossLosses.add(g.abs());
            }
            points = points.add(pts);
            gross = gross.add(g);
            chargesBroker = chargesBroker.add(cb);
            chargesSpec = chargesSpec.add(cs);
        }

        double winRate() {
            return n == 0 ? 0d : round2(100d * wins / n);
        }

        double meanPoints() {
            return n == 0 ? 0d : round2(points.doubleValue() / n);
        }

        /**
         * Gross profit divided by gross loss. Infinite when there are no losses,
         * reported as 0 when there are no trades at all — the two are different
         * and a caller reading a bare number should be able to tell them apart
         * from {@code n}.
         */
        double profitFactor() {
            if (grossLosses.signum() == 0) return grossWins.signum() == 0 ? 0d : Double.POSITIVE_INFINITY;
            return round2(grossWins.doubleValue() / grossLosses.doubleValue());
        }

        BookSummary toSummary(String book) {
            return new BookSummary(book, n, winRate(), meanPoints(), profitFactor(), gross,
                    chargesBroker, gross.subtract(chargesBroker),
                    chargesSpec, gross.subtract(chargesSpec));
        }

        private static double round2(double v) {
            return BigDecimal.valueOf(v).setScale(2, RoundingMode.HALF_UP).doubleValue();
        }
    }

    private static String str(Object v) {
        return v == null ? "" : v.toString();
    }

    private static String nz(String v) {
        return v == null ? "" : v;
    }

    private static String str(LocalDateTime v) {
        return v == null ? "" : v.toString();
    }
}
