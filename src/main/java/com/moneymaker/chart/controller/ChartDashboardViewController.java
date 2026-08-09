package com.moneymaker.chart.controller;

import com.moneymaker.login.config.BrokerProperties;
import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.state.AppState;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * Renders the chart dashboard page shell. The page itself is server-rendered
 * via Thymeleaf; data is loaded separately through the chart REST API.
 */
@Controller
@RequiredArgsConstructor
public class ChartDashboardViewController {

    private final BrokerLoginManager manager;
    private final AppState appState;
    private final BrokerProperties brokerProperties;

    @GetMapping("/charts/dashboard")
    public String dashboard(Model model) {
        model.addAttribute("activePage", "charts");
        model.addAttribute("activeBroker", manager.activeBroker());
        model.addAttribute("availableBrokers", manager.availableBrokers());
        model.addAttribute("loggedIn", appState.isLoggedIn());
        model.addAttribute("sessionValid", appState.isLoggedIn());
        model.addAttribute("lastHeartbeatStatus", appState.getLastHeartbeatStatus());
        model.addAttribute("lastHeartbeatAt", appState.getLastHeartbeatAt());
        model.addAttribute("dataHealthy", appState.isDataHealthy());
        model.addAttribute("brokerProps", brokerProperties);
        return "chart-dashboard";
    }
}
