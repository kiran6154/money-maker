package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeConfig;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Unit tests for {@link CommonRules}. Rule predicates and SMA helpers shared
 * across strategies. Bugs here change every strategy decision, so the test
 * coverage is broad — every public method, both happy and edge paths.
 */
class CommonRulesTest {

    @Nested
    class IsMarketCloseTime {

        @Test
        void true_when_candle_time_is_at_or_after_1515() {
            assertThat(CommonRules.isMarketCloseTime(ctxWithCandleAt(LocalTime.of(15, 15)))).isTrue();
            assertThat(CommonRules.isMarketCloseTime(ctxWithCandleAt(LocalTime.of(15, 20)))).isTrue();
            assertThat(CommonRules.isMarketCloseTime(ctxWithCandleAt(LocalTime.of(15, 30)))).isTrue();
        }

        @Test
        void false_when_candle_time_is_before_1515() {
            assertThat(CommonRules.isMarketCloseTime(ctxWithCandleAt(LocalTime.of(15, 14)))).isFalse();
            assertThat(CommonRules.isMarketCloseTime(ctxWithCandleAt(LocalTime.of(9, 30)))).isFalse();
        }

        @Test
        void false_when_candle_is_null() {
            RuleContext ctx = new RuleContext(null, 0, List.of(), 50, configWithTarget(null));
            assertThat(CommonRules.isMarketCloseTime(ctx)).isFalse();
        }

        @Test
        void false_when_candle_timestamp_is_null() {
            MarketData candle = new MarketData();
            // timestamp left null
            RuleContext ctx = new RuleContext(candle, 0, List.of(candle), 50, configWithTarget(null));
            assertThat(CommonRules.isMarketCloseTime(ctx)).isFalse();
        }
    }

    @Nested
    class IsDistanceToNextHigherSmaAboveTarget {

        @Test
        void true_when_distance_exceeds_target() {
            MarketData c = new MarketData();
            c.setSmaValue50(100.0);
            c.setSmaValue100(120.0);  // |120-100| = 20
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, configWithTarget(10.0));
            assertThat(CommonRules.isDistanceToNextHigherSmaAboveTarget(ctx)).isTrue();
        }

        @Test
        void false_when_distance_equals_or_below_target() {
            MarketData c = new MarketData();
            c.setSmaValue50(100.0);
            c.setSmaValue100(110.0);  // |110-100| = 10
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, configWithTarget(10.0));
            // strict > target, equal is false
            assertThat(CommonRules.isDistanceToNextHigherSmaAboveTarget(ctx)).isFalse();
        }

        @Test
        void false_when_either_sma_is_unavailable() {
            MarketData c1 = new MarketData();
            c1.setSmaValue50(100.0);  // higher (100) is null
            RuleContext ctx1 = new RuleContext(c1, 0, List.of(c1), 50, configWithTarget(1.0));
            assertThat(CommonRules.isDistanceToNextHigherSmaAboveTarget(ctx1)).isFalse();

            MarketData c2 = new MarketData();
            c2.setSmaValue100(200.0);  // primary (50) is null
            RuleContext ctx2 = new RuleContext(c2, 0, List.of(c2), 50, configWithTarget(1.0));
            assertThat(CommonRules.isDistanceToNextHigherSmaAboveTarget(ctx2)).isFalse();
        }

        @Test
        void false_when_no_higher_sma_exists_for_period() {
            MarketData c = new MarketData();
            c.setSmaValue500(100.0);
            // 500 has no "next higher" in nextHigherSmaPeriod.
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 500, configWithTarget(1.0));
            assertThat(CommonRules.isDistanceToNextHigherSmaAboveTarget(ctx)).isFalse();
        }

        @Test
        void false_when_target_is_null() {
            MarketData c = new MarketData();
            c.setSmaValue50(100.0);
            c.setSmaValue100(200.0);
            RuleContext ctx = new RuleContext(c, 0, List.of(c), 50, configWithTarget(null));
            assertThat(CommonRules.isDistanceToNextHigherSmaAboveTarget(ctx)).isFalse();
        }
    }

    @Nested
    class NextHigherSmaPeriod {

        @Test
        void chain_walks_20_50_100_200_500() {
            assertThat(CommonRules.nextHigherSmaPeriod(20)).isEqualTo(50);
            assertThat(CommonRules.nextHigherSmaPeriod(50)).isEqualTo(100);
            assertThat(CommonRules.nextHigherSmaPeriod(100)).isEqualTo(200);
            assertThat(CommonRules.nextHigherSmaPeriod(200)).isEqualTo(500);
        }

        @Test
        void returns_null_for_500_top_of_chain() {
            assertThat(CommonRules.nextHigherSmaPeriod(500)).isNull();
        }

        @Test
        void returns_null_for_unknown_period() {
            assertThat(CommonRules.nextHigherSmaPeriod(30)).isNull();
            assertThat(CommonRules.nextHigherSmaPeriod(null)).isNull();
        }
    }

    @Nested
    class ProfitTarget {

        @Test
        void extracts_target_from_config() {
            assertThat(CommonRules.profitTarget(configWithTarget(15.5)))
                    .isCloseTo(15.5, within(1e-9));
        }

        @Test
        void returns_null_for_null_config() {
            assertThat(CommonRules.profitTarget(null)).isNull();
        }

        @Test
        void returns_null_for_missing_tradeConfig() {
            TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
            // tradeConfig left null
            assertThat(CommonRules.profitTarget(dto)).isNull();
        }

        @Test
        void returns_null_for_unset_target() {
            assertThat(CommonRules.profitTarget(configWithTarget(null))).isNull();
        }
    }

    @Nested
    class SmaValue {

        @Test
        void reads_correct_field_per_period() {
            MarketData c = new MarketData();
            c.setSmaValue20(20.0);
            c.setSmaValue50(50.0);
            c.setSmaValue100(100.0);
            c.setSmaValue200(200.0);
            c.setSmaValue500(500.0);

            assertThat(CommonRules.smaValue(c, 20)).isCloseTo(20.0, within(1e-9));
            assertThat(CommonRules.smaValue(c, 50)).isCloseTo(50.0, within(1e-9));
            assertThat(CommonRules.smaValue(c, 100)).isCloseTo(100.0, within(1e-9));
            assertThat(CommonRules.smaValue(c, 200)).isCloseTo(200.0, within(1e-9));
            assertThat(CommonRules.smaValue(c, 500)).isCloseTo(500.0, within(1e-9));
        }

        @Test
        void returns_zero_when_value_is_null() {
            MarketData c = new MarketData();  // all SMA fields null
            assertThat(CommonRules.smaValue(c, 20)).isEqualTo(0.0);
            assertThat(CommonRules.smaValue(c, 500)).isEqualTo(0.0);
        }

        @Test
        void returns_zero_for_unknown_period() {
            MarketData c = new MarketData();
            c.setSmaValue20(20.0);
            assertThat(CommonRules.smaValue(c, 30)).isEqualTo(0.0);
        }

        @Test
        void returns_zero_for_null_candle_or_period() {
            assertThat(CommonRules.smaValue(null, 20)).isEqualTo(0.0);
            assertThat(CommonRules.smaValue(new MarketData(), null)).isEqualTo(0.0);
        }
    }

    @Nested
    class PriceHelpers {

        @Test
        void openValue_returns_double_or_zero() {
            MarketData c = new MarketData();
            c.setOpen(new BigDecimal("123.45"));
            assertThat(CommonRules.openValue(c)).isCloseTo(123.45, within(1e-9));
            assertThat(CommonRules.openValue(new MarketData())).isEqualTo(0.0);
            assertThat(CommonRules.openValue(null)).isEqualTo(0.0);
        }

        @Test
        void closeValue_returns_double_or_zero() {
            MarketData c = new MarketData();
            c.setClose(new BigDecimal("678.90"));
            assertThat(CommonRules.closeValue(c)).isCloseTo(678.90, within(1e-9));
            assertThat(CommonRules.closeValue(new MarketData())).isEqualTo(0.0);
            assertThat(CommonRules.closeValue(null)).isEqualTo(0.0);
        }
    }

    /* ---------------- helpers ---------------- */

    private static RuleContext ctxWithCandleAt(LocalTime time) {
        MarketData candle = new MarketData();
        candle.setTimestamp(LocalDateTime.of(LocalDate.of(2026, 4, 1), time));
        return new RuleContext(candle, 0, List.of(candle), 50, configWithTarget(null));
    }

    private static TradeConfigCombinedDTO configWithTarget(Double target) {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
        TradeConfig tc = new TradeConfig();
        if (target != null) tc.setTarget(BigDecimal.valueOf(target));
        dto.setTradeConfig(tc);
        return dto;
    }
}
