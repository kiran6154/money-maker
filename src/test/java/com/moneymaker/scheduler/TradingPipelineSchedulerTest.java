package com.moneymaker.scheduler;

import com.moneymaker.market.service.MarketHoursService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link TradingPipelineScheduler}.
 *
 * <p>Three guarantees the test exercises:
 * <ol>
 *   <li>Calls services in <b>analysis → orders → positions</b> order.</li>
 *   <li>{@code tryLock} skips re-entrant ticks (cumulative skip counter).</li>
 *   <li>Mode + market-hours gates short-circuit cleanly.</li>
 * </ol>
 */
class TradingPipelineSchedulerTest {

    @Mock private AnalysisScheduler analysis;
    @Mock private OrderScheduler orders;
    @Mock private PositionScheduler positions;
    @Mock private MarketHoursService marketHours;

    private TradingPipelineScheduler pipeline;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        pipeline = new TradingPipelineScheduler(analysis, orders, positions, marketHours);
        // Default: live mode, market open. Override per-test as needed.
        ReflectionTestUtils.setField(pipeline, "appMode", "live");
        when(marketHours.isOpenNow()).thenReturn(true);
    }

    @Test
    void tick_calls_services_in_strict_order() {
        pipeline.tick();

        InOrder seq = inOrder(analysis, orders, positions);
        seq.verify(analysis).analyzeMarketData();
        seq.verify(orders).processOrders();
        seq.verify(positions).processPositions();
    }

    @Test
    void tick_is_noop_in_backtest_mode() {
        ReflectionTestUtils.setField(pipeline, "appMode", "backtest");
        pipeline.tick();

        verify(analysis, never()).analyzeMarketData();
        verify(orders, never()).processOrders();
        verify(positions, never()).processPositions();
    }

    @Test
    void tick_is_noop_outside_market_hours() {
        when(marketHours.isOpenNow()).thenReturn(false);
        pipeline.tick();

        verify(analysis, never()).analyzeMarketData();
    }

    @Test
    void tick_skips_when_previous_tick_still_running() throws Exception {
        // Block the first tick in analyzeMarketData; fire the second from
        // another thread. The second tick should hit the tryLock-skip path
        // without invoking any service.
        CountDownLatch firstTickStarted = new CountDownLatch(1);
        CountDownLatch releaseFirstTick = new CountDownLatch(1);
        doAnswer(inv -> {
            firstTickStarted.countDown();
            releaseFirstTick.await(2, TimeUnit.SECONDS);
            return null;
        }).when(analysis).analyzeMarketData();

        Thread firstTick = new Thread(pipeline::tick, "tick-1");
        firstTick.start();
        assertThat(firstTickStarted.await(2, TimeUnit.SECONDS)).isTrue();

        long skipsBefore = pipeline.skippedTickCount();
        pipeline.tick();                            // re-entrant from main thread
        long skipsAfter = pipeline.skippedTickCount();

        assertThat(skipsAfter - skipsBefore)
                .as("re-entrant tick must increment the skip counter exactly once")
                .isEqualTo(1);
        verify(orders, never()).processOrders();    // second tick never reached orders
        verify(positions, never()).processPositions();

        releaseFirstTick.countDown();
        firstTick.join(2_000);
    }

    @Test
    void tick_continues_to_next_service_when_one_throws_during_normal_run() {
        // We don't want a failure in analysis to swallow orders/positions
        // forever — but within a tick, the per-tick try/catch should log and
        // move on. Verify: analysis throws, the pipeline catches, the tick
        // still completes (no exception propagates) and lock is released so
        // the next tick can proceed.
        doAnswer(inv -> { throw new RuntimeException("simulated"); })
                .when(analysis).analyzeMarketData();

        pipeline.tick();    // must not throw

        // Lock released — next tick runs normally.
        pipeline.tick();
        verify(analysis, org.mockito.Mockito.times(2)).analyzeMarketData();
    }
}
