package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.RuleEngine;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * {@link Strategy3} is Strategy 1 with the directions inverted, and the whole
 * inversion lives in three seams: {@link RuleEngine#decideBuyEntry} (cross-up
 * gate, ungated SELL exit), the mirrored rule sets, and the
 * {@code transaction_type} guard. Each is pinned here.
 *
 * <p>The fail-closed test matters most: {@code buyRulesFor} derives period
 * enablement from the <i>baseline's</i> sell rules, so a period the baseline
 * disables (20, via its commented-out {@code case}) must stay untradeable in
 * the inverted strategy too — the exact regression {@code RuleEngine}'s
 * "no rules" rule exists to prevent.</p>
 */
class Strategy3InvertedRulesTest {

    private final Strategy3 strategy = new Strategy3(null);

    private static MarketData candle(String open, String close, double sma50,
                                     boolean sma50UpTrending, LocalDateTime ts) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(new BigDecimal(open));
        c.setClose(new BigDecimal(close));
        c.setSmaValue50(sma50);
        c.setSma50UpTrending(sma50UpTrending);
        return c;
    }

    private RuleEngine.Decision decide(MarketData c, Integer period, LocalDateTime asOf) {
        RuleContext ctx = new RuleContext(c, 0, List.of(c), period, null, asOf);
        return RuleEngine.decideBuyEntry(ctx,
                strategy.sellRulesFor(period), strategy.buyRulesFor(period));
    }

    @Test
    @DisplayName("cross-up through the SMA with the up-trend flag set → BUY entry")
    void crossUpWithUpTrendBuys() {
        LocalDateTime ts = LocalDateTime.of(2026, 9, 4, 10, 15);
        RuleEngine.Decision d = decide(candle("90", "110", 100.0, true, ts), 50, ts);

        assertThat(d.action()).isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("cross-up without the up-trend flag → no signal (mirror of the down-trend requirement)")
    void crossUpWithoutUpTrendIsBlocked() {
        LocalDateTime ts = LocalDateTime.of(2026, 9, 4, 10, 15);
        RuleEngine.Decision d = decide(candle("90", "110", 100.0, false, ts), 50, ts);

        assertThat(d.action()).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("no cross, mid-session → no signal (the exit leg is close-time only)")
    void noCrossMidSessionIsQuiet() {
        LocalDateTime ts = LocalDateTime.of(2026, 9, 4, 10, 15);
        RuleEngine.Decision d = decide(candle("105", "110", 100.0, true, ts), 50, ts);

        assertThat(d.action()).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("no cross at the close-signal time → SELL, the inverted exit leg")
    void closeTimeEmitsSellExit() {
        LocalDateTime ts = LocalDateTime.of(2026, 9, 4, 15, 15);
        RuleEngine.Decision d = decide(candle("105", "110", 100.0, true, ts), 50, ts);

        assertThat(d.action()).isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("a period the baseline fails closed (20) stays fail-closed when inverted")
    void baselineDisabledPeriodStaysDisabled() {
        assertThat(strategy.buyRulesFor(20).required).isEmpty();
        assertThat(strategy.buyRulesFor(20).anyOf).isEmpty();

        // Even a perfect cross-up + up-trend bar must not fire on it.
        LocalDateTime ts = LocalDateTime.of(2026, 9, 4, 10, 15);
        MarketData c = candle("90", "110", 0, true, ts);
        c.setSmaValue20(100.0);
        c.setSma20UpTrending(true);
        RuleContext ctx = new RuleContext(c, 0, List.of(c), 20, null, ts);

        RuleEngine.Decision d = RuleEngine.decideBuyEntry(ctx,
                strategy.sellRulesFor(20), strategy.buyRulesFor(20));
        assertThat(d.action()).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("exit rules are the baseline buy rules verbatim — one anyOf: isMarketCloseTime")
    void exitRulesMirrorBaselineBuyRules() {
        var exit = strategy.sellRulesFor(50);

        assertThat(exit.required).isEmpty();
        assertThat(exit.anyOf).hasSize(1);
        assertThat(exit.anyOf.get(0).name()).isEqualTo("isMarketCloseTime");
    }

    // ---- transaction_type guard ----------------------------------------

    private Map<String, List<MarketData>> savedStrikeData;

    @AfterEach
    void restoreSharedData() {
        if (savedStrikeData != null) {
            SharedData.strikeMarketDataByInstrumentAndInterval = savedStrikeData;
            savedStrikeData = null;
        }
    }

    @Test
    @DisplayName("a config whose transaction_type is not BUY is refused before any scanning")
    void nonBuyConfigIsRefused() {
        // A non-empty cache plus a null instrument resolver means reaching the
        // scan would NPE — completing quietly proves the guard returned first.
        savedStrikeData = SharedData.strikeMarketDataByInstrumentAndInterval;
        Map<String, List<MarketData>> dummy = new ConcurrentHashMap<>();
        dummy.put("x|5minute|CE|23400|t|null|null",
                List.of(candle("90", "110", 100.0, true, LocalDateTime.of(2026, 9, 4, 10, 15))));
        SharedData.strikeMarketDataByInstrumentAndInterval = dummy;

        TradeConfig tc = new TradeConfig();
        tc.setId(7);
        tc.setTransactionType("SELL");
        SmaTimeframe tf = new SmaTimeframe();
        tf.setTimePeriod(5);
        tf.setSma(50);
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO(tc, null, null, List.of(tf), 3);

        int signalsBefore = SharedData.tradeSignals.size();
        assertThatCode(() -> strategy.execute(dto, LocalDateTime.of(2026, 9, 4, 10, 15)))
                .doesNotThrowAnyException();
        assertThat(SharedData.tradeSignals).hasSize(signalsBefore);
    }
}
