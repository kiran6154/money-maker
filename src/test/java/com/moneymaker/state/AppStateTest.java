package com.moneymaker.state;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.model.HeartbeatStatus;
import com.moneymaker.login.service.BrokerSessionStore;
import com.moneymaker.repository.BrokerSessionRepository;
import com.moneymaker.repository.TradeConfigRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link AppState}.
 *
 * <p>Focus on the state-machine behaviour: heartbeat status transitions,
 * {@code isLoggedIn} short-circuits for AUTH_FAIL / NO_SESSION, and the
 * "transient probe failure does not unset session" contract from the class
 * Javadoc.
 */
class AppStateTest {

    @Mock private BrokerSessionStore sessionStore;
    @Mock private BrokerSessionRepository sessionRepository;
    @Mock private TradeConfigRepository tradeConfigRepository;

    private AppState state;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        // Default: no session in DB (test starts from fresh JVM).
        when(sessionRepository.findFirstByLoggedInTrue()).thenReturn(Optional.empty());
        when(sessionStore.current()).thenReturn(Optional.empty());
        state = new AppState(sessionStore, sessionRepository, tradeConfigRepository);
    }

    @Test
    void rehydrate_with_no_persisted_session_leaves_state_empty() {
        // Manually call the @PostConstruct (Spring would do this normally).
        org.springframework.test.util.ReflectionTestUtils.invokeMethod(state, "rehydrate");
        assertThat(state.isLoggedIn()).isFalse();
        assertThat(state.currentSession()).isEmpty();
        assertThat(state.getLastHeartbeatStatus()).isEqualTo(HeartbeatStatus.NO_SESSION);
    }

    @Test
    void onLoginSuccess_caches_session_and_marks_status_OK() {
        BrokerSession s = validSession();
        state.onLoginSuccess(s);

        assertThat(state.currentSession()).contains(s);
        assertThat(state.isLoggedIn()).isTrue();
        assertThat(state.getLastHeartbeatStatus()).isEqualTo(HeartbeatStatus.OK);
        assertThat(state.isDataHealthy()).isTrue();
        verify(sessionStore).save(s);
    }

    @Test
    void onLogout_clears_session_and_marks_NO_SESSION() {
        state.onLoginSuccess(validSession());
        state.onLogout();

        assertThat(state.isLoggedIn()).isFalse();
        assertThat(state.getLastHeartbeatStatus()).isEqualTo(HeartbeatStatus.NO_SESSION);
        assertThat(state.isDataHealthy()).isFalse();
        verify(sessionStore).clear();
    }

    @Test
    void onHeartbeat_OK_marks_data_healthy_and_persists_status() {
        state.onLoginSuccess(validSession());
        Instant tick = Instant.now();
        state.onHeartbeat(HeartbeatStatus.OK, tick, null);

        assertThat(state.getLastHeartbeatStatus()).isEqualTo(HeartbeatStatus.OK);
        assertThat(state.isDataHealthy()).isTrue();
        assertThat(state.getLastDataAt()).isEqualTo(tick);
        verify(sessionStore).updateHeartbeatStatus(eq(Broker.ZERODHA), eq("OK"), eq(tick), eq(true));
    }

    @Test
    void onHeartbeat_NO_DATA_does_NOT_unset_loggedIn() {
        // Contract: a transient probe failure preserves cached tokens. Only
        // AUTH_FAIL / NO_SESSION should flip isLoggedIn to false.
        state.onLoginSuccess(validSession());
        state.onHeartbeat(HeartbeatStatus.NO_DATA, null, "broker quote endpoint timing out");

        assertThat(state.getLastHeartbeatStatus()).isEqualTo(HeartbeatStatus.NO_DATA);
        assertThat(state.isDataHealthy()).isFalse();
        assertThat(state.isLoggedIn()).isTrue();    // still logged in
        assertThat(state.currentSession()).isPresent();
    }

    @Test
    void onHeartbeat_AUTH_FAIL_makes_isLoggedIn_return_false() {
        state.onLoginSuccess(validSession());
        state.onHeartbeat(HeartbeatStatus.AUTH_FAIL, null, "token rejected");

        assertThat(state.getLastHeartbeatStatus()).isEqualTo(HeartbeatStatus.AUTH_FAIL);
        // Session still cached, but isLoggedIn returns false.
        assertThat(state.isLoggedIn()).isFalse();
        assertThat(state.currentSession()).isPresent();
    }

    @Test
    void onHeartbeat_HTTP_ERROR_does_NOT_unset_loggedIn() {
        // HTTP_ERROR is a transient diagnostic, same class as NO_DATA.
        state.onLoginSuccess(validSession());
        state.onHeartbeat(HeartbeatStatus.HTTP_ERROR, null, "500 from broker");

        assertThat(state.isLoggedIn()).isTrue();
    }

    @Test
    void isLoggedIn_returns_false_when_session_has_expired() {
        // Expired-at in the past → BrokerSession.isExpired() = true.
        BrokerSession expired = BrokerSession.builder()
                .broker(Broker.ZERODHA)
                .userId("GP3319")
                .accessToken("token")
                .valid(true)
                .loginAt(Instant.now().minusSeconds(86400))
                .expiresAt(Instant.now().minusSeconds(60))
                .build();
        state.onLoginSuccess(expired);
        assertThat(state.isLoggedIn()).isFalse();
    }

    @Test
    void isLoggedIn_returns_false_when_session_marked_invalid() {
        BrokerSession invalid = validSession();
        invalid.setValid(false);
        state.onLoginSuccess(invalid);
        assertThat(state.isLoggedIn()).isFalse();
    }

    @Test
    void onHeartbeat_without_broker_skips_persistence_update() {
        // Edge: heartbeat fires before any session is loaded. Should not NPE
        // and must not invoke the sessionStore update.
        state.onHeartbeat(HeartbeatStatus.OK, Instant.now(), null);
        verify(sessionStore, never()).updateHeartbeatStatus(any(), anyString(), any(), anyBoolean());
    }

    @Test
    void setTradeConfigs_defensively_copies_input_list() {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
        List<TradeConfigCombinedDTO> input = new java.util.ArrayList<>(List.of(dto));
        state.setTradeConfigs(input);

        // Mutating the caller's list must not affect cached state.
        input.clear();
        assertThat(state.tradeConfigs()).hasSize(1);
    }

    @Test
    void setTradeConfigs_null_becomes_empty_list() {
        state.setTradeConfigs(null);
        assertThat(state.tradeConfigs()).isEmpty();
    }

    private static BrokerSession validSession() {
        return BrokerSession.builder()
                .broker(Broker.ZERODHA)
                .userId("GP3319")
                .accessToken("kite_test_token")
                .valid(true)
                .loginAt(Instant.now().minusSeconds(60))
                .expiresAt(Instant.now().plusSeconds(86400))
                .build();
    }
}
