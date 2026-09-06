package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.StrategyDefaults;
import com.moneymaker.repository.StrategyDefaultsRepository;
import com.moneymaker.strategy.rules.RuleContext;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@link Strategy10} is Strategy 9 with a 13:15 cut-off and its own
 * {@code strategy_defaults} row (expiry gate off, candle 0.35). Only the
 * differences are pinned here; the shared rules live in the 8 and 9 tests.
 */
class Strategy10RulesTest {

    private static final String KEY_15M = "HIST:NIFTY:NSE:SPOT|15minute|CE|24000|HIST:NIFTY:NFO:2026-09-10:24000:CE|2|2";
    private static final LocalTime CLOSE_SIGNAL = LocalTime.of(15, 15);
    private static final LocalDateTime DAY = LocalDateTime.of(2026, 9, 7, 9, 15);

    static class Fixed extends Strategy10 {
        LocalDate expiry;
        Fixed() { super(null); }
        @Override protected LocalDate expiryFor(RuleContext ctx, LocalDate day) { return expiry; }
    }

    private final Fixed strategy = new Fixed();

    private static MarketData bar(LocalDateTime ts, double close) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(BigDecimal.valueOf(close + 1)); c.setHigh(BigDecimal.valueOf(close + 2));
        c.setLow(BigDecimal.valueOf(close - 2)); c.setClose(BigDecimal.valueOf(close));
        c.setVolume(100L);
        return c;
    }

    private static List<MarketData> series(int todayBars) {
        List<MarketData> out = new ArrayList<>();
        for (int i = 0; i < 25; i++) out.add(bar(DAY.minusDays(1).plusMinutes(15L * i), 200 - 2.0 * i));
        for (int i = 0; i < todayBars; i++) out.add(bar(DAY.plusMinutes(15L * i), 200 - 2.0 * (25 + i)));
        return out;
    }

    private RuleContext ctx(List<MarketData> s, int index) {
        MarketData c = s.get(index);
        return new RuleContext(c, index, s, 50, null, c.getTimestamp().plusMinutes(15), CLOSE_SIGNAL, KEY_15M);
    }

    private TradeAction decide(RuleContext ctx) {
        return strategy.decide(ctx, strategy.sellRulesFor(50), strategy.buyRulesFor(50)).action();
    }

    @Test
    @DisplayName("identity: id 10, cut-off 120 minutes before the close signal")
    void identity() {
        assertThat(strategy.getId()).isEqualTo(10);
        assertThat(strategy.entryCutoffMinutesBeforeCloseSignal()).isEqualTo(120);
        assertThat(new Strategy9(null).entryCutoffMinutesBeforeCloseSignal()).isEqualTo(30);
    }

    @Test
    @DisplayName("13:15 is the last entry bar; the 13:30 bar is blocked; Strategy 9 would still sell at 14:45")
    void cutoff() {
        strategy.useSettings(new Strategy9.GateSettings(null, null, null));
        List<MarketData> s = series(25);                                  // 09:15 … 15:15 today
        assertThat(decide(ctx(s, 25 + 16))).isEqualTo(TradeAction.SELL);  // 13:15 bar
        assertThat(decide(ctx(s, 25 + 17))).isEqualTo(TradeAction.NONE);  // 13:30 bar
        assertThat(decide(ctx(s, 25 + 22))).isEqualTo(TradeAction.NONE);  // 14:45 bar
        assertThat(decide(ctx(s, 25 + 24))).isEqualTo(TradeAction.BUY);   // 15:15 close-time exit untouched
    }

    @Test
    @DisplayName("reads its own strategy_defaults row (id 10), not Strategy 9's")
    void ownDefaultsRow() {
        StrategyDefaultsRepository repo = mock(StrategyDefaultsRepository.class);
        StrategyDefaults nine = new StrategyDefaults(); nine.setMinCandleClosePosition(new BigDecimal("0.25")); nine.setMinDaysToExpiry(2);
        StrategyDefaults ten = new StrategyDefaults(); ten.setMinCandleClosePosition(new BigDecimal("0.35")); ten.setMaxVolumeSurge(new BigDecimal("2.00"));
        when(repo.findById(anyInt())).thenReturn(Optional.empty());
        when(repo.findById(9)).thenReturn(Optional.of(nine));
        when(repo.findById(10)).thenReturn(Optional.of(ten));
        strategy.useRepository(repo);
        Strategy9.GateSettings s = strategy.settingsFor(DAY.toLocalDate());
        assertThat(s.minCandleClosePosition()).isEqualByComparingTo("0.35");
        assertThat(s.minDaysToExpiry()).isNull();
        assertThat(s.maxVolumeSurge()).isEqualByComparingTo("2.00");
    }

    @Test
    @DisplayName("with the seeded settings: 1 DTE trades, a candle at 0.3 of its range does not, 0.5 does")
    void seededGates() {
        strategy.useSettings(new Strategy9.GateSettings(null, new BigDecimal("0.35"), null));
        List<MarketData> s = series(8);
        strategy.expiry = DAY.toLocalDate().plusDays(1);                  // expiry gate off
        MarketData sig = s.get(25 + 4);                                   // 10:15 bar, close half-way (0.5)
        assertThat(decide(ctx(s, 25 + 4))).isEqualTo(TradeAction.SELL);
        sig.setLow(sig.getClose().subtract(new BigDecimal("1.2")));       // range 3.2, close 1.2 above low = 0.375 → passes
        assertThat(decide(ctx(s, 25 + 4))).isEqualTo(TradeAction.SELL);
        sig.setLow(sig.getClose().subtract(new BigDecimal("0.8")));       // range 2.8, close 0.8 above low = 0.29 → blocked
        assertThat(decide(ctx(s, 25 + 4))).isEqualTo(TradeAction.NONE);
    }
}
