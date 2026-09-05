package com.moneymaker.tradeconfig.generation;

import java.util.List;

/**
 * The seven comparison books the Pressure spec asks for, as data.
 *
 * <p>A "book" is one complete way of expressing the same signal stream. All
 * seven see identical entry decisions — same spot bars, same pressure scores,
 * same clock — and differ only in <i>what instrument the trade is put on</i>.
 * That is the whole point: laid side by side they separate how good the signal
 * is from how good the chosen expression of it is.</p>
 *
 * <h3>Why each book is two configs</h3>
 * {@code trade_config.trading_side} is single-valued, so a book that acts on
 * both down-pressure and up-pressure needs one config per leg. They share a
 * {@code book_id}, and {@code OrderService}'s cross-config cap is what keeps
 * "ONE position at a time" true across the pair — without it each leg would
 * hold its own budget and the two could run concurrently.
 *
 * <pre>
 *   P_down &gt;= 3   SELL CE   or   BUY PE       (or SHORT spot)
 *   P_up   &gt;= 3   SELL PE   or   BUY CE       (or LONG  spot)
 * </pre>
 *
 * <h3>The SPOT book</h3>
 * The baseline. Same signals and same +50 / -50 / +25 brackets, but priced in
 * index points on the underlying rather than on a premium — see
 * {@code SyntheticUnderlyingContract}. Its two configs are the short and long
 * halves rather than CE and PE. It is where the spec's headline sanity figures
 * come from, and its charges are zero because there is no contract note for a
 * hypothetical index trade.
 */
public record PressureBook(String bookId, boolean underlyingLeg,
                           String transactionType, Integer strikeOffsetPoints) {

    /** The leg descriptors this book needs, in the order they are created. */
    public record Leg(String tradingSide, String transactionType) {
    }

    /**
     * The two configs this book expands into.
     *
     * <p>For an option book the split is by option side and the direction is
     * constant. For the spot book the split is by <i>direction</i> on a single
     * synthetic contract, which is why the side reads {@code SPOT} on both — the
     * short leg takes down-pressure, the long leg takes up-pressure, and
     * {@code OrderService} keeps them apart because its open-position lookup is
     * scoped to a single {@code trade_config_id}.</p>
     */
    public List<Leg> legs() {
        if (underlyingLeg) {
            return List.of(new Leg("SPOT", "SELL"), new Leg("SPOT", "BUY"));
        }
        return List.of(new Leg("CE", transactionType), new Leg("PE", transactionType));
    }

    /**
     * All seven books, in the order the summary table reports them.
     *
     * <p>ITM offsets are positive: 300 means "300 points in the money", which
     * resolves to {@code ATM-300} for a CE and {@code ATM+300} for a PE. ATM is
     * offset 0. There are deliberately no OTM books — the spec names ITM300,
     * ITM200 and ATM and says not to invent extra ones.</p>
     */
    public static List<PressureBook> all() {
        return List.of(
                new PressureBook("SPOT", true, null, null),
                new PressureBook("SELL_ITM300", false, "SELL", 300),
                new PressureBook("SELL_ITM200", false, "SELL", 200),
                new PressureBook("SELL_ATM", false, "SELL", 0),
                new PressureBook("BUY_ITM300", false, "BUY", 300),
                new PressureBook("BUY_ITM200", false, "BUY", 200),
                new PressureBook("BUY_ATM", false, "BUY", 0));
    }

    /** Looks up one book by id, or null. Used to scope a generation run. */
    public static PressureBook byId(String id) {
        for (PressureBook b : all()) {
            if (b.bookId().equalsIgnoreCase(id)) return b;
        }
        return null;
    }
}
