package com.moneymaker.strategy;

import com.moneymaker.market.instrument.OptionInstrumentResolver;
import org.springframework.stereotype.Component;

/**
 * {@link Strategy9} tuned for the intraday form (optimisation of 2026-09-06,
 * S31 in {@code docs/STRATEGY_ANALYSIS_TODO.md}). Same rule, same chandelier
 * exit, same three gates; what differs is what the gates are set to and how
 * long the entry window stays open:
 * <ul>
 *   <li>{@code min_days_to_expiry} NULL — the expiry gate is off, so the
 *       Wednesday / Thursday entries Strategy 9 skips are back;</li>
 *   <li>{@code min_candle_close_position} 0.35 instead of 0.25;</li>
 *   <li>last entry bar 13:15 instead of 14:45 ({@link #entryCutoffMinutesBeforeCloseSignal}
 *       = 120 minutes before the 15:15 close signal).</li>
 * </ul>
 * The two thresholds live on this strategy's own {@code strategy_defaults} row
 * (changeset 050); the cut-off is strategy identity like Strategy 8's 30
 * minutes.
 *
 * <p>Replay (Python replica, dbeaver export, Jan-2024 → Dec-2025, ATM leg,
 * gross points): 714 trades, +4,609, avg +6.5, PF 1.6, max drawdown −207,
 * worst month −54, 2024 +2,651 / 2025 +1,957 — against Strategy 9's 602 /
 * +3,504 / +5.8 / 1.5 / −246 / −151 / 2,096 / 1,408. Chosen on those two
 * years; expect less. Everything Strategy 9 depends on (a 15-minute
 * {@code sma_timeframe} row, cached legs within ±200 of the session-open ATM
 * for the volume gate, no rule tag from the changeset) applies unchanged.</p>
 */
@Component
public class Strategy10 extends Strategy9 {

    public static final int ID = 10;

    /** Last admissible entry bar starts 120 minutes before the close signal: 13:15. */
    public static final int ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE_SIGNAL = 120;

    public Strategy10(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    @Override
    protected int entryCutoffMinutesBeforeCloseSignal() {
        return ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE_SIGNAL;
    }
}
