package com.moneymaker.strategy;

import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.TradeRule;
import com.moneymaker.strategy.rules.TradeRules;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * {@link Strategy1} plus one extra sell-side filter: <b>no SELL entry while the
 * 20-period SMA is sloping upward</b>, whatever the config's own SMA period is.
 *
 * <p>Everything else — which legs are scanned, the premium sort, the
 * {@code open > SMA && close < SMA} cross gate, the per-period down-trend rule,
 * the entry price band, the end-of-day buy exit — is inherited unchanged from
 * {@link AbstractSmaCrossStrategy}, so a config switched from
 * {@code stratergy_id = 1} to {@code 2} differs in exactly one respect: some of
 * its sells no longer fire.</p>
 *
 * <h3>What the filter does and does not touch</h3>
 * <ul>
 *   <li><b>Sell only.</b> The buy side is untouched. On the SELL configs this
 *       strategy is written for, BUY is the <i>exit</i> leg (the 15:15 close),
 *       and gating that on a trend condition would strand open positions until
 *       stop-loss or the end-of-day force-close.</li>
 *   <li><b>Every SMA period.</b> The rule is appended by
 *       {@link #sellRulesFor(Integer)} rather than to individual
 *       {@code sellRulesForNN()} builders, so it applies to 50 / 100 / 200 / 500
 *       — and to 20 or any period enabled later — without further edits.</li>
 *   <li><b>A period with no baseline rules stays untradeable.</b> A fully-empty
 *       {@link TradeRules} is passed straight through instead of being wrapped:
 *       {@code RuleEngine} fails it closed on purpose, and appending a required
 *       rule to it would flip "never trade this period" into "trade it whenever
 *       the slope is flat or down".</li>
 * </ul>
 */
@Component
public class Strategy2 extends AbstractSmaCrossStrategy {

    public static final int ID = 2;

    public Strategy2(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    /**
     * The baseline sell rules for this period with {@code sma20SlopeNotUp}
     * appended as an additional <i>required</i> rule.
     *
     * <p>Appended last so the {@code [tick]} log still names the period's own
     * down-trend rule first when that is what failed — the slope rule only shows
     * up as the failing one when it is genuinely the reason the entry was
     * blocked.</p>
     */
    @Override
    protected TradeRules sellRulesFor(Integer primarySmaPeriod) {
        TradeRules base = super.sellRulesFor(primarySmaPeriod);
        if (base == null || (base.required.isEmpty() && base.anyOf.isEmpty())) {
            // "No rules defined" is fail-closed by design — keep it that way.
            return TradeRules.empty();
        }
        List<TradeRule> required = new ArrayList<>(base.required);
        required.add(TradeRule.named("sma20SlopeNotUp",
                ctx -> !CommonRules.isSma20SlopeUp(ctx)));
        return new TradeRules(required, base.anyOf);
    }
}
