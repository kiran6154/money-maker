package com.moneymaker.login.service;

import com.moneymaker.broker.angelone.AngelOneLoginService;
import com.moneymaker.broker.groww.GrowwLoginService;
import com.moneymaker.broker.zerodha.ZerodhaLoginService;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.state.AppState;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link LoginOrchestrator}.
 *
 * <p>Four outcomes drive the matrix: ALREADY_VALID, LOGGED_IN (TOTP auto),
 * INTERACTIVE_REQUIRED (Zerodha), FAILED (TOTP threw / returned failure).
 * Tests use concrete subclasses of broker login services so the instanceof
 * checks in the orchestrator dispatch correctly.
 */
class LoginOrchestratorTest {

    @Mock private BrokerLoginManager manager;
    @Mock private AppState appState;
    @Mock private NotificationService notifier;

    @Mock private GrowwLoginService growwSvc;
    @Mock private AngelOneLoginService angelSvc;
    @Mock private ZerodhaLoginService zerodhaSvc;

    private LoginOrchestrator orchestrator;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        orchestrator = new LoginOrchestrator(manager, appState, notifier);
    }

    @Test
    void ensureLoggedIn_returns_ALREADY_VALID_when_session_valid() {
        BrokerSession session = sessionFor(Broker.GROWW);
        when(manager.active()).thenReturn(growwSvc);
        when(appState.currentSession()).thenReturn(Optional.of(session));
        when(growwSvc.validateSession(session)).thenReturn(true);
        lenient().when(growwSvc.getBroker()).thenReturn(Broker.GROWW);

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.ALREADY_VALID);
        verify(appState, never()).onLoginSuccess(any());
        verify(notifier, never()).alertLoginSuccess(any(), any());
    }

    @Test
    void ensureLoggedIn_triggers_TOTP_login_when_no_session() {
        when(manager.active()).thenReturn(growwSvc);
        when(appState.currentSession()).thenReturn(Optional.empty());
        when(growwSvc.getBroker()).thenReturn(Broker.GROWW);
        BrokerSession freshSession = sessionFor(Broker.GROWW);
        BrokerLoginResponse resp = BrokerLoginResponse.builder()
                .success(true).session(freshSession).build();
        when(growwSvc.completeLogin(any(BrokerLoginRequest.class))).thenReturn(resp);

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.LOGGED_IN);
        verify(appState).onLoginSuccess(freshSession);
        verify(notifier).alertLoginSuccess(eq(Broker.GROWW), any());
    }

    @Test
    void ensureLoggedIn_triggers_TOTP_login_when_session_invalid() {
        // Cached but validateSession says false → auto-login.
        BrokerSession stale = sessionFor(Broker.ANGEL_ONE);
        when(manager.active()).thenReturn(angelSvc);
        when(appState.currentSession()).thenReturn(Optional.of(stale));
        when(angelSvc.validateSession(stale)).thenReturn(false);
        when(angelSvc.getBroker()).thenReturn(Broker.ANGEL_ONE);
        BrokerSession fresh = sessionFor(Broker.ANGEL_ONE);
        when(angelSvc.completeLogin(any(BrokerLoginRequest.class)))
                .thenReturn(BrokerLoginResponse.builder().success(true).session(fresh).build());

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.LOGGED_IN);
        verify(appState).onLoginSuccess(fresh);
    }

    @Test
    void ensureLoggedIn_returns_FAILED_when_TOTP_login_returns_failure() {
        when(manager.active()).thenReturn(growwSvc);
        when(appState.currentSession()).thenReturn(Optional.empty());
        when(growwSvc.getBroker()).thenReturn(Broker.GROWW);
        when(growwSvc.completeLogin(any(BrokerLoginRequest.class)))
                .thenReturn(BrokerLoginResponse.builder()
                        .success(false).message("invalid TOTP").build());

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.FAILED);
        verify(notifier).alertLoginFailed(eq(Broker.GROWW), eq("invalid TOTP"));
        verify(appState, never()).onLoginSuccess(any());
    }

    @Test
    void ensureLoggedIn_returns_FAILED_when_TOTP_login_throws() {
        when(manager.active()).thenReturn(growwSvc);
        when(appState.currentSession()).thenReturn(Optional.empty());
        when(growwSvc.getBroker()).thenReturn(Broker.GROWW);
        when(growwSvc.completeLogin(any(BrokerLoginRequest.class)))
                .thenThrow(new RuntimeException("network down"));

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.FAILED);
        verify(notifier).alertLoginFailed(eq(Broker.GROWW), eq("network down"));
    }

    @Test
    void ensureLoggedIn_returns_INTERACTIVE_REQUIRED_for_Zerodha_without_session() {
        when(manager.active()).thenReturn(zerodhaSvc);
        when(appState.currentSession()).thenReturn(Optional.empty());
        when(zerodhaSvc.getBroker()).thenReturn(Broker.ZERODHA);
        when(zerodhaSvc.getLoginUrl()).thenReturn("https://kite.zerodha.com/login");

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.INTERACTIVE_REQUIRED);
        verify(notifier).alertLoginFailed(eq(Broker.ZERODHA), any());
        // No auto-login attempt was made for Zerodha.
        verify(zerodhaSvc, never()).completeLogin(any());
    }

    @Test
    void validateSession_throwing_is_treated_as_invalid_session() {
        // safeValidate catches the exception and falls through to auto-login.
        BrokerSession session = sessionFor(Broker.GROWW);
        when(manager.active()).thenReturn(growwSvc);
        when(appState.currentSession()).thenReturn(Optional.of(session));
        when(growwSvc.validateSession(session)).thenThrow(new RuntimeException("broker down"));
        when(growwSvc.getBroker()).thenReturn(Broker.GROWW);
        BrokerSession fresh = sessionFor(Broker.GROWW);
        when(growwSvc.completeLogin(any(BrokerLoginRequest.class)))
                .thenReturn(BrokerLoginResponse.builder().success(true).session(fresh).build());

        LoginOrchestrator.Outcome outcome = orchestrator.ensureLoggedIn();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.LOGGED_IN);
    }

    @Test
    void forceLogin_skips_session_validity_and_always_auto_logs_in() {
        // Even with a valid session, forceLogin re-issues.
        BrokerSession valid = sessionFor(Broker.GROWW);
        when(manager.active()).thenReturn(growwSvc);
        when(growwSvc.getBroker()).thenReturn(Broker.GROWW);
        BrokerSession fresh = sessionFor(Broker.GROWW);
        when(growwSvc.completeLogin(any(BrokerLoginRequest.class)))
                .thenReturn(BrokerLoginResponse.builder().success(true).session(fresh).build());

        LoginOrchestrator.Outcome outcome = orchestrator.forceLogin();

        assertThat(outcome).isEqualTo(LoginOrchestrator.Outcome.LOGGED_IN);
        // currentSession is never consulted in forceLogin.
        verify(appState, never()).currentSession();
        verify(appState).onLoginSuccess(fresh);
    }

    /* ---------------- helpers ---------------- */

    private static BrokerSession sessionFor(Broker b) {
        return BrokerSession.builder()
                .broker(b)
                .userId("u1")
                .accessToken("tok")
                .valid(true)
                .build();
    }
}
