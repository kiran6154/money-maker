package com.moneymaker.scheduler;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import com.moneymaker.util.ConverterUtility;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.DayOfWeek;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

import static com.moneymaker.util.ConverterUtility.toBigDecimal;
import static com.moneymaker.util.ConverterUtility.toInteger;

@Slf4j
@Component
public class TradeConfigScheduler {
    /** Alert-key namespace for {@link DailyEventGuard} — keeps DB rows organised by feature. */
    private static final String ALERT_KEY_TRADE_CONFIGS = "trade-configs";

    @Autowired
    private TradeConfigRepository tradeConfigRepository;
    @Autowired
    private SmaTimeframeRepository smaTimeframeRepository;
    @Autowired
    private NotificationService notifier;
    @Autowired
    private DailyEventGuard dailyEventGuard;

    @Value("${app.mode:live}")
    private String appMode;

    /**
     * Date-keyed cache for {@link #getConfigsForDate(LocalDate)}. Callers
     * (live cron, backtest outer loop, backtest's {@code getUniqueTimePeriods},
     * the controller's manual login) go through {@code getConfigsForDate} so
     * the same DB query doesn't fire repeatedly. Cleared on JVM restart;
     * mid-day DB edits are not picked up — restart to refresh.
     */
    private final Map<LocalDate, List<TradeConfigCombinedDTO>> configsCache = new ConcurrentHashMap<>();

    /**
     * Live-mode startup seed. The 09:16 cron is the only other writer to
     * {@link SharedData#combinedDto}, so a JVM started after 09:16 on a
     * trading day would leave the pipeline schedulers idle until the next
     * day's cron fires. This listener loads today's configs once on boot so
     * the next 5-min Analysis/Order/Position tick has something to work with.
     *
     * <p>Skipped in backtest mode — {@code BacktestAnalysisService} manages
     * {@code combinedDto} per-day inside its own loop and we don't want to
     * fire the trade-configs Telegram on every backtest boot.</p>
     *
     * <p>Idempotent with the 09:16 cron: {@link #getConfigsForDate} is
     * date-keyed cached and {@link #reportConfigsForDay} is gated by
     * {@link DailyEventGuard} (one Telegram per date across JVM restarts).</p>
     */
    @EventListener(ApplicationReadyEvent.class)
    public void seedConfigsOnStartup() {
        if (!"live".equalsIgnoreCase(appMode)) {
            return;
        }
        LocalDate today = LocalDate.now();
        if (today.getDayOfWeek() == DayOfWeek.SATURDAY || today.getDayOfWeek() == DayOfWeek.SUNDAY) {
            return;
        }
        log.info("[TradeConfigScheduler] Startup seed: loading trade configs for {}", today);
        List<TradeConfigCombinedDTO> combinedDto = getConfigsForDate(today);
        SharedData.combinedDto = combinedDto;
        reportConfigsForDay(today, combinedDto);
    }

    @Scheduled(cron = "0 12 9 * * MON-FRI")
    public void dailyTaskAt912AM() {
        LocalDateTime now = LocalDateTime.now();

        if (now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY) {
            log.info("Scheduler has run at 9:12 AM on {}", now);
        }
    }

    @Scheduled(cron = "0 16 9 * * MON-FRI")
    public void checkTradeConfigAt916AM() {
        LocalDateTime now = LocalDateTime.now();

        if (now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY) {
            log.info("Is any trade-config available for today? Checking at 9:16 AM on {}", now);
            LocalDate today = LocalDate.now();
            List<TradeConfigCombinedDTO> combinedDto = getConfigsForDate(today);
            SharedData.combinedDto = combinedDto;
            reportConfigsForDay(today, combinedDto);
        }
    }

    /**
     * Single-entry-point fetch for trade configs on a given date, with
     * in-JVM caching. Every caller in the app (live cron, backtest outer
     * loop, controller, {@code getUniqueTimePeriods}) should go through here
     * rather than calling {@link #fetchTradeConfigsByDate(LocalDate)} directly
     * — that way the same DB query never fires more than once per
     * {@code (JVM, date)} pair <i>when the DB actually has configs</i>.
     *
     * <p><b>Empty results are NOT cached</b>: if a date has zero configs, the
     * next call re-queries. This lets a user add a row mid-session and trigger
     * another backtest run without restarting the JVM. (A populated result is
     * cached normally — once configs exist for the day they don't change
     * mid-session in any realistic workflow.)
     */
    public List<TradeConfigCombinedDTO> getConfigsForDate(LocalDate date) {
        if (date == null) return List.of();
        List<TradeConfigCombinedDTO> cached = configsCache.get(date);
        if (cached != null && !cached.isEmpty()) {
            return cached;
        }
        List<TradeConfigCombinedDTO> fresh = fetchTradeConfigsByDate(date);
        if (fresh != null && !fresh.isEmpty()) {
            configsCache.put(date, fresh);
        }
        return fresh == null ? List.of() : fresh;
    }

    /** Clears the in-JVM cache so the next {@link #getConfigsForDate} hits the DB. */
    public void invalidateConfigsCache() {
        configsCache.clear();
    }

    public List<TradeConfigCombinedDTO> fetchTradeConfigsByDate(LocalDate date) {

        List<Object[]> results = tradeConfigRepository.fetchCombinedByTradingDate(date);
        log.debug("Fetched combined trade configs for date {}: {}", date, results.size());
        List<TradeConfigCombinedDTO> tradeConfigCombinedDTOList = results.stream().map(row -> {
            TradeConfig tradeConfig = mapToTradeConfig(row);
            Instrument instrument = mapToInstrument(row, tradeConfig);
            InstrumentDetails instrumentDetails = mapToInstrumentDetails(row, tradeConfig, instrument);
            List<SmaTimeframe> timeFrameList = tradeConfig.getId() == null
                    ? new ArrayList<>()
                    : smaTimeframeRepository.findByTradeConfigId(tradeConfig.getId());
            return new TradeConfigCombinedDTO(tradeConfig, instrument, instrumentDetails,timeFrameList);
        }).toList();
return tradeConfigCombinedDTOList;
    }

    /**
     * Logs (INFO) and Telegram-alerts the active trade configs for {@code date},
     * <b>once per date — across JVM restarts</b>. The decision is delegated to
     * {@link DailyEventGuard} which persists the "already fired" mark to the
     * {@code alert_state} table. {@link NotificationService#sendIfChanged}
     * still backstops the actual send.
     */
    public void reportConfigsForDay(LocalDate date, List<TradeConfigCombinedDTO> configs) {
        if (date == null) return;
        if (!dailyEventGuard.firstTime(ALERT_KEY_TRADE_CONFIGS, date)) {
            return; // already reported today — guard row in alert_state confirms it
        }
        if (configs == null || configs.isEmpty()) {
            log.info("[trade-configs] {}: no active configs", date);
            notifier.sendIfChanged(ALERT_KEY_TRADE_CONFIGS + ":" + date,
                    String.format("*Trade configs for %s*: none active", date));
            return;
        }

        String summary = buildSummary(date, configs);
        log.info("[trade-configs] {}\n{}", date, summary);
        notifier.sendIfChanged(ALERT_KEY_TRADE_CONFIGS + ":" + date,
                String.format("*Trade configs for %s* (%d active)%n%s", date, configs.size(), summary));
    }

    /**
     * Builds the per-config block printed in the Telegram trade-config alert.
     * Each config is rendered as a vertical list of label/value rows so the
     * message stays readable on a phone (one config per "card", blank line
     * between cards).
     */
    private String buildSummary(LocalDate date, List<TradeConfigCombinedDTO> configs) {
        StringBuilder sb = new StringBuilder();
        String nl = System.lineSeparator();
        int idx = 0;
        for (TradeConfigCombinedDTO dto : configs) {
            idx++;
            TradeConfig tc = dto.getTradeConfig();
            Instrument ins = dto.getInstrument();
            if (tc == null) continue;

            if (idx > 1) sb.append(nl); // blank line between configs

            sb.append("Config #").append(idx).append(nl);
            sb.append("  id          : ").append(tc.getId()).append(nl);
            sb.append("  instrument  : ").append(ins != null ? ins.getInsName() : "-").append(nl);
            sb.append("  side        : ").append(tc.getTradingSide()).append(nl);
            sb.append("  txn         : ").append(tc.getTransactionType()).append(nl);
            sb.append("  target      : ").append(tc.getTarget()).append(nl);
            sb.append("  stop-loss   : ").append(tc.getStopLoss()).append(nl);
            sb.append("  lots        : ").append(tc.getLotQuantity()).append(nl);
            sb.append("  trades/day  : ").append(tc.getNumberOfTradesPerDay()).append(nl);
            sb.append("  parallel    : ").append(tc.getNumberOfParallelTrades()).append(nl);
            sb.append("  strategy    : ").append(tc.getStratergyId()).append(nl);

            List<SmaTimeframe> tfs = dto.getTimeframes();
            if (tfs != null && !tfs.isEmpty()) {
                String tfList = tfs.stream()
                        .filter(t -> t != null && t.getTimePeriod() != null)
                        .map(t -> t.getTimePeriod() + "min/SMA" + t.getSma())
                        .collect(Collectors.joining(", "));
                sb.append("  timeframes  : ").append(tfList).append(nl);
            }
        }
        return sb.toString();
    }

    // Helper to safely convert to BigDecimal
    private TradeConfig mapToTradeConfig(Object[] row) {
        TradeConfig tc = new TradeConfig();
        int i = 0;
        tc.setId(toInteger(row[i++])); // id
        tc.setTradingSide(ConverterUtility.toString(row[i++])); // trading_side
        tc.setTradingDate(row[i] != null ? ((java.sql.Date) row[i]).toLocalDate() : null); i++; // trading_date
        tc.setTarget(toBigDecimal(row[i++])); // target
        tc.setStopLoss(toBigDecimal(row[i++])); // stop_loss
        i++; // Skip p_instrument as it will be set separately
        tc.setMaxLoss(toBigDecimal(row[i++])); // max_loss
        tc.setOptionDepth(toInteger(row[i++])); // option_depth
        tc.setTransactionType(ConverterUtility.toString(row[i++])); // transaction_type
        tc.setLotQuantity(toInteger(row[i++])); // lot_quantity
        tc.setStratergyId(toInteger(row[i++])); // stratergy_id
        tc.setNumberOfTradesPerDay(toInteger(row[i++])); // no_of_trades
        tc.setNumberOfParallelTrades(toInteger(row[i++])); // no_of_parrellel_trades
        tc.setItmDepth(toInteger(row[i++]));
        tc.setOtmDepth(toInteger(row[i++]));
        tc.setAtmDepth(toInteger(row[i++]));
        tc.setSource(ConverterUtility.toString(row[i++])); // source (MANUAL / AUTO_DOWNTREND)


        // Instrument will be set separately by mapToInstrument
        return tc;
    }

    private Instrument mapToInstrument(Object[] row, TradeConfig tc) {
        // Instrument starts after TradeConfig fields (0..16 incl. source)
        int i = 17;  // Starting index for Instrument fields
        Instrument ins = new Instrument();
        ins.setId(toInteger(row[i++])); // id
        ins.setInsName(ConverterUtility.toString(row[i++])); // ins_name
        ins.setInsId(ConverterUtility.toString(row[i++])); // ins_id
        ins.setLotQty(toInteger(row[i++])); // lot_qty
        ins.setStrikePoints(toBigDecimal(row[i++])); // strike_points
        // Add more fields if present in Instrument entity and query
        tc.setInstrument(ins);
        return ins;
    }

    private InstrumentDetails mapToInstrumentDetails(Object[] row, TradeConfig tc, Instrument ins) {
        // InstrumentDetails starts after TradeConfig (17 incl. source) and Instrument (5) fields
        int i = 22;  // Starting index for InstrumentDetails fields
        InstrumentDetails id = new InstrumentDetails();
        id.setInstrumentToken(toInteger(row[i++])); // instrument_token
        id.setExchangeToken(toInteger(row[i++])); // exchange_token
        id.setTradingSymbol(ConverterUtility.toString(row[i++])); // tradingsymbol
        id.setName(ConverterUtility.toString(row[i++])); // name
        id.setLastPrice(toBigDecimal(row[i++])); // last_price
        //  id.setExpiry(row[i] != null ? ((java.sql.Date) row[i]).toLocalDate() : null); i++; // expiry
        i++;
        id.setStrike(toBigDecimal(row[i++])); // strike
        id.setTickSize(toBigDecimal(row[i++])); // tick_size
        id.setLotSize(toBigDecimal(row[i++])); // lot_size
        id.setInstrumentType(ConverterUtility.toString(row[i++])); // instrument_type
        id.setSegment(ConverterUtility.toString(row[i++])); // segment
        id.setExchange(ConverterUtility.toString(row[i++])); // exchange
        return id;
    }

}
