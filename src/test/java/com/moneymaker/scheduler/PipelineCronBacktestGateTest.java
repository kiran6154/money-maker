package com.moneymaker.scheduler;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.journal.JournalRecorder;
import com.moneymaker.journal.ObservationContextFactory;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.position.service.PositionService;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.StrategyFactory;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Pins the backtest gate on the three pipeline crons (GAPS #4).
 *
 * <p>The shape being protected is the one invariant 8 asks for: the
 * {@code @Scheduled} method is a wall-clock wrapper and may refuse to run; the
 * method underneath it is the replayable one and must behave identically in
 * both modes, because {@code BacktestAnalysisService} calls it directly with a
 * simulated timestamp. So each scheduler gets four assertions — the cron is
 * inert in backtest, the cron still runs in live, the live market-hours gate is
 * unchanged, and the explicit call the replay makes is untouched by mode.</p>
 */
class PipelineCronBacktestGateTest {

    private static final String LIVE = "live";
    private static final String BACKTEST = "backtest";

    @Nested
    @DisplayName("OrderScheduler")
    class Orders {

        private OrderService orderService;
        private MarketHoursService marketHours;

        @BeforeEach
        void setUp() {
            orderService = mock(OrderService.class);
            marketHours = mock(MarketHoursService.class);
        }

        @Test
        @DisplayName("cron tick is a no-op in backtest mode, and never even asks the clock")
        void cronInertInBacktest() {
            new OrderScheduler(orderService, marketHours, BACKTEST).scheduledTick();

            verify(orderService, never()).processOrders();
            verifyNoInteractions(marketHours);
        }

        @Test
        @DisplayName("cron tick still drains the queue in live mode while the market is open")
        void cronRunsInLive() {
            when(marketHours.isOpenNow()).thenReturn(true);

            new OrderScheduler(orderService, marketHours, LIVE).scheduledTick();

            verify(orderService).processOrders();
        }

        @Test
        @DisplayName("live market-hours gating is unchanged")
        void cronSkipsOutsideMarketHours() {
            when(marketHours.isOpenNow()).thenReturn(false);

            new OrderScheduler(orderService, marketHours, LIVE).scheduledTick();

            verify(orderService, never()).processOrders();
        }

        @Test
        @DisplayName("the replay's explicit processOrders() call runs regardless of mode")
        void explicitCallUnaffectedByMode() {
            new OrderScheduler(orderService, marketHours, BACKTEST).processOrders();

            verify(orderService).processOrders();
            verifyNoInteractions(marketHours);
        }
    }

    @Nested
    @DisplayName("PositionScheduler")
    class Positions {

        private PositionService positionService;
        private MarketHoursService marketHours;

        @BeforeEach
        void setUp() {
            positionService = mock(PositionService.class);
            marketHours = mock(MarketHoursService.class);
        }

        @Test
        @DisplayName("cron tick is a no-op in backtest mode, and never even asks the clock")
        void cronInertInBacktest() {
            new PositionScheduler(positionService, marketHours, BACKTEST).scheduledTick();

            verify(positionService, never()).processPositions();
            verifyNoInteractions(marketHours);
        }

        @Test
        @DisplayName("cron tick still monitors open rows in live mode while the market is open")
        void cronRunsInLive() {
            when(marketHours.isOpenNow()).thenReturn(true);

            new PositionScheduler(positionService, marketHours, LIVE).scheduledTick();

            verify(positionService).processPositions();
        }

        @Test
        @DisplayName("live market-hours gating is unchanged")
        void cronSkipsOutsideMarketHours() {
            when(marketHours.isOpenNow()).thenReturn(false);

            new PositionScheduler(positionService, marketHours, LIVE).scheduledTick();

            verify(positionService, never()).processPositions();
        }

        @Test
        @DisplayName("the replay's explicit processPositions() call runs regardless of mode")
        void explicitCallUnaffectedByMode() {
            new PositionScheduler(positionService, marketHours, BACKTEST).processPositions();

            verify(positionService).processPositions();
            verifyNoInteractions(marketHours);
        }
    }

    @Nested
    @DisplayName("AnalysisScheduler")
    class Analysis {

        private MarketDataService marketDataService;
        private MarketHoursService marketHours;
        private StrategyFactory strategyFactory;

        @AfterEach
        void clearSharedState() {
            SharedData.combinedDto = null;
        }

        private AnalysisScheduler realScheduler(String appMode) {
            marketDataService = mock(MarketDataService.class);
            marketHours = mock(MarketHoursService.class);
            strategyFactory = mock(StrategyFactory.class);
            return new AnalysisScheduler(
                    marketDataService,
                    new IndicatorService(), // final class — the real one, never reached by these paths
                    strategyFactory,
                    marketHours,
                    mock(TradeOrderRepository.class),
                    mock(OptionInstrumentResolver.class),
                    mock(JournalRecorder.class),
                    mock(ObservationContextFactory.class),
                    appMode);
        }

        /**
         * Spied so the assertion can be about the wrapper's decision — did it
         * hand off to the replayable method? — without dragging the whole
         * fetch-and-compute body (and its static {@code SharedData} state) into
         * a test about mode gating. {@code calculateIndicator} is stubbed out
         * for the same reason.
         */
        private AnalysisScheduler scheduler(String appMode) {
            AnalysisScheduler spied = spy(realScheduler(appMode));
            doNothing().when(spied).calculateIndicator(any(LocalDateTime.class));
            return spied;
        }

        @Test
        @DisplayName("cron tick is a no-op in backtest mode, and never fetches today's candles")
        void cronInertInBacktest() {
            AnalysisScheduler scheduler = scheduler(BACKTEST);

            scheduler.analyzeMarketData();

            verify(scheduler, never()).calculateIndicator(any(LocalDateTime.class));
            verifyNoInteractions(marketHours, marketDataService);
        }

        @Test
        @DisplayName("cron tick still analyses in live mode while the market is open")
        void cronRunsInLive() {
            AnalysisScheduler scheduler = scheduler(LIVE);
            when(marketHours.isOpenNow()).thenReturn(true);

            scheduler.analyzeMarketData();

            verify(scheduler).calculateIndicator(any(LocalDateTime.class));
        }

        @Test
        @DisplayName("live market-hours gating is unchanged")
        void cronSkipsOutsideMarketHours() {
            AnalysisScheduler scheduler = scheduler(LIVE);
            when(marketHours.isOpenNow()).thenReturn(false);

            scheduler.analyzeMarketData();

            verify(scheduler, never()).calculateIndicator(any(LocalDateTime.class));
        }

        @Test
        @DisplayName("the replay's explicit runStrategies(asOf) call dispatches in backtest mode")
        void explicitCallUnaffectedByMode() {
            AnalysisScheduler scheduler = realScheduler(BACKTEST);
            LocalDateTime asOf = LocalDateTime.of(2024, 1, 4, 10, 15);
            TradeConfigCombinedDTO dto =
                    new TradeConfigCombinedDTO(new TradeConfig(), null, null, List.of());
            SharedData.combinedDto = List.of(dto);

            scheduler.runStrategies(asOf);

            verify(strategyFactory).execute(dto, asOf);
            // The replayable method consults neither the mode nor the wall clock.
            verifyNoInteractions(marketHours);
        }
    }
}
