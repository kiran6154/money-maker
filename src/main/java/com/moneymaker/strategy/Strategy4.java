package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import org.springframework.stereotype.Component;

/**
 * {@link Strategy1}'s detection, inverted at <b>execution</b>: the sell signal
 * is taken as-is — cross-down (<code>open &gt; SMA &amp;&amp; close &lt; SMA</code>)
 * plus the period's {@code isSmaNNDownTrending} flag, on the very same legs —
 * but the order placed on it is a <b>BUY</b>. The close-time BUY exit is
 * likewise emitted as the SELL that closes the long.
 *
 * <p>Nothing about the rule sets is overridden — {@code sellRulesFor} /
 * {@code buyRulesFor} are the inherited baseline, so this strategy detects on
 * exactly the ticks Strategy 1 does, config for config, leg for leg. The whole
 * identity is {@link #mapAction}: detected SELL → emitted BUY, detected BUY →
 * emitted SELL. Brackets need no special handling — target, stop-loss, the
 * ceiling and the trailing ladder all key off {@code entry_direction} in
 * {@code OrderService} / {@code PositionService}, so the config's same numbers
 * apply on the long side (SL fires when the premium falls, target when it
 * rises).</p>
 *
 * <h3>Contrast with {@link Strategy3}</h3>
 * <p>Strategy 3 <i>mirrors the detection</i> onto the traded leg (cross-up +
 * up-trend → BUY): same market view as the baseline's sell, expressed long on
 * the opposite-side config. Strategy 4 <i>keeps the detection</i> and fades it:
 * it buys the very option whose premium just crossed down in a day-long
 * downtrend — long against the detected momentum, with theta also against the
 * position. That is the user's specified design (2026-09-04), and its
 * economics are deliberately left to measurement — see S20 in
 * STRATEGY_ANALYSIS_TODO.md.</p>
 *
 * <h3>Config prerequisites</h3>
 * <p>{@code transaction_type = BUY}, enforced by the guard at the top of
 * {@link AbstractSmaCrossStrategy#execute} (the emitted entry here is
 * {@code mapAction(SELL) = BUY}). On a SELL config the mapped entries would be
 * discarded by {@code OrderService} while the mapped close-time SELL would be
 * mistaken for a fresh short entry.</p>
 */
@Component
public class Strategy4 extends AbstractSmaCrossStrategy {

    public static final int ID = 4;

    public Strategy4(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }

    @Override
    protected TradeAction mapAction(TradeAction detected) {
        switch (detected) {
            case SELL: return TradeAction.BUY;
            case BUY:  return TradeAction.SELL;
            default:   return detected;
        }
    }
}
