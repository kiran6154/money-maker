package com.moneymaker.strategy;

import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * {@link Strategy2} plus the three entry gates the 2024-2025 dbviewer replay
 * singled out (analysis 2026-09-05, see the S27 entry in
 * {@code docs/STRATEGY_ANALYSIS_TODO.md} for the numbers):
 *
 * <ol>
 *   <li><b>Higher-timeframe confirmation.</b> No SELL entry while the leg's
 *       own <b>15-minute</b> series says its SMA-50 is <i>not</i> in a
 *       whole-day down-trend ({@code SmaTrendCalculator}, {@code maxDeviations
 *       = 0}, on the newest settled 15-minute bar). Applies to every primary
 *       period and to 5- and 15-minute signals alike — a 5-minute cross only
 *       counts when the coarser series agrees. <i>Unknown allows:</i> before
 *       09:30 there is no settled 15-minute bar for the session, so the
 *       opening-bar entries (the replay's best slice) are judged on the
 *       5-minute evidence alone; see
 *       {@link CommonRules#higherTimeframeSmaDownTrending} for the full list
 *       of unknown cases.</li>
 *   <li><b>Entry cut-off.</b> The signal bar must start at or before the
 *       close-signal time minus 30 minutes — 14:45 on the standard session.
 *       Entries after 15:00 won 29% and lost 304 points over the replay; they
 *       are closed by the 15:15 signal before they can work.</li>
 *   <li><b>Stop-loss locks the book.</b> After a {@code STOP_LOSS} exit this
 *       strategy opens nothing further on that config for the rest of the
 *       session. Re-entries after a stop lost 583 points across 343 trades.
 *       This one is a ledger question, so it is declared here
 *       ({@link #stopLossLocksBookForDay()}) and enforced by
 *       {@code OrderService.handleSignal} with the other per-(config,
 *       strategy) caps — identical live and in replay.</li>
 * </ol>
 *
 * <p>Everything else — the scan, the premium sort, the cross gate, the
 * per-period down-trend rule, Strategy 2's {@code sma20SlopeNotUp}, the price
 * band, the 15:15 exit — is inherited unchanged. The 20-SMA slope filter is
 * kept because with these gates in place it raised the profit factor
 * (1.17 → 1.28) and was the only variant positive in every half-year; on its
 * own it was noise (S27).</p>
 *
 * <p><b>Config prerequisites.</b> {@code transaction_type = SELL}, like
 * strategies 1 and 2. The 15-minute confirmation series is fetched by
 * {@code AnalysisScheduler} because this bean declares it in
 * {@link #confirmationTimeframes()}; the config's own {@code sma_timeframe}
 * rows need not name 15 minutes. For {@code AUTO_DOWNTREND} generation the
 * strategy needs its {@code strategy_defaults} row and a
 * {@code sma_downtrend_rule_strategy} tag — see STRATEGIES.md.</p>
 *
 * <p>The three numbers below are strategy identity, deliberately not
 * {@code TradeConfig} columns (CLAUDE.md #9 — recorded as an open question in
 * S27): they are what makes a config tagged 6 different from one tagged 2.
 * Promote them to columns the day a second strategy wants different values.</p>
 */
@Component
public class Strategy6 extends Strategy2 {

    public static final int ID = 6;

    /** Interval of the leg's confirmation series, in minutes. */
    public static final int CONFIRMATION_TIMEFRAME_MINUTES = 15;

    /** SMA period whose whole-day down-trend flag is required on that series. */
    public static final int CONFIRMATION_SMA_PERIOD = 50;

    /**
     * Last admissible entry bar starts this many minutes before the close-signal
     * time: 15:15 − 30 = 14:45 on the standard session.
     */
    public static final int ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE_SIGNAL = 30;

    public Strategy6(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    @Override
    public Set<Integer> confirmationTimeframes() {
        return Set.of(CONFIRMATION_TIMEFRAME_MINUTES);
    }

    @Override
    public boolean stopLossLocksBookForDay() {
        return true;
    }

    /**
     * Strategy 2's sell rules for this period (baseline down-trend rule plus
     * {@code sma20SlopeNotUp}) with the two entry gates appended as further
     * <i>required</i> rules, in that order, so the {@code [tick]} log names the
     * baseline rule first when that is what failed.
     *
     * <p>A fully-empty pair is passed straight through: {@code RuleEngine}
     * fails it closed, and appending a rule would turn "this period is not
     * traded" into "traded whenever my gates pass" — the same guard
     * {@link Strategy2#sellRulesFor} applies.</p>
     */
    @Override
    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        TradeRules base = super.sellRulesFor(primarySmaPeriod);
        if (base == null || (base.required.isEmpty() && base.anyOf.isEmpty())) {
            return TradeRules.empty();
        }
        List<TradeRule> required = new ArrayList<>(base.required);
        required.add(TradeRule.named("htf15Sma50DownOrUnknown",
                ctx -> !Boolean.FALSE.equals(CommonRules.higherTimeframeSmaDownTrending(
                        ctx, CONFIRMATION_TIMEFRAME_MINUTES, CONFIRMATION_SMA_PERIOD))));
        required.add(TradeRule.named("entryAtOrBefore1445",
                ctx -> CommonRules.isAtOrBeforeEntryCutoff(ctx, ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE_SIGNAL)));
        return new TradeRules(required, base.anyOf);
    }
}
