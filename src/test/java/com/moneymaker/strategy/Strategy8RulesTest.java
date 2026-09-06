package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.entity.MarketData;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.RuleEngine;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link Strategy8} is the "20SMA 15min candle" rule with no cross gate. The
 * four sell-side rules and the ATR the signal carries are pinned here bar by
 * bar on a synthetic 15-minute series; the exit half (the chandelier floor)
 * lives in {@code PositionServiceAtrTrailTest}.
 */
class Strategy8RulesTest {

    private static final String KEY_15M = "HIST:NIFTY:NSE:SPOT|15minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";
    private static final String KEY_5M  = "HIST:NIFTY:NSE:SPOT|5minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";
    private static final LocalTime CLOSE_SIGNAL = LocalTime.of(15, 15);
    private static final LocalDateTime DAY = LocalDateTime.of(2026, 9, 7, 9, 15);

    private final Strategy8 strategy = new Strategy8(null);

    // ------------------------------------------------------------ fixtures

    private static MarketData bar(LocalDateTime ts, double open, double high, double low, double close) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(BigDecimal.valueOf(open));
        c.setHigh(BigDecimal.valueOf(high));
        c.setLow(BigDecimal.valueOf(low));
        c.setClose(BigDecimal.valueOf(close));
        return c;
    }

    /**
     * A 15-minute series from the previous session's 09:15 to today: closes
     * follow {@code closeAt(i)}, each bar spanning ±2 around its close. 25 bars
     * per session, so today's bar {@code k} sits at index {@code 25 + k}.
     */
    private static List<MarketData> series(java.util.function.IntToDoubleFunction closeAt, int todayBars) {
        List<MarketData> out = new ArrayList<>();
        LocalDateTime prevDay = DAY.minusDays(1);
        for (int i = 0; i < 25; i++) {
            double c = closeAt.applyAsDouble(i);
            out.add(bar(prevDay.plusMinutes(15L * i), c + 1, c + 2, c - 2, c));
        }
        for (int i = 0; i < todayBars; i++) {
            double c = closeAt.applyAsDouble(25 + i);
            out.add(bar(DAY.plusMinutes(15L * i), c + 1, c + 2, c - 2, c));
        }
        return out;
    }

    private RuleContext ctx(List<MarketData> s, int index, String key) {
        MarketData candle = s.get(index);
        return new RuleContext(candle, index, s, 50, null,
                candle.getTimestamp().plusMinutes(15), CLOSE_SIGNAL, key);
    }

    private TradeAction decide(RuleContext ctx) {
        return strategy.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50)).action();
    }

    // ------------------------------------------------------------ entry

    @Test
    @DisplayName("falling premium: SMA-20 slope down and close below previous close → SELL, no cross needed")
    void fallingSeriesSells() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 8);   // 09:15 … 11:00 today
        RuleContext ctx = ctx(s, 25 + 4, KEY_15M);            // today's 10:15 bar
        assertThat(Strategy8.smaSlopeDown(ctx)).isTrue();
        assertThat(Strategy8.closeBelowPreviousClose(ctx)).isTrue();
        assertThat(Strategy8.isSignalTimeframe(ctx)).isTrue();
        RuleEngine.Decision d = strategy.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50));
        assertThat(d.action()).isEqualTo(TradeAction.SELL);
        assertThat(d.reason()).contains("no cross gate");
    }

    @Test
    @DisplayName("an up-close inside a down-slope blocks the entry")
    void upCloseBlocks() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 8);
        s.get(25 + 4).setClose(s.get(25 + 3).getClose().add(BigDecimal.ONE)); // 10:15 closes above 10:00
        assertThat(decide(ctx(s, 25 + 4, KEY_15M))).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("a down-close while the SMA-20 slopes up blocks the entry")
    void upSlopeBlocks() {
        List<MarketData> s = series(i -> 100 + 2.0 * i, 8);               // rising premium
        s.get(25 + 4).setClose(s.get(25 + 3).getClose().subtract(BigDecimal.ONE)); // one lower close
        RuleContext ctx = ctx(s, 25 + 4, KEY_15M);
        assertThat(Strategy8.closeBelowPreviousClose(ctx)).isTrue();
        assertThat(Strategy8.smaSlopeDown(ctx)).isFalse();
        assertThat(decide(ctx)).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("the rule only reads the 15-minute series")
    void fiveMinuteSeriesNeverSells() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 8);
        assertThat(decide(ctx(s, 25 + 4, KEY_5M))).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("too little history for the 20-SMA slope → no entry, no exception")
    void warmUpGuard() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 8).subList(20, 33);   // 13 bars only
        RuleContext ctx = new RuleContext(s.get(12), 12, s, 50, null,
                s.get(12).getTimestamp().plusMinutes(15), CLOSE_SIGNAL, KEY_15M);
        assertThat(Strategy8.smaOfCloses(s, 12, 20)).isNull();
        assertThat(decide(ctx)).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("SMA-20 of closes is a plain mean over the last 20 bars, across the session boundary")
    void smaArithmetic() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 8);
        // bars 13..32 close at 200-26 … 200-64 → mean 200 - 2*22.5 = 155
        assertThat(Strategy8.smaOfCloses(s, 32, 20)).isEqualTo(155.0);
    }

    // ------------------------------------------------------------ time gates

    @Test
    @DisplayName("14:45 is the last entry bar; the 15:00 bar is blocked")
    void entryCutoff() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 24);   // 09:15 … 15:00 today
        assertThat(decide(ctx(s, 25 + 22, KEY_15M))).isEqualTo(TradeAction.SELL);  // 14:45 bar
        assertThat(decide(ctx(s, 25 + 23, KEY_15M))).isEqualTo(TradeAction.NONE);  // 15:00 bar
    }

    @Test
    @DisplayName("close-signal time → BUY exit even though the premium is still falling")
    void closeTimeExit() {
        List<MarketData> s = series(i -> 200 - 2.0 * i, 25);   // 09:15 … 15:15 today
        assertThat(decide(ctx(s, 25 + 24, KEY_15M))).isEqualTo(TradeAction.BUY);
    }

    // ------------------------------------------------------------ ATR on the signal

    @Test
    @DisplayName("ATR-14 is the mean true range of the last 14 bars and travels on the signal")
    void atrOnSignal() {
        // bars close 2 apart, span ±2 → true range = max(4, |c+2 - prevC|, |c-2 - prevC|) = max(4, 4, 0) = 4
        List<MarketData> s = series(i -> 200 - 2.0 * i, 8);
        RuleContext ctx = ctx(s, 25 + 4, KEY_15M);
        assertThat(Strategy8.atr(s, 25 + 4, 14)).isEqualByComparingTo("4");
        assertThat(strategy.signalAtr(ctx)).isEqualByComparingTo("4");
        assertThat(Strategy8.atr(s, 10, 14)).isNull();   // not enough bars for 14 true ranges
    }

    @Test
    @DisplayName("identity: id 8, no confirmation series, stop-loss does not lock the book")
    void identity() {
        assertThat(strategy.getId()).isEqualTo(8);
        assertThat(strategy.confirmationTimeframes()).isEmpty();
        assertThat(strategy.stopLossLocksBookForDay()).isFalse();
    }
}
