package com.moneymaker.strategy;

import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import org.springframework.stereotype.Component;

import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

/**
 * {@link Strategy6} plus one regime gate taken from the intraday regime study
 * (the 10:15 checkpoint), reshaped for a one-sided premium short — S28 in
 * {@code docs/STRATEGY_ANALYSIS_TODO.md} has the numbers:
 *
 * <p><b>First hour not against the leg.</b> For a signal bar that starts at or
 * after {@value #FIRST_HOUR_CHECKPOINT_TEXT}, the underlying's first-hour move
 * (session open → last bar before the checkpoint), signed in the leg's favour
 * and divided by ATR-14, must be at least
 * −{@value #FIRST_HOUR_MAX_AGAINST_ATR}: a CE is not sold into a morning that
 * rose more than a fifth of a day's range, a PE is not sold into one that fell
 * that much. Entries before the checkpoint — the opening-bar trades, the best
 * slice of the replay — are untouched, and every "cannot be judged" case
 * allows, the same convention as the 15-minute confirmation.</p>
 *
 * <p>What it is for: the strategy's losses live on days that trend
 * <i>against</i> the leg (Strategy 6: 84 such trades, −1,881 points, profit
 * factor 0.23, versus +1,866 on sideways days and +2,036 on favourable trends).
 * Nothing known at the open flags those days — the gap rule and the
 * expected-move level were tried and rejected (S28) — but the direction of the
 * first hour is the best partial tell for the afternoon: the 43 after-10:15
 * entries this gate removed were trend-against days 35% of the time against a
 * 14% base rate. Replay: 525 trades, +2,125 points, profit factor 1.31,
 * positive in all four half-years (Strategy 6: 561, +2,021, 1.28). The
 * threshold is flat from −0.1 to −0.3 ATR and the same with the 09:15 straddle
 * as the normaliser; ATR was chosen because the strategy already has the
 * underlying series and needs no straddle fetch.</p>
 *
 * <p>Everything else is Strategy 6, inherited: the 15-minute SMA-50
 * confirmation, the 14:45 cut-off, the stop-loss lock (declared via
 * {@link #stopLossLocksBookForDay()} and enforced by {@code OrderService}),
 * Strategy 2's slope filter and the baseline scan. Requires
 * {@code transaction_type = SELL}; changeset 047 seeds its
 * {@code strategy_defaults} as a copy of strategy 1's block; tagging it on a
 * rule is the operator's call (STRATEGIES.md).</p>
 *
 * <p>The checkpoint and the threshold are strategy identity, not
 * {@code TradeConfig} columns, for the same reason as Strategy 6's constants
 * (S27 open question (a)).</p>
 */
@Component
public class Strategy7 extends Strategy6 {

    public static final int ID = 7;

    /** End of the first hour on the standard 09:15 session. */
    public static final LocalTime FIRST_HOUR_CHECKPOINT = LocalTime.of(10, 15);
    static final String FIRST_HOUR_CHECKPOINT_TEXT = "10:15";

    /** Largest first-hour move against the leg, in ATR-14 units, that still admits an entry. */
    public static final double FIRST_HOUR_MAX_AGAINST_ATR = 0.20;

    public Strategy7(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    /**
     * Strategy 6's sell rules for this period with the first-hour gate appended
     * as a further required rule, so a blocked entry still names the earlier
     * rule that failed first. An empty pair stays empty (fail-closed period).
     */
    @Override
    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        TradeRules base = super.sellRulesFor(primarySmaPeriod);
        if (base == null || (base.required.isEmpty() && base.anyOf.isEmpty())) {
            return TradeRules.empty();
        }
        List<TradeRule> required = new ArrayList<>(base.required);
        required.add(TradeRule.named("firstHourNotAgainstOrUnknown", ctx -> {
            Double inFavourAtr = CommonRules.firstHourMoveInFavourAtr(ctx, FIRST_HOUR_CHECKPOINT);
            return inFavourAtr == null || inFavourAtr >= -FIRST_HOUR_MAX_AGAINST_ATR;
        }));
        return new TradeRules(required, base.anyOf);
    }
}
