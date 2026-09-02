package com.moneymaker.tradeconfig.controller;

import com.moneymaker.tradeconfig.dto.DowntrendRuleGridFormDTO;
import com.moneymaker.tradeconfig.dto.DowntrendRuleViewDTO;
import com.moneymaker.tradeconfig.service.DowntrendRuleAdminService;
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
 * JSON endpoints behind the Detection rules panel on {@code /trade-configs}.
 *
 * <ul>
 *   <li>{@code GET  /api/downtrend-rules}                 – every rule, with grid + read-only context</li>
 *   <li>{@code GET  /api/downtrend-rules/indicator-types} – registered scanner types (dropdown source)</li>
 *   <li>{@code PUT  /api/downtrend-rules/{id}/grid}       – save one rule's grid / indicator / enabled</li>
 * </ul>
 *
 * <p>The path says {@code /grid} because that is all it edits — the rule's
 * thresholds and bracket stay SQL-only (see the service javadoc).</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/downtrend-rules")
@RequiredArgsConstructor
public class DowntrendRuleAdminController {

    private final DowntrendRuleAdminService service;

    @GetMapping
    public List<DowntrendRuleViewDTO> list() {
        return service.list();
    }

    @GetMapping("/indicator-types")
    public List<String> indicatorTypes() {
        return service.indicatorTypes();
    }

    @PutMapping("/{id}/grid")
    public ResponseEntity<?> updateGrid(@PathVariable Integer id,
                                        @RequestBody DowntrendRuleGridFormDTO form) {
        try {
            return ResponseEntity.ok(service.updateGrid(id, form));
        } catch (IllegalArgumentException e) {
            log.warn("[downtrend-rule] update {} rejected: {}", id, e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
