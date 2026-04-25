package com.moneymaker.backtesting;

import com.moneymaker.login.config.BrokerProperties;
import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.state.AppMode;
import com.moneymaker.state.AppModeProperties;
import com.moneymaker.state.AppState;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * Renders the {@code /backtest} HTML page. The page is reachable in both
 * modes, but the action button only works when {@code app.mode=backtest}
 * (otherwise the {@link BacktestController} bean is absent and the JS call
 * 404s — surfaced in the UI as a disabled state with a hint).
 */
@Controller
@RequiredArgsConstructor
public class BacktestViewController {

    private final BrokerLoginManager manager;
    private final AppState appState;
    private final BrokerProperties brokerProperties;
    private final AppModeProperties appModeProperties;

    @GetMapping("/backtest")
    public String backtest(Model model) {
        AppMode mode = appModeProperties.getMode();
        model.addAttribute("activePage", "backtest");
        model.addAttribute("appMode", mode);
        model.addAttribute("backtestEnabled", mode == AppMode.BACKTEST);
        model.addAttribute("activeBroker", manager.activeBroker());
        model.addAttribute("availableBrokers", manager.availableBrokers());
        model.addAttribute("loggedIn", appState.isLoggedIn());
        model.addAttribute("sessionValid", appState.isLoggedIn());
        model.addAttribute("lastHeartbeatStatus", appState.getLastHeartbeatStatus());
        model.addAttribute("lastHeartbeatAt", appState.getLastHeartbeatAt());
        model.addAttribute("dataHealthy", appState.isDataHealthy());
        model.addAttribute("brokerProps", brokerProperties);
        return "backtest";
    }
}
