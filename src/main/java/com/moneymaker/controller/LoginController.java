package com.moneymaker.controller;

import com.moneymaker.login.config.BrokerProperties;
import com.moneymaker.login.exception.BrokerLoginException;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.service.BrokerLoginManager;
import com.moneymaker.login.service.BrokerLoginService;
import com.moneymaker.login.service.BrokerSessionStore;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.util.Map;

/**
 * UI + JSON endpoints for broker login.
 *
 * <ul>
 *   <li>{@code GET /}                – dashboard (session summary)</li>
 *   <li>{@code GET /login}           – broker selector page</li>
 *   <li>{@code GET /login/start}     – redirect to active broker's login URL</li>
 *   <li>{@code GET /login/callback}  – Zerodha OAuth redirect handler</li>
 *   <li>{@code GET /login/manual}    – manual TOTP form (Groww)</li>
 *   <li>{@code POST /login/manual}   – submit TOTP form</li>
 *   <li>{@code POST /logout}         – clear current session</li>
 *   <li>{@code GET /api/session}     – JSON session snapshot</li>
 * </ul>
 */
@Slf4j
@Controller
public class LoginController {

    private final BrokerLoginManager manager;
    private final BrokerSessionStore store;
    private final BrokerProperties properties;

    public LoginController(BrokerLoginManager manager,
                           BrokerSessionStore store,
                           BrokerProperties properties) {
        this.manager = manager;
        this.store = store;
        this.properties = properties;
    }

    @GetMapping("/")
    public String dashboard(Model model) {
        populateCommon(model);
        model.addAttribute("activePage", "dashboard");
        return "index";
    }

    @GetMapping("/login")
    public String loginPage(Model model) {
        populateCommon(model);
        model.addAttribute("activePage", "login");
        return "login";
    }

    @GetMapping("/login/start")
    public String startLogin() {
        BrokerLoginService active = manager.active();
        String url = active.getLoginUrl();
        log.info("Starting login flow for {} -> {}", active.getBroker(), url);
        return "redirect:" + url;
    }

    /** Zerodha OAuth callback: ?request_token=xxx&action=login&status=success */
    @GetMapping("/login/callback")
    public String callback(@RequestParam(value = "request_token", required = false) String requestToken,
                           @RequestParam(value = "status", required = false) String status,
                           RedirectAttributes ra) {
        if (requestToken == null || requestToken.isBlank()) {
            ra.addFlashAttribute("alert", flash(false, "Login cancelled or missing request_token (status=" + status + ")"));
            return "redirect:/login";
        }
        try {
            BrokerLoginResponse resp = manager.forBroker(Broker.ZERODHA)
                    .completeLogin(BrokerLoginRequest.builder().requestToken(requestToken).build());
            return handleResponse(resp, ra);
        } catch (BrokerLoginException e) {
            log.error("Zerodha callback failed", e);
            ra.addFlashAttribute("alert", flash(false, e.getMessage()));
            return "redirect:/login";
        }
    }

    @GetMapping("/login/manual")
    public String manualForm(@RequestParam(value = "broker", required = false) String brokerName,
                             Model model) {
        populateCommon(model);
        model.addAttribute("targetBroker",
                brokerName != null ? brokerName.toUpperCase() : manager.activeBroker().name());
        model.addAttribute("activePage", "login");
        return "manual-login";
    }

    @PostMapping("/login/manual")
    public String manualSubmit(@RequestParam("broker") String brokerName,
                               @RequestParam(value = "totp", required = false) String totp,
                               @RequestParam(value = "requestToken", required = false) String requestToken,
                               RedirectAttributes ra) {
        try {
            Broker broker = Broker.fromString(brokerName);
            BrokerLoginRequest req = BrokerLoginRequest.builder()
                    .totp(totp)
                    .requestToken(requestToken)
                    .build();
            BrokerLoginResponse resp = manager.forBroker(broker).completeLogin(req);
            return handleResponse(resp, ra);
        } catch (Exception e) {
            log.error("Manual login failed", e);
            ra.addFlashAttribute("alert", flash(false, e.getMessage()));
            return "redirect:/login";
        }
    }

    @PostMapping("/logout")
    public String logout(RedirectAttributes ra) {
        store.current().ifPresent(s -> {
            try { manager.forBroker(s.getBroker()).logout(s); } catch (Exception ignored) {}
        });
        store.clear();
        ra.addFlashAttribute("alert", flash(true, "Logged out."));
        return "redirect:/";
    }

    @GetMapping("/api/session")
    @ResponseBody
    public Map<String, Object> sessionJson() {
        BrokerSession s = store.current().orElse(null);
        return Map.of(
                "activeBroker", manager.activeBroker().name(),
                "available", manager.availableBrokers().stream().map(Enum::name).toList(),
                "valid", store.isValid(),
                "session", s == null ? Map.of() : Map.of(
                        "broker", s.getBroker(),
                        "userId", s.getUserId() == null ? "" : s.getUserId(),
                        "loginAt", s.getLoginAt(),
                        "expiresAt", s.getExpiresAt(),
                        "expired", s.isExpired()
                )
        );
    }

    /* ---------- helpers ---------- */

    private String handleResponse(BrokerLoginResponse resp, RedirectAttributes ra) {
        if (resp.isSuccess() && resp.getSession() != null) {
            store.save(resp.getSession());
            ra.addFlashAttribute("alert", flash(true, "Login successful for " + resp.getSession().getBroker()));
            return "redirect:/";
        }
        ra.addFlashAttribute("alert", flash(false, "Login failed: " + resp.getMessage()));
        return "redirect:/login";
    }

    private void populateCommon(Model model) {
        model.addAttribute("activeBroker", manager.activeBroker());
        model.addAttribute("availableBrokers", manager.availableBrokers());
        model.addAttribute("session", store.current().orElse(null));
        model.addAttribute("sessionValid", store.isValid());
        model.addAttribute("brokerProps", properties);
    }

    private static Map<String, Object> flash(boolean ok, String message) {
        return Map.of("success", ok, "message", message);
    }
}

