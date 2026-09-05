package com.moneymaker.strategy;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.shared.data.SharedData;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@link Strategy4}'s whole identity is "Strategy 1's detection, inverted at
 * execution". Three properties carry it, each pinned here:
 * <ol>
 *   <li>the rule sets are the inherited baseline, untouched — the user's
 *       "do not change the rule set of sell" is a testable statement;</li>
 *   <li>{@code mapAction} inverts SELL↔BUY and leaves NONE alone;</li>
 *   <li>end-to-end through {@code execute()}, a bar that fires Strategy 1's
 *       sell signal (cross-down + down-trend) lands in
 *       {@code SharedData.tradeSignals} as a <b>BUY</b> — the mapping is applied
 *       at emission, not just defined.</li>
 * </ol>
 */
class Strategy4InvertedExecutionTest {

    private static final String KEY = "TOK|5minute|CE|23400|999|null|null";
    private static final LocalDateTime TICK = LocalDateTime.of(2026, 9, 4, 10, 15);

    private Map<String, List<MarketData>> savedStrikeData;
    private Map<String, LocalDateTime> savedTickStamps;

    @BeforeEach
    void snapshotSharedData() {
        savedStrikeData = SharedData.strikeMarketDataByInstrumentAndInterval;
        savedTickStamps = SharedData.strikeMarketDataTick;
        SharedData.strikeMarketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
        SharedData.strikeMarketDataTick = new ConcurrentHashMap<>();
        SharedData.tradeSignals.clear();
    }

    @AfterEach
    void restoreSharedData() {
        SharedData.strikeMarketDataByInstrumentAndInterval = savedStrikeData;
        SharedData.strikeMarketDataTick = savedTickStamps;
        SharedData.tradeSignals.clear();
    }

    private static MarketData candle(LocalDateTime ts, String open, String close, double sma50) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        c.setOpen(new BigDecimal(open));
        c.setHigh(new BigDecimal(open));
        c.setLow(new BigDecimal(close));
        c.setClose(new BigDecimal(close));
        c.setSmaValue50(sma50);
        return c;
    }

    /** CE config on a 5-minute / SMA-50 timeframe, fanned out for strategy 4. */
    private static TradeConfigCombinedDTO buyConfig(String transactionType) {
        TradeConfig tc = new TradeConfig();
        tc.setId(7);
        tc.setTradingSide("CE");
        tc.setTransactionType(transactionType);
        SmaTimeframe tf = new SmaTimeframe();
        tf.setTimePeriod(5);
        tf.setSma(50);
        return new TradeConfigCombinedDTO(tc, null, null, List.of(tf), Strategy4.ID);
    }

    /**
     * Two same-day candles with a declining SMA-50 (101 → 100), the second one
     * crossing down through it (open 105 &gt; 100 &gt; close 95) — exactly the
     * bar Strategy 1 sells on.
     */
    private static void cacheSellSignalBar() {
        List<MarketData> series = new ArrayList<>();
        series.add(candle(TICK.minusMinutes(5), "108", "106", 101.0));
        series.add(candle(TICK, "105", "95", 100.0));
        // One call writes the series, the S8 stamp and the contract-id index
        // together — see SharedData.putStrikeSeries (GAPS #27).
        SharedData.putStrikeSeries(KEY, series, TICK);
    }

    private static Strategy4 strategyScanning(String underlyingToken) {
        OptionInstrumentResolver resolver = mock(OptionInstrumentResolver.class);
        when(resolver.underlyingSymbol(any(TradeConfigCombinedDTO.class))).thenReturn(underlyingToken);
        return new Strategy4(resolver);
    }

    @Test
    @DisplayName("Strategy 1's sell bar is emitted as a BUY signal, end to end")
    void sellDetectionEmitsBuy() {
        cacheSellSignalBar();

        strategyScanning("TOK").execute(buyConfig("BUY"), TICK);

        assertThat(SharedData.tradeSignals).hasSize(1);
        TradeSignal s = SharedData.tradeSignals.peek();
        assertThat(s.getAction()).isEqualTo(TradeAction.BUY);
        assertThat(s.getStrategyId()).isEqualTo(Strategy4.ID);
        assertThat(s.getStrikeKey()).isEqualTo(KEY);
        assertThat(s.getPrice()).isEqualByComparingTo("95");
        assertThat(s.getSignalTime()).isEqualTo(TICK);
    }

    @Test
    @DisplayName("rule sets are the untouched baseline — Strategy 1's, name for name")
    void ruleSetsAreTheBaseline() {
        Strategy4 s4 = new Strategy4(null);

        var sell = s4.sellRulesFor(50);
        assertThat(sell.required).hasSize(1);
        assertThat(sell.required.get(0).name()).isEqualTo("isSma50DownTrending");
        assertThat(sell.anyOf).isEmpty();

        var buy = s4.buyRulesFor(50);
        assertThat(buy.required).isEmpty();
        assertThat(buy.anyOf).hasSize(1);
        assertThat(buy.anyOf.get(0).name()).isEqualTo("isMarketCloseTime");

        // Disabled periods stay disabled — inherited fail-closed.
        assertThat(s4.sellRulesFor(20).required).isEmpty();
        assertThat(s4.sellRulesFor(20).anyOf).isEmpty();
    }

    @Test
    @DisplayName("mapAction inverts SELL↔BUY and leaves NONE alone")
    void mapActionInverts() {
        Strategy4 s4 = new Strategy4(null);

        assertThat(s4.mapAction(TradeAction.SELL)).isEqualTo(TradeAction.BUY);
        assertThat(s4.mapAction(TradeAction.BUY)).isEqualTo(TradeAction.SELL);
        assertThat(s4.mapAction(TradeAction.NONE)).isEqualTo(TradeAction.NONE);
    }

    @Test
    @DisplayName("a config whose transaction_type is not BUY is refused before any scanning")
    void nonBuyConfigIsRefused() {
        cacheSellSignalBar();

        // A null resolver would NPE the moment the scan starts — completing
        // quietly with no signal proves the inherited guard returned first.
        Strategy4 s4 = new Strategy4(null);
        assertThatCode(() -> s4.execute(buyConfig("SELL"), TICK)).doesNotThrowAnyException();
        assertThat(SharedData.tradeSignals).isEmpty();
    }
}
