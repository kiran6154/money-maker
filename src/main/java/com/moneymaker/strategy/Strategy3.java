package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.RuleEngine;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * {@link Strategy1} with the signal directions inverted: a <b>BUY entry</b>
 * where the baseline sells, and a SELL at the market-close time where the
 * baseline buys.
 *
 * <p>Everything is the baseline's rule set mirrored onto the leg being scanned:
 * the cross gate flips to {@code open < SMA && close > SMA}, the per-period
 * {@code isSmaNNDownTrending} requirement flips to {@code isSmaNNUpTrending},
 * and the ungated {@code isMarketCloseTime} exit is emitted as SELL instead of
 * BUY (see {@link RuleEngine#decideBuyEntry}). Scanning, premium sort, price
 * band and cache-key matching are inherited unchanged.</p>
 *
 * <h3>How this expresses "PE sell becomes CE buy"</h3>
 * <p>A strategy only scans and trades its own config's {@code trading_side} —
 * the ledger requires the traded option type to match the config. So the
 * pairing is done at config level: tag the <b>CE</b>-side config with this
 * strategy, and at the market moment the sibling PE config fires Strategy 1's
 * cross-down SELL (index rising, PE premium falling), the CE leg is the mirror
 * image — premium crossing <i>up</i> through its own SMA, SMA up-trending —
 * and this strategy fires BUY on it. The equivalence is structural, not
 * tick-exact: each leg is judged on its own series, so the two signals land on
 * the same market move but not necessarily the same bar — recorded as
 * S19 in STRATEGY_ANALYSIS_TODO.md.</p>
 *
 * <h3>Config prerequisites</h3>
 * <p>The config must have {@code transaction_type = BUY}. On a SELL config this
 * strategy's entries would be discarded by {@code OrderService} (direction
 * mismatch) while its 15:15 SELL <i>exit</i> signal would be mistaken for a
 * fresh short entry — the guard at the top of
 * {@link AbstractSmaCrossStrategy#execute} refuses to scan such a config at
 * all. That is a mis-configuration guard, not a trading rule: a SELL config
 * tagged with this strategy has no meaningful interpretation.</p>
 *
 * <h3>What does NOT carry over automatically</h3>
 * <p>Period <i>enablement</i> tracks the baseline (a period with no baseline
 * sell rules stays fail-closed here — uncommenting the SMA-20 case there
 * enables it here too), but rule <i>content</i> is mirrored by hand: a new
 * predicate added to the baseline sell rules later will not acquire an inverse
 * here on its own.</p>
 */
@Component
public class Strategy3 extends AbstractSmaCrossStrategy {

    public static final int ID = 3;

    public Strategy3(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    @Override
    protected TradeAction entryAction() {
        return TradeAction.BUY;
    }

    /**
     * Entry rules: the baseline sell rules for this period, mirrored — the
     * required {@code isSmaNNDownTrending} becomes {@code isSmaNNUpTrending}.
     *
     * <p>Enablement is derived from the baseline rather than from a private
     * period list: a period the baseline fails closed (no {@code case} branch,
     * or one commented out) stays fail-closed here, so the two strategies can
     * never disagree about which periods are tradeable.</p>
     */
    @Override
    protected TradeRules buyRulesFor(Integer primarySmaPeriod) {
        TradeRules baseSell = super.sellRulesFor(primarySmaPeriod);
        if (baseSell == null || (baseSell.required.isEmpty() && baseSell.anyOf.isEmpty())) {
            // "No rules defined" is fail-closed by design — keep it that way.
            return TradeRules.empty();
        }
        final Integer period = primarySmaPeriod;
        List<TradeRule> required = new ArrayList<>();
        required.add(TradeRule.named("isSma" + period + "UpTrending",
                ctx -> CommonRules.isSmaUpTrending(ctx.candle, period)));
        return new TradeRules(required, new ArrayList<>());
    }

    /**
     * Exit rules: exactly the baseline's buy rules (the ungated
     * {@code isMarketCloseTime} leg) — {@link RuleEngine#decideBuyEntry} emits
     * them as SELL, which on a BUY config is the exit direction.
     */
    @Override
    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        return super.buyRulesFor(primarySmaPeriod);
    }
}
