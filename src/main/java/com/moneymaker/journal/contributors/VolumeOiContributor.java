package com.moneymaker.journal.contributors;

import com.moneymaker.entity.MarketData;
import com.moneymaker.journal.FeatureContributor;
import com.moneymaker.journal.ObservationContext;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Volume and open interest on the traded leg, plus their change against the
 * previous settled bar.
 *
 * <h3>Why this matters for a seller specifically</h3>
 * OI is a position count, not a flow: it rises when a new contract is written and
 * falls when one is closed out. So the pairing of OI direction with premium
 * direction is the informative part —
 *
 * <ul>
 *   <li>premium rising <b>and</b> OI rising = fresh buying into the leg you are
 *       short. New money is taking the other side of your position.</li>
 *   <li>premium rising <b>and</b> OI falling = shorts covering. The move is
 *       unwinding rather than building, and is more likely to exhaust.</li>
 * </ul>
 *
 * <p>The raw fields were present in {@code historical_option_candles} all along
 * and silently discarded, because {@code MarketData} had nowhere to put them
 * until changeset 030. Nothing in the strategy has ever seen them.
 *
 * <p>Nulls are left absent rather than defaulted to zero: the broker path does
 * not supply these yet, and a zero would read as "no trades" instead of
 * "not known".
 */
@Component
public class VolumeOiContributor implements FeatureContributor {

    @Override
    public String name() {
        return "volume-oi";
    }

    @Override
    public Map<String, Object> contribute(ObservationContext ctx) {
        Map<String, Object> f = new LinkedHashMap<>();
        List<MarketData> candles = ctx == null ? null : ctx.optionCandles();
        if (candles == null || candles.isEmpty()) {
            return f;
        }

        MarketData last = candles.get(candles.size() - 1);
        MarketData prev = candles.size() >= 2 ? candles.get(candles.size() - 2) : null;

        if (last.getVolume() != null) {
            f.put("volume", last.getVolume());
            if (prev != null && prev.getVolume() != null) {
                f.put("volume_change", last.getVolume() - prev.getVolume());
            }
        }

        if (last.getOpenInterest() != null) {
            f.put("open_interest", last.getOpenInterest());
            if (prev != null && prev.getOpenInterest() != null) {
                long delta = last.getOpenInterest() - prev.getOpenInterest();
                f.put("oi_change", delta);

                // The combination, pre-computed, so analysis can group on it
                // directly instead of re-deriving the sign pair every query.
                if (last.getClose() != null && prev.getClose() != null) {
                    int priceDir = last.getClose().compareTo(prev.getClose());
                    if (priceDir != 0 && delta != 0) {
                        boolean priceUp = priceDir > 0;
                        boolean oiUp = delta > 0;
                        f.put("oi_price_regime",
                                priceUp
                                        ? (oiUp ? "PREMIUM_UP_OI_UP" : "PREMIUM_UP_OI_DOWN")
                                        : (oiUp ? "PREMIUM_DOWN_OI_UP" : "PREMIUM_DOWN_OI_DOWN"));
                    }
                }
            }
        }
        return f;
    }
}
