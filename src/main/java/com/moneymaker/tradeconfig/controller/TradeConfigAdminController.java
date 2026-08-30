package com.moneymaker.tradeconfig.controller;

import com.moneymaker.state.AppState;
import com.moneymaker.tradeconfig.dto.AutoDeleteRequestDTO;
import com.moneymaker.tradeconfig.dto.InstrumentOptionDTO;
import com.moneymaker.tradeconfig.dto.PagedResponse;
import com.moneymaker.tradeconfig.dto.StrategyOptionDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigFormDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigViewDTO;
import com.moneymaker.tradeconfig.service.ConfirmationRequiredException;
import com.moneymaker.tradeconfig.service.TradeConfigAdminService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * UI + JSON endpoints for trade-config administration.
 *
 * <ul>
 *   <li>{@code GET  /trade-configs}                       – Thymeleaf page</li>
 *   <li>{@code GET  /api/trade-configs?date=&page=&size=} – paged list</li>
 *   <li>{@code GET  /api/trade-configs/{id}}              – single config</li>
 *   <li>{@code POST /api/trade-configs}                   – create</li>
 *   <li>{@code PUT  /api/trade-configs/{id}?confirm=}     – update (409 + {@code confirmRequired} while trades are open)</li>
 *   <li>{@code DELETE /api/trade-configs/{id}}            – delete (blocked if executed trades exist)</li>
 *   <li>{@code POST /api/trade-configs/{id}/active?value=} – retire / reinstate without deleting</li>
 *   <li>{@code POST /api/trade-configs/clone?fromDate=&toDate=&dryRun=} – bulk clone a day's configs</li>
 *   <li>{@code GET  /api/trade-configs/instruments}       – instrument dropdown source</li>
 *   <li>{@code GET  /api/trade-configs/strategies}        – strategy dropdown source</li>
 * </ul>
 */
@Slf4j
@Controller
@RequestMapping
@RequiredArgsConstructor
public class TradeConfigAdminController {

    private final TradeConfigAdminService service;
    private final AppState appState;

    @Value("${app.mode:live}")
    private String appMode;

    @GetMapping("/trade-configs")
    public String page(Model model) {
        model.addAttribute("activePage", "trade-configs");
        model.addAttribute("appMode", appMode);
        model.addAttribute("loggedIn", appState.isLoggedIn());
        model.addAttribute("lastHeartbeatStatus", appState.getLastHeartbeatStatus());
        return "trade-configs";
    }

    @GetMapping("/api/trade-configs")
    @ResponseBody
    public PagedResponse<TradeConfigViewDTO> list(
            @RequestParam(value = "date", required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(value = "page", defaultValue = "0") int page,
            @RequestParam(value = "size", defaultValue = "10") int size) {
        return service.list(date, page, size);
    }

    @GetMapping("/api/trade-configs/{id}")
    @ResponseBody
    public TradeConfigViewDTO get(@PathVariable Integer id) {
        return service.findById(id);
    }

    @PostMapping("/api/trade-configs")
    @ResponseBody
    public ResponseEntity<?> create(@RequestBody TradeConfigFormDTO form) {
        try {
            return ResponseEntity.ok(service.create(form));
        } catch (IllegalArgumentException e) {
            log.warn("[trade-config] create rejected: {}", e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * Update. Returns <b>409 with {@code confirmRequired: true}</b> — not an
     * error — when the config has OPEN trades and the edit touches something
     * those trades still read (GAPS #8). The response names each change so the
     * dialog can show them; re-sending with {@code ?confirm=true} applies the
     * same edit. An edit that only moves the bracket never trips this: those
     * values were snapshotted onto the order at entry.
     */
    @PutMapping("/api/trade-configs/{id}")
    @ResponseBody
    public ResponseEntity<?> update(@PathVariable Integer id,
                                    @RequestBody TradeConfigFormDTO form,
                                    @RequestParam(value = "confirm", defaultValue = "false") boolean confirm) {
        try {
            return ResponseEntity.ok(service.update(id, form, confirm));
        } catch (IllegalArgumentException e) {
            log.warn("[trade-config] update {} rejected: {}", id, e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (ConfirmationRequiredException e) {
            log.info("[trade-config] update {} needs confirmation: {}", id, e.getMessage());
            return ResponseEntity.status(409).body(Map.of(
                    "error", e.getMessage(),
                    "confirmRequired", true,
                    "openTrades", e.getOpenTrades(),
                    "changes", e.getChanges()));
        }
    }

    /**
     * Retire ({@code value=false}) or reinstate ({@code value=true}) a config
     * without deleting it (GAPS #7). A retired config stops being dispatched but
     * keeps its id and its whole trade history; trades already open run to their
     * own exits.
     *
     * <p>POST rather than PUT because it is a row action, not a representation
     * replacement — and deliberately not a field on the edit form, so a stale
     * form cannot flip it as a side effect of an unrelated save.
     */
    @PostMapping("/api/trade-configs/{id}/active")
    @ResponseBody
    public ResponseEntity<?> setActive(@PathVariable Integer id,
                                       @RequestParam("value") boolean value) {
        try {
            return ResponseEntity.ok(service.setActive(id, value));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (IllegalStateException e) {
            // Retire refused because trades are open — same 409 shape as delete,
            // and for the same reason: the ledger holds the config down.
            log.info("[trade-config] retire {} refused: {}", id, e.getMessage());
            return ResponseEntity.status(409).body(Map.of("error", e.getMessage()));
        }
    }

    @DeleteMapping("/api/trade-configs/{id}")
    @ResponseBody
    public ResponseEntity<?> delete(@PathVariable Integer id) {
        try {
            service.delete(id);
            return ResponseEntity.ok(Map.of("deleted", id));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (IllegalStateException e) {
            return ResponseEntity.status(409).body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * Bulk-clone a trading day's configs onto another date (GAPS #9).
     *
     * <p>{@code dryRun} defaults to <b>true</b>, the same shape the bulk delete
     * uses: a caller who omits it gets a preview with the real counts, not a
     * write. Retired configs are left behind and configs already present on
     * {@code toDate} are skipped, both reported separately so the numbers are
     * explained rather than merely small.
     */
    @PostMapping("/api/trade-configs/clone")
    @ResponseBody
    public ResponseEntity<?> clone(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate,
            @RequestParam(value = "dryRun", defaultValue = "true") boolean dryRun) {
        try {
            return ResponseEntity.ok(service.cloneDay(fromDate, toDate, dryRun));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    // ------------------------------------------------------------------
    // Bulk delete of auto-generated (AUTO_DOWNTREND) configs
    // ------------------------------------------------------------------

    /** Per-day counts that paint the bulk-delete calendar. */
    @GetMapping("/api/trade-configs/auto/calendar")
    @ResponseBody
    public ResponseEntity<?> autoCalendar(
            @RequestParam("from") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam("to") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(value = "source", required = false) AutoDeleteRequestDTO.Source source) {
        try {
            return ResponseEntity.ok(service.autoCalendar(from, to, source));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /** Generation runs, newest first — the "undo that run" selector. */
    @GetMapping("/api/trade-configs/auto/runs")
    @ResponseBody
    public List<Map<String, Object>> autoRuns() {
        return service.autoRuns();
    }

    /**
     * Bulk delete. POST rather than DELETE because the selector is a body, and
     * {@code dryRun} defaults to true — a caller that omits it gets a preview, not
     * a deletion.
     */
    @PostMapping("/api/trade-configs/auto/delete")
    @ResponseBody
    public ResponseEntity<?> autoDelete(@RequestBody AutoDeleteRequestDTO request) {
        try {
            return ResponseEntity.ok(service.deleteAuto(request));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @GetMapping("/api/trade-configs/instruments")
    @ResponseBody
    public List<InstrumentOptionDTO> instruments() {
        return service.listInstruments();
    }

    @GetMapping("/api/trade-configs/strategies")
    @ResponseBody
    public List<StrategyOptionDTO> strategies() {
        return service.listStrategies();
    }
}
