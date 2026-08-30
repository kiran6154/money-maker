package com.moneymaker.scheduler;

import com.moneymaker.data.download.ZerodhaMarketDataService;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.model.HeartbeatResult;
import com.moneymaker.login.model.HeartbeatStatus;
import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.login.service.BrokerLoginService;
import com.moneymaker.login.service.LoginOrchestrator;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.state.AppState;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * GAPS #3 — the heartbeat used to run every 60s, forever. Cost was small (one
 * quote a minute) but it meant a Friday-evening AUTH_FAIL Telegram about a
 * session nothing was going to use until Monday.
 *
 * <p>Two things have to hold at once, and they pull in opposite directions:
 * <ul>
 *   <li><b>Nothing changes during trading hours.</b> The heartbeat is the only
 *       thing that catches token death, so a gate that clipped even a minute of
 *       the session would be a regression, not a cleanup. Enforced twice — as a
 *       test here, and as a startup check in {@code MarketHoursService.init}
 *       that refuses a window narrower than {@code [open, close]}.</li>
 *   <li><b>The morning margin is real.</b> Alerts fire on <i>transitions</i>, so
 *       a dead token has to be probed before the 08:00 login cron for the alert
 *       to be any use. 07:50 is the default and it is a property, not a
 *       constant.</li>
 * </ul>
 */
class HeartbeatWindowTest {

    private static final ZoneId IST = ZoneId.of("Asia/Kolkata");

    private BrokerLoginManager manager;
    private AppState appState;
    private NotificationService notifier;
    private LoginOrchestrator orchestrator;
    private BrokerLoginService loginService;
    private MarketHoursService marketHours;
    private LoginScheduler scheduler;

    @BeforeEach
    void setUp() {
        manager = mock(BrokerLoginManager.class);
        appState = mock(AppState.class);
        notifier = mock(NotificationService.class);
        orchestrator = mock(LoginOrchestrator.class);
        loginService = mock(BrokerLoginService.class);
        marketHours = mock(MarketHoursService.class);

        scheduler = new LoginScheduler(manager, appState, notifier, orchestrator,
                mock(ZerodhaMarketDataService.class), marketHours);
    }

    /** A session that probes clean, so a run that happens is unmistakable. */
    private void givenHealthySession() {
        BrokerSession session = mock(BrokerSession.class);
        when(session.getBroker()).thenReturn(Broker.ZERODHA);
        when(appState.currentSession()).thenReturn(Optional.of(session));
        when(appState.currentBroker()).thenReturn(Optional.of(Broker.ZERODHA));
        when(appState.getLastHeartbeatStatus()).thenReturn(HeartbeatStatus.OK);
        when(manager.forBroker(Broker.ZERODHA)).thenReturn(loginService);
        when(loginService.validateSession(session)).thenReturn(true);
        HeartbeatResult ok = mock(HeartbeatResult.class);
        when(ok.getStatus()).thenReturn(HeartbeatStatus.OK);
        when(loginService.fetchHeartbeatQuote(session)).thenReturn(ok);
    }

    /* ---------------- the scheduled tick ---------------- */

    @Test
    @DisplayName("outside the window the tick probes nothing at all — no session read, no broker call")
    void tick_is_inert_outside_the_window() {
        when(marketHours.isWithinHeartbeatWindow()).thenReturn(false);
        when(marketHours.heartbeatStart()).thenReturn(LocalTime.of(7, 50));
        when(marketHours.heartbeatEnd()).thenReturn(LocalTime.of(15, 40));

        scheduler.heartbeat();

        verifyNoInteractions(appState, manager, notifier);
    }

    @Test
    @DisplayName("inside the window the tick runs the probe exactly as before")
    void tick_probes_inside_the_window() {
        when(marketHours.isWithinHeartbeatWindow()).thenReturn(true);
        givenHealthySession();

        scheduler.heartbeat();

        verify(loginService).validateSession(any());
        verify(appState).onHeartbeat(any(), any(), any());
    }

    @Test
    @DisplayName("the probe itself has no clock opinion — a direct call runs regardless of the window")
    void probe_ignores_the_window_when_called_directly() {
        when(marketHours.isWithinHeartbeatWindow()).thenReturn(false);
        givenHealthySession();

        scheduler.runHeartbeat();

        verify(loginService).validateSession(any());
        verify(marketHours, never()).isWithinHeartbeatWindow();
    }

    /* ---------------- the window itself ---------------- */

    private MarketHoursService realHours(String start, String end) {
        MarketHoursService s = new MarketHoursService();
        ReflectionTestUtils.setField(s, "openStr", "09:15");
        ReflectionTestUtils.setField(s, "closeStr", "15:30");
        ReflectionTestUtils.setField(s, "timezoneStr", "Asia/Kolkata");
        ReflectionTestUtils.setField(s, "closeSignalOffsetMinutes", 15);
        ReflectionTestUtils.setField(s, "replayFirstTickOffsetMinutes", 5);
        ReflectionTestUtils.setField(s, "replayLastTickOffsetMinutes", 10);
        ReflectionTestUtils.setField(s, "heartbeatStartStr", start);
        ReflectionTestUtils.setField(s, "heartbeatEndStr", end);
        ReflectionTestUtils.invokeMethod(s, "init");
        return s;
    }

    /** 2026-08-31 is a Monday; 2026-09-05 a Saturday. */
    private static ZonedDateTime weekdayAt(int hour, int minute) {
        return ZonedDateTime.of(2026, 8, 31, hour, minute, 0, 0, IST);
    }

    private static ZonedDateTime saturdayAt(int hour, int minute) {
        return ZonedDateTime.of(2026, 9, 5, hour, minute, 0, 0, IST);
    }

    private boolean within(MarketHoursService s, ZonedDateTime at) {
        return Boolean.TRUE.equals(
                ReflectionTestUtils.invokeMethod(s, "isWithinHeartbeatWindow", at));
    }

    @Test
    @DisplayName("defaults: 07:50-15:40 inclusive, so the 08:00 login cron is covered with 10 min to spare")
    void default_window_boundaries() {
        MarketHoursService s = realHours("07:50", "15:40");

        assertThat(s.heartbeatStart()).isEqualTo(LocalTime.of(7, 50));
        assertThat(s.heartbeatEnd()).isEqualTo(LocalTime.of(15, 40));

        assertThat(within(s, weekdayAt(7, 49))).isFalse();
        assertThat(within(s, weekdayAt(7, 50))).isTrue();   // boundary is inclusive
        assertThat(within(s, weekdayAt(8, 0))).isTrue();    // the login cron
        assertThat(within(s, weekdayAt(15, 40))).isTrue();  // boundary is inclusive
        assertThat(within(s, weekdayAt(15, 41))).isFalse();
        assertThat(within(s, weekdayAt(22, 0))).isFalse();  // the Friday-night case
    }

    @Test
    @DisplayName("every minute of the trading session is still probed")
    void trading_session_is_fully_covered() {
        MarketHoursService s = realHours("07:50", "15:40");
        for (int h = 9; h <= 15; h++) {
            for (int m = 0; m < 60; m++) {
                boolean inSession = (h > 9 || m >= 15) && (h < 15 || m <= 30);
                if (inSession) {
                    assertThat(within(s, weekdayAt(h, m)))
                            .as("heartbeat must run at %02d:%02d — it is inside the session", h, m)
                            .isTrue();
                }
            }
        }
    }

    @Test
    @DisplayName("weekends are outside the window even at 10:00")
    void weekends_are_out() {
        MarketHoursService s = realHours("07:50", "15:40");
        assertThat(within(s, saturdayAt(10, 0))).isFalse();
    }

    @Test
    @DisplayName("the window is configurable, and a window narrower than the session fails startup")
    void window_is_configurable_and_validated() {
        MarketHoursService wider = realHours("06:00", "18:00");
        assertThat(within(wider, weekdayAt(6, 0))).isTrue();
        assertThat(within(wider, weekdayAt(17, 59))).isTrue();

        assertThatThrownBy(() -> realHours("09:30", "15:40"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("does not cover the trading session");
        assertThatThrownBy(() -> realHours("07:50", "15:00"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("does not cover the trading session");
    }
}
