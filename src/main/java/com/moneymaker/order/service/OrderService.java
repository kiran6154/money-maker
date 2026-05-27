package com.moneymaker.order.service;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Queue;

/**
 * Consumes {@link TradeSignal}s emitted by strategies, applies cross-signal
 * rules from {@link TradeConfigCombinedDTO}, persists the resulting
 * {@link TradeOrder} record, and delegates the venue call to the active
 * {@link OrderPlacementService} chosen by {@link OrderPlacementFactory}.
 *
 * <p>Open-position lookup is DB-backed so a SELL→BUY sequence on the same
 * (config, instrument, optionType) closes the open position rather than being
 * deduped as a duplicate.
 */
@Slf4j
@Service
public class OrderService {

    static final String STATUS_OPEN = "OPEN";
    static final String STATUS_CLOSED = "CLOSED";

    static final String FILL_PENDING = "PENDING";
    static final String FILL_BACKTEST = "BACKTEST";
    static final String FILL_COMPLETE = "COMPLETE";
    /** Row was force-closed locally but the broker exit order failed. Operator action required. */
    static final String FILL_EXIT_FAILED = "EXIT_FAILED";

    static final String BACKTESTING_NAME = "BACKTESTING";

    private final OrderPlacementFactory placementFactory;
    private final TradeOrderRepository tradeOrderRepository;
    private final NotificationService notifier;

    public OrderService(OrderPlacementFactory placementFactory,
                        TradeOrderRepository tradeOrderRepository,
                        NotificationService notifier) {
        this.placementFactory = Objects.requireNonNull(placementFactory, "placementFactory must not be null");
        this.tradeOrderRepository = Objects.requireNonNull(tradeOrderRepository, "tradeOrderRepository must not be null");
        this.notifier = Objects.requireNonNull(notifier, "notifier must not be null");
    }

    public void processOrders() {
        Queue<TradeSignal> signals = SharedData.tradeSignals;
        if (signals == null || signals.isEmpty()) return;

        OrderPlacementService placement = placementFactory.active();

        TradeSignal signal;
        while ((signal = signals.poll()) != null) {
            try {
                handleSignal(signal, placement);
            } catch (Exception ex) {
                log.error("Failed to handle signal {}", signal, ex);
            }
        }
    }

    private void handleSignal(TradeSignal signal, OrderPlacementService placement) {
        if (signal == null || signal.getStrikeKey() == null || signal.getAction() == null) return;

        TradeConfigCombinedDTO config = findConfig(signal.getTradeConfigId());
        if (config == null) {
            log.warn("Skipping signal — no config for tradeConfigId={}", signal.getTradeConfigId());
            return;
        }

        ParsedKey key = ParsedKey.from(signal.getStrikeKey());
        if (key == null) {
            log.warn("Skipping signal — unparseable strikeKey={}", signal.getStrikeKey());
            return;
        }

        // Match by optionToken (unique per strike+expiry+type) — matching by
        // (instrumentToken, optionType) alone collides across strikes on the same
        // underlying, so a 24100 CE signal would falsely close a 24200 CE open.
        Optional<TradeOrder> openOpt = tradeOrderRepository
                .findFirstByTradeConfigIdAndOptionTokenAndStatus(
                        signal.getTradeConfigId(), key.optionToken, STATUS_OPEN);

        if (openOpt.isPresent()) {
            TradeOrder open = openOpt.get();
            if (sameDirection(open.getEntryDirection(), signal.getAction())) {
                log.debug("[order] skip signal — open trade already exists in same direction: id={}, dir={}",
                        open.getId(), open.getEntryDirection());
                return;
            }
            // Opposite direction → close it.
            closeOrder(open, signal, config, placement);
            return;
        }

        // No open position. A new entry is only legal when the signal direction
        // matches the configured transactionType — strategies are intentionally
        // one-sided (e.g. SELL-only intraday); BUY signals are exit-only.
        String configTxn = config.getTradeConfig() != null ? config.getTradeConfig().getTransactionType() : null;
        if (configTxn != null && !configTxn.isBlank()
                && !configTxn.trim().equalsIgnoreCase(signal.getAction().name())) {
            log.debug("[order] skip signal — direction {} != config.transactionType {} (entry suppressed)",
                    signal.getAction(), configTxn);
            return;
        }

        // Per-day cap: respect TradeConfig.numberOfTradesPerDay if set. Counts
        // all entries for this config today (across all strikes, OPEN + CLOSED).
        // Null / non-positive means no cap — re-entries are allowed by default,
        // including on the same strike after a CLOSED trade earlier in the day.
        Integer maxPerDay = config.getTradeConfig() != null
                ? config.getTradeConfig().getNumberOfTradesPerDay()
                : null;
        if (maxPerDay != null && maxPerDay > 0) {
            LocalDateTime startOfDay = signal.getSignalTime().toLocalDate().atStartOfDay();
            LocalDateTime endOfDay   = startOfDay.plusDays(1).minusNanos(1);
            long todayCount = tradeOrderRepository
                    .countByTradeConfigIdAndEntryTimeBetween(
                            signal.getTradeConfigId(), startOfDay, endOfDay);
            if (todayCount >= maxPerDay) {
                log.debug("[order] skip signal — numberOfTradesPerDay={} reached for tradeConfigId={} (todayCount={})",
                        maxPerDay, signal.getTradeConfigId(), todayCount);
                return;
            }
        }

        // Daily realised-loss cap: TradeConfig.maxLoss stops this strategy from
        // opening new trades once today's CLOSED P&L has dropped below
        // -maxLoss. Floating P&L on OPEN trades is intentionally NOT counted —
        // the cap is a *realised* threshold so a temporary drawdown on a
        // still-open trade doesn't choke off legitimate re-entries. Null /
        // non-positive maxLoss means no cap.
        BigDecimal maxLoss = config.getTradeConfig() != null
                ? config.getTradeConfig().getMaxLoss()
                : null;
        if (maxLoss != null && maxLoss.signum() > 0) {
            LocalDateTime sodMax = signal.getSignalTime().toLocalDate().atStartOfDay();
            LocalDateTime eodMax = sodMax.plusDays(1).minusNanos(1);
            BigDecimal realised = tradeOrderRepository.sumRealisedProfitForDay(
                    signal.getTradeConfigId(), sodMax, eodMax);
            if (realised == null) realised = BigDecimal.ZERO;
            if (realised.compareTo(maxLoss.negate()) <= 0) {
                log.debug("[order] skip signal — daily maxLoss={} reached for tradeConfigId={} (realised={})",
                        maxLoss, signal.getTradeConfigId(), realised);
                return;
            }
        }

        // Concurrent-direction cap: TradeConfig.numberOfParallelTrades caps how
        // many OPEN trades in the same direction this config can hold at any
        // moment. Counts only OPEN rows for this config + this signal's
        // direction (BUY / SELL). Null / non-positive means no cap.
        Integer maxParallel = config.getTradeConfig() != null
                ? config.getTradeConfig().getNumberOfParallelTrades()
                : null;
        if (maxParallel != null && maxParallel > 0) {
            long openSameDir = tradeOrderRepository
                    .countByTradeConfigIdAndEntryDirectionAndStatus(
                            signal.getTradeConfigId(),
                            signal.getAction().name(),
                            STATUS_OPEN);
            if (openSameDir >= maxParallel) {
                log.debug("[order] skip signal — numberOfParallelTrades={} reached for tradeConfigId={} dir={} (openSameDir={})",
                        maxParallel, signal.getTradeConfigId(), signal.getAction(), openSameDir);
                return;
            }
        }

        // Exact-duplicate guard: re-runs of the backtest replay identical signals
        // and would otherwise create a fresh row each run. Skip when an existing
        // row has the same (config, optionToken, direction, entryTime) — that's
        // the same trade. Legitimate re-entries on the same strike later in the
        // day fire at a different entryTime and are unaffected.
        boolean exactDuplicate = tradeOrderRepository
                .existsByTradeConfigIdAndOptionTokenAndEntryDirectionAndEntryTime(
                        signal.getTradeConfigId(), key.optionToken,
                        signal.getAction().name(), signal.getSignalTime());
        if (exactDuplicate) {
            log.debug("[order] skip signal — exact duplicate exists: tradeConfigId={} optionToken={} dir={} entryTime={}",
                    signal.getTradeConfigId(), key.optionToken, signal.getAction(), signal.getSignalTime());
            return;
        }

        openOrder(signal, key, config, placement);
    }

    private void openOrder(TradeSignal signal, ParsedKey key, TradeConfigCombinedDTO config,
                           OrderPlacementService placement) {
        if (signal.getPrice() == null) {
            log.warn("Skipping open — signal has no price: {}", signal);
            return;
        }

        TradeOrder order = new TradeOrder();
        order.setTradeConfigId(signal.getTradeConfigId());
        order.setInstrumentName(instrumentName(config));
        order.setInstrumentToken(key.instrumentToken);
        order.setOptionStrike(parseInt(key.strike));
        order.setOptionType(key.optionType);
        order.setOptionToken(key.optionToken);
        order.setEntryDirection(signal.getAction().name());
        order.setEntryTime(signal.getSignalTime());
        order.setEntryPrice(signal.getPrice());
        order.setEntryReason(buildEntryReason(signal));
        order.setStrategyId(config != null && config.getTradeConfig() != null
                ? config.getTradeConfig().getStratergyId() : null);
        order.setStatus(STATUS_OPEN);
        order.setFillStatus(initialFillStatus(placement));
        // Snapshot SL / target so PositionService doesn't depend on SharedData
        // staying populated and so mid-trade config edits don't retroactively
        // close already-open trades.
        if (config != null && config.getTradeConfig() != null) {
            order.setTargetAtEntry(config.getTradeConfig().getTarget());
            order.setStopLossAtEntry(config.getTradeConfig().getStopLoss());
        }
        // Seed peak P&L tracking at the entry baseline (0). The position monitor
        // then reports max(0, observed P&L) and min(0, observed P&L) — which
        // means peak_profit ≥ 0 and peak_loss ≤ 0 always, and they're meaningful
        // even on a trade that closes after a single monitor tick.
        order.setPeakProfit(BigDecimal.ZERO);
        order.setPeakLoss(BigDecimal.ZERO);

        order = tradeOrderRepository.save(order);

        String brokerOrderId = placement.place(order, config);
        if (brokerOrderId != null) {
            order.setEntryBrokerOrderId(brokerOrderId);
            order.setFillStatus(FILL_PENDING);
            order = tradeOrderRepository.save(order);
        }

        log.info("[order] OPEN id={} via {} tradeConfigId={} dir={} {} {}{} @ {} brokerOrderId={} fillStatus={}",
                order.getId(), placement.getName(), order.getTradeConfigId(), order.getEntryDirection(),
                order.getInstrumentName(), order.getOptionStrike(), order.getOptionType(), order.getEntryPrice(),
                order.getEntryBrokerOrderId(), order.getFillStatus());
        notifier.alertOrderOpened(order);
    }

    private void closeOrder(TradeOrder open, TradeSignal signal, TradeConfigCombinedDTO config,
                            OrderPlacementService placement) {
        if (signal.getPrice() == null) {
            log.warn("Skipping close — signal has no price: {}", signal);
            return;
        }

        open.setExitTime(signal.getSignalTime());
        open.setExitPrice(signal.getPrice());
        open.setProfit(perShareProfit(open.getEntryDirection(), open.getEntryPrice(), signal.getPrice()));
        open.setStatus(STATUS_CLOSED);
        open.setExitReason("SIGNAL");
        open.setFillStatus(initialFillStatus(placement));

        open = tradeOrderRepository.save(open);

        String brokerOrderId = placement.place(open, config);
        if (brokerOrderId != null) {
            open.setExitBrokerOrderId(brokerOrderId);
            open.setFillStatus(FILL_PENDING);
            open = tradeOrderRepository.save(open);
        }

        log.info("[order] CLOSE id={} via {} dir={} {} entry={} → exit={} profit/share={} brokerOrderId={} fillStatus={}",
                open.getId(), placement.getName(), open.getEntryDirection(),
                open.getInstrumentName(), open.getEntryPrice(), open.getExitPrice(), open.getProfit(),
                open.getExitBrokerOrderId(), open.getFillStatus());
        notifier.alertOrderClosed(open);
    }

    private String initialFillStatus(OrderPlacementService placement) {
        return BACKTESTING_NAME.equalsIgnoreCase(placement.getName()) ? FILL_BACKTEST : FILL_PENDING;
    }

    /**
     * Resolves the latest fill state for {@code orderId} against the active broker
     * and updates {@code entry_price} / {@code exit_price} / {@code fill_status}
     * (and recomputes {@code profit}) accordingly.
     *
     * <p>Picks which leg to sync from {@link TradeOrder#getStatus()}: an OPEN row
     * syncs the entry leg; a CLOSED row syncs the exit leg.
     */
    public TradeOrder syncOrder(Long orderId) {
        TradeOrder order = tradeOrderRepository.findById(orderId)
                .orElseThrow(() -> new IllegalArgumentException("No order with id " + orderId));

        boolean syncingExit = STATUS_CLOSED.equalsIgnoreCase(order.getStatus());
        String brokerOrderId = syncingExit ? order.getExitBrokerOrderId() : order.getEntryBrokerOrderId();
        if (brokerOrderId == null || brokerOrderId.isBlank()) {
            log.debug("syncOrder skipped — no broker order id for orderId={}, syncingExit={}", orderId, syncingExit);
            return order;
        }

        OrderPlacementService placement = placementFactory.active();
        FillSnapshot snap = placement.syncFill(brokerOrderId);
        if (snap == null) {
            log.debug("syncOrder — placement returned no snapshot for orderId={}, brokerOrderId={}", orderId, brokerOrderId);
            return order;
        }

        if (snap.getAveragePrice() != null) {
            if (syncingExit) {
                order.setExitPrice(snap.getAveragePrice());
                if (order.getEntryPrice() != null) {
                    order.setProfit(perShareProfit(order.getEntryDirection(),
                            order.getEntryPrice(), snap.getAveragePrice()));
                }
            } else {
                order.setEntryPrice(snap.getAveragePrice());
                if (STATUS_CLOSED.equalsIgnoreCase(order.getStatus()) && order.getExitPrice() != null) {
                    order.setProfit(perShareProfit(order.getEntryDirection(),
                            snap.getAveragePrice(), order.getExitPrice()));
                }
            }
        }

        if (snap.getStatus() != null) {
            order.setFillStatus(snap.getStatus());
        }

        order = tradeOrderRepository.save(order);
        log.info("Synced order id={} leg={} brokerOrderId={} → fillStatus={}, avgPrice={}",
                order.getId(), syncingExit ? "EXIT" : "ENTRY", brokerOrderId,
                order.getFillStatus(), snap.getAveragePrice());
        return order;
    }

    /**
     * Closes an OPEN trade outside the strategy-signal flow — used by the
     * position monitor when a target / stop-loss is hit. Persists the exit
     * leg, recomputes profit, calls the active placement service for the
     * exit broker call, and emits the closed-order alert.
     *
     * <p>{@code reason} is stored on the row ({@code TARGET}, {@code STOP_LOSS},
     * {@code FORCE_CLOSE}, etc.) so the ledger explains why the trade ended.
     */
    public TradeOrder closeManually(Long orderId, BigDecimal exitPrice, LocalDateTime exitTime, String reason) {
        TradeOrder order = tradeOrderRepository.findById(orderId)
                .orElseThrow(() -> new IllegalArgumentException("No order with id " + orderId));
        if (!STATUS_OPEN.equalsIgnoreCase(order.getStatus())) {
            log.debug("closeManually skipped — orderId={} already in status {}", orderId, order.getStatus());
            return order;
        }
        if (exitPrice == null) {
            log.warn("closeManually skipped — no exit price for orderId={}", orderId);
            return order;
        }

        OrderPlacementService placement = placementFactory.active();
        TradeConfigCombinedDTO config = findConfig(order.getTradeConfigId());

        order.setExitTime(exitTime != null ? exitTime : LocalDateTime.now());
        order.setExitPrice(exitPrice);
        order.setProfit(perShareProfit(order.getEntryDirection(), order.getEntryPrice(), exitPrice));
        order.setStatus(STATUS_CLOSED);
        order.setExitReason(reason);
        order.setFillStatus(initialFillStatus(placement));

        order = tradeOrderRepository.save(order);

        if (config != null) {
            String brokerOrderId = placement.place(order, config);
            if (brokerOrderId != null) {
                order.setExitBrokerOrderId(brokerOrderId);
                order.setFillStatus(FILL_PENDING);
                order = tradeOrderRepository.save(order);
            }
        }

        log.info("Closed order manually id={} reason={} entry={} → exit={} profit/share={}",
                order.getId(), reason, order.getEntryPrice(), exitPrice, order.getProfit());
        notifier.alertOrderClosed(order);
        return order;
    }

    /**
     * Force-closes every {@link #STATUS_OPEN} trade entered on {@code tradingDate}
     * at {@code closeAt}. Used by {@code BacktestAnalysisService} at end-of-day so
     * intraday strategies don't carry positions overnight when the close-signal
     * strike has fallen out of the active-strike set before market close.
     *
     * <p>Exit price is taken from the cached {@code SharedData} candle data for
     * the option (latest candle ≤ {@code closeAt}); falls back to entry price
     * (zero P&L) if no cached price is available.
     */
    public int forceCloseOpenPositions(LocalDate tradingDate, LocalDateTime closeAt) {
        LocalDateTime startOfDay = tradingDate.atStartOfDay();
        LocalDateTime endOfDay   = startOfDay.plusDays(1).minusNanos(1);

        List<TradeOrder> openToday = tradeOrderRepository
                .findByStatusAndEntryTimeBetween(STATUS_OPEN, startOfDay, endOfDay);
        if (openToday.isEmpty()) return 0;

        // Active placement: BACKTESTING (no-op) in backtest mode; a real broker
        // placement in live. The distinction matters below — a null broker order
        // id from BACKTESTING is "normal"; a null from a live broker means the
        // exit attempt failed and the row stays OPEN with fill_status=EXIT_FAILED.
        OrderPlacementService placement = placementFactory.active();
        boolean isBacktestPlacement = BACKTESTING_NAME.equalsIgnoreCase(placement.getName());

        int closed = 0;
        for (TradeOrder order : openToday) {
            BigDecimal exitPrice = lastPriceFor(order.getOptionToken(), closeAt);
            if (exitPrice == null) {
                log.warn("Force-close: no cached price for optionToken={}, falling back to entryPrice for orderId={}",
                        order.getOptionToken(), order.getId());
                exitPrice = order.getEntryPrice();
            }

            // Local fields populated FIRST so place(order) can read status=CLOSED
            // and infer the opposite-direction broker call (see e.g.
            // ZerodhaOrderPlacementService.transactionType).
            order.setExitTime(closeAt);
            order.setExitPrice(exitPrice);
            order.setProfit(perShareProfit(order.getEntryDirection(), order.getEntryPrice(), exitPrice));
            order.setStatus(STATUS_CLOSED);
            order.setExitReason("FORCE_CLOSE");
            order.setFillStatus(initialFillStatus(placement));

            // M3: attempt the real broker exit. In backtest the call returns null
            // (FILL_BACKTEST stays). In live, a successful call returns the broker
            // order id; a null return means the broker call failed — we keep the
            // row OPEN, mark fill_status=EXIT_FAILED, and alert ops loudly.
            String brokerOrderId = null;
            try {
                brokerOrderId = placement.place(order, findConfig(order.getTradeConfigId()));
            } catch (Exception ex) {
                log.error("Force-close placement threw for orderId={}", order.getId(), ex);
            }

            if (brokerOrderId != null) {
                order.setExitBrokerOrderId(brokerOrderId);
                order.setFillStatus(FILL_PENDING);
                order = tradeOrderRepository.save(order);
                log.info("[order] FORCE_CLOSE id={} dir={} entry={} → exit={} profit/share={} brokerOrderId={}",
                        order.getId(), order.getEntryDirection(),
                        order.getEntryPrice(), exitPrice, order.getProfit(), brokerOrderId);
                notifier.alertOrderForceClosed(order);
                closed++;
                continue;
            }

            if (isBacktestPlacement) {
                // Backtest path — null broker id is expected.
                order = tradeOrderRepository.save(order);
                log.info("[order] FORCE_CLOSE id={} dir={} entry={} → exit={} profit/share={} (backtest)",
                        order.getId(), order.getEntryDirection(),
                        order.getEntryPrice(), exitPrice, order.getProfit());
                notifier.alertOrderForceClosed(order);
                closed++;
                continue;
            }

            // Live placement failed — the broker position is still open. Keep
            // our row OPEN so a retry (manual or via the DaySummary 15:31 cron)
            // can try again. Alert ops CRITICAL with the row details.
            order.setStatus(STATUS_OPEN);
            order.setExitTime(null);
            order.setExitPrice(null);
            order.setProfit(null);
            order.setExitReason(null);
            order.setFillStatus(FILL_EXIT_FAILED);
            order = tradeOrderRepository.save(order);
            log.error("[order] FORCE_CLOSE FAILED id={} — broker exit returned null; row kept OPEN with fill_status=EXIT_FAILED",
                    order.getId());
            notifier.alertOrderExitFailed(order, "broker placeOrder returned null");
        }
        return closed;
    }

    /**
     * Pulls the last close price for {@code optionToken} from the cached
     * {@code SharedData.strikeMarketDataByInstrumentAndInterval} entries — keys
     * are {@code <instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|...},
     * so we match by the optionToken segment. Returns {@code null} if no cached
     * candle is available.
     */
    private BigDecimal lastPriceFor(String optionToken, LocalDateTime atOrBefore) {
        if (optionToken == null) return null;
        Map<String, List<MarketData>> cache = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) return null;

        // M1.1: iterate keys in natural order, not ConcurrentHashMap's
        // non-deterministic iteration order. Multiple cache entries can
        // share the same optionToken (different itm/otm depths in the key
        // suffix) — without sorting, which entry's "last close" wins varies
        // run-to-run. The sort makes force-close exit prices stable for
        // reproducibility.
        java.util.List<String> orderedKeys = new java.util.ArrayList<>(cache.keySet());
        java.util.Collections.sort(orderedKeys);

        for (String key : orderedKeys) {
            String[] parts = key.split("\\|");
            if (parts.length < 5) continue;
            if (!optionToken.equals(parts[4])) continue;

            List<MarketData> list = cache.get(key);
            if (list == null || list.isEmpty()) continue;
            for (int i = list.size() - 1; i >= 0; i--) {
                MarketData md = list.get(i);
                if (md == null || md.getTimestamp() == null) continue;
                if (md.getTimestamp().isAfter(atOrBefore)) continue;
                if (md.getClose() != null) return md.getClose();
            }
        }
        return null;
    }

    /**
     * Per-share P&L. For a SELL entry, profit is collected when exit price drops
     * below entry; for a BUY entry, profit is when exit price rises above entry.
     * Multiply by lot size × lot quantity downstream for absolute P&L.
     */
    private BigDecimal perShareProfit(String entryDirection, BigDecimal entryPrice, BigDecimal exitPrice) {
        if (entryPrice == null || exitPrice == null) return BigDecimal.ZERO;
        if ("SELL".equalsIgnoreCase(entryDirection)) {
            return entryPrice.subtract(exitPrice);
        }
        return exitPrice.subtract(entryPrice);
    }

    /**
     * Compact human-readable reason snapshotted on entry — e.g.
     * {@code "5min/SMA50"}. Used by the Telegram alert and the {@code trade_order}
     * ledger row so the trigger doesn't need to be re-derived later.
     */
    private String buildEntryReason(TradeSignal signal) {
        if (signal == null) return null;
        String interval = signal.getInterval();
        if (interval != null) interval = interval.replace("minute", "min");
        Integer sma = signal.getPrimarySma();
        if (interval == null && sma == null) return null;
        if (interval == null) return "SMA" + sma;
        if (sma == null) return interval;
        return interval + "/SMA" + sma;
    }

    private boolean sameDirection(String entryDirection, TradeAction signalAction) {
        return entryDirection != null && signalAction != null
                && entryDirection.equalsIgnoreCase(signalAction.name());
    }

    private TradeConfigCombinedDTO findConfig(Integer tradeConfigId) {
        if (tradeConfigId == null) return null;
        List<TradeConfigCombinedDTO> all = SharedData.combinedDto;
        if (all == null) return null;
        for (TradeConfigCombinedDTO dto : all) {
            if (dto != null && dto.getTradeConfig() != null
                    && tradeConfigId.equals(dto.getTradeConfig().getId())) {
                return dto;
            }
        }
        return null;
    }

    private String instrumentName(TradeConfigCombinedDTO config) {
        Instrument instrument = config != null ? config.getInstrument() : null;
        return instrument != null ? instrument.getInsName() : null;
    }

    private static Integer parseInt(String s) {
        try {
            return s == null ? null : Integer.valueOf(s);
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    /**
     * Pipe-separated key shape produced by AnalysisScheduler.toStrikeMarketDataKey:
     * {@code <instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|<itmDepth>|<otmDepth>}.
     */
    private static final class ParsedKey {
        final String instrumentToken;
        final String interval;
        final String optionType;
        final String strike;
        final String optionToken;
        final String itmDepth;
        final String otmDepth;

        private ParsedKey(String[] p) {
            this.instrumentToken = p[0];
            this.interval = p[1];
            this.optionType = p[2];
            this.strike = p[3];
            this.optionToken = p[4];
            this.itmDepth = p[5];
            this.otmDepth = p[6];
        }

        static ParsedKey from(String key) {
            if (key == null) return null;
            String[] parts = key.split("\\|");
            if (parts.length < 7) return null;
            return new ParsedKey(parts);
        }
    }
}
