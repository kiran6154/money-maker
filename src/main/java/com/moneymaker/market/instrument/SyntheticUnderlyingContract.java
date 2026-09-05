package com.moneymaker.market.instrument;

/**
 * The pseudo-contract a {@code trade_config.underlying_leg = true} config trades.
 *
 * <h3>What it is</h3>
 * The Pressure spec's SPOT baseline book takes the same signals, the same clock
 * and the same +50 / -50 / +25 brackets as the option books, but prices entry
 * and exit in <b>index points</b> off the spot series. It is the row that
 * separates "how good is the signal" from "how good are the option mechanics",
 * and it is where the spec's headline sanity figures (1,560 trades, 64.2% WR,
 * +5.23 pts, PF 1.35) come from.
 *
 * <h3>Why it is faked as a contract rather than run outside the ledger</h3>
 * {@code trade_order} is shaped for options — strike, right, contract id — and
 * {@code PositionMonitorService.currentQuote} resolves a price by contract id. A
 * spot trade has none of those. The two ways out were to invent one narrow
 * pseudo-contract, or to run the book in a separate in-memory walker with its
 * own copy of the exit rules.
 *
 * <p>This is the first. The second would mean a second implementation of the
 * target / stop / trail / time-stop / flatten logic that has to stay in step
 * with {@code PositionService} forever — precisely the duplication CLAUDE.md
 * invariant 8 exists to prevent — and it would put the baseline book in a
 * different table from the six books it exists to be compared against. One
 * labelled special case is the cheaper honesty.</p>
 *
 * <h3>How it works with zero changes to the monitor</h3>
 * {@code AnalysisScheduler} caches the spot series into the strike cache under a
 * key whose contract segment is {@link #TOKEN}. {@code SharedData.latestCachedCandle}
 * matches on exactly that segment, so {@code BacktestingPositionMonitorService}
 * finds and quotes it without knowing anything about spot — it sees a contract
 * like any other. Nothing in the position or order layer was modified for this.
 *
 * <h3>Charges</h3>
 * {@code TradeChargeService} costs an option premium turnover. A spot-points
 * book has no contract note, so its charges are meaningless and the export
 * reports them as zero rather than inventing an option's costs for a
 * hypothetical index trade.
 */
public final class SyntheticUnderlyingContract {

    private SyntheticUnderlyingContract() {
    }

    /**
     * Contract-id segment. Deliberately hyphenated, not piped: the strike cache
     * key is pipe-delimited and parsed positionally by
     * {@code SharedData.latestCachedCandle} and {@code OrderService.ParsedKey},
     * so a pipe inside the token would shift every later segment.
     */
    public static final String TOKEN = "NIFTY-SPOT";

    /**
     * Side segment. Not {@code CE} or {@code PE} — those are read as real option
     * sides by {@code OrderService}'s same-side cap and by the ledger's
     * {@code option_type} column, and a spot row must not be counted against
     * either wing's budget.
     */
    public static final String SIDE = "SPOT";

    /**
     * Strike segment. Zero rather than null: the cache key is positional and an
     * empty segment would collapse two adjacent delimiters, leaving a 6-part key
     * that {@code ParsedKey.from} rejects outright.
     */
    public static final int STRIKE = 0;

    /** True when this ledger row is a spot baseline trade rather than an option. */
    public static boolean isSyntheticUnderlying(String optionToken) {
        return TOKEN.equals(optionToken);
    }
}
