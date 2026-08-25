package com.moneymaker.order.controller;

import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.dto.OrderPurgeRequestDTO;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Read-only API exposing persisted {@link TradeOrder} rows plus a per-row
 * sync endpoint that resolves the actual broker fill price for a given row.
 */
@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final TradeOrderRepository tradeOrderRepository;
    private final OrderService orderService;

    public OrderController(TradeOrderRepository tradeOrderRepository,
                           OrderService orderService) {
        this.tradeOrderRepository = Objects.requireNonNull(tradeOrderRepository, "tradeOrderRepository must not be null");
        this.orderService = Objects.requireNonNull(orderService, "orderService must not be null");
    }

    /**
     * List orders. Optional filters by entry-time range. With no params, returns
     * all orders sorted by id (newest first).
     */
    @GetMapping
    public List<TradeOrder> list(
            @RequestParam(value = "fromDate", required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam(value = "toDate",   required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {

        List<TradeOrder> all = tradeOrderRepository.findAll();
        if (fromDate == null && toDate == null) {
            return all;
        }
        LocalDateTime from = fromDate != null ? LocalDateTime.of(fromDate, LocalTime.MIN) : LocalDateTime.MIN;
        LocalDateTime to   = toDate   != null ? LocalDateTime.of(toDate,   LocalTime.MAX) : LocalDateTime.MAX;
        return all.stream()
                .filter(o -> o.getEntryTime() != null
                        && !o.getEntryTime().isBefore(from)
                        && !o.getEntryTime().isAfter(to))
                .toList();
    }

    /**
     * Clear ledger rows by entry-date. POST rather than DELETE because the
     * selector is a body and {@code dryRun} defaults to {@code true} — a caller
     * that omits it gets a preview, not a wipe. Mirrors
     * {@code /api/trade-configs/auto/delete}.
     */
    @PostMapping("/purge")
    public ResponseEntity<?> purge(@RequestBody OrderPurgeRequestDTO request) {
        try {
            return ResponseEntity.ok(orderService.purge(request));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * Resolve the latest fill state from the active broker for the given row,
     * apply {@code average_price} → {@code entry_price}/{@code exit_price}, and
     * recompute {@code profit}. Returns the updated {@link TradeOrder}.
     */
    @PostMapping("/{id}/sync")
    public ResponseEntity<TradeOrder> sync(@PathVariable("id") Long id) {
        TradeOrder updated = orderService.syncOrder(id);
        return ResponseEntity.ok(updated);
    }
}
