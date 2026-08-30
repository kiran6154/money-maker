package com.moneymaker.strategy;

import com.moneymaker.market.instrument.OptionInstrumentResolver;
import org.springframework.stereotype.Component;

/**
 * The baseline SMA-cross strategy: {@code open > SMA && close < SMA} on the
 * config's primary SMA period, gated by that period's down-trend flag, with the
 * opposite direction reserved for the end-of-day exit.
 *
 * <p>All of that lives in {@link AbstractSmaCrossStrategy} — this class adds
 * nothing beyond its id, and exists so the unmodified baseline stays addressable
 * as {@code stratergy_id = 1}. Compare with {@link Strategy2}, which is this
 * strategy plus one extra sell-side filter.</p>
 */
@Component
public class Strategy1 extends AbstractSmaCrossStrategy {

    public static final int ID = 1;

    public Strategy1(OptionInstrumentResolver instrumentResolver) {
        super(instrumentResolver);
    }

    @Override
    public int getId() {
        return ID;
    }
}
