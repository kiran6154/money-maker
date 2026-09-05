package com.moneymaker.tradeconfig.controller;

import com.moneymaker.tradeconfig.dto.StrategyBracketModeFormDTO;
import com.moneymaker.tradeconfig.dto.StrategyDefaultsViewDTO;
import com.moneymaker.tradeconfig.service.StrategyDefaultsAdminService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * JSON surface behind the Strategy bracket panel on {@code /trade-configs}:
 *
 * <ul>
 *   <li>{@code GET /api/strategy-defaults}                     – every strategy block</li>
 *   <li>{@code GET /api/strategy-defaults/bracket-modes}       – the allowed mode values</li>
 *   <li>{@code PUT /api/strategy-defaults/{id}/bracket-mode}   – flip one strategy's target / SL mode</li>
 * </ul>
 *
 * <p>The path says {@code /bracket-mode} because that is all it edits — the rest
 * of the strategy block stays SQL-only (see the service javadoc).</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/strategy-defaults")
@RequiredArgsConstructor
public class StrategyDefaultsAdminController {

    private final StrategyDefaultsAdminService service;

    @GetMapping
    public List<StrategyDefaultsViewDTO> list() {
        return service.list();
    }

    @GetMapping("/bracket-modes")
    public List<String> bracketModes() {
        return service.bracketModes();
    }

    @PutMapping("/{id}/bracket-mode")
    public ResponseEntity<?> updateBracketMode(@PathVariable Integer id,
                                               @RequestBody StrategyBracketModeFormDTO form) {
        try {
            return ResponseEntity.ok(service.updateBracketModes(id, form));
        } catch (IllegalArgumentException e) {
            log.warn("[strategy-defaults] bracket-mode update {} rejected: {}", id, e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
