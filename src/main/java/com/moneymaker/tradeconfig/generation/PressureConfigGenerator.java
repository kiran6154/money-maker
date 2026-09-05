package com.moneymaker.tradeconfig.generation;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.market.service.TradingCalendar;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.strategy.Strategy5;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Creates the {@code trade_config} rows the Pressure books run on, one set per
 * trading date in a window.
 *
 * <h3>Why a generator at all</h3>
 * {@code fetchCombinedByTradingDate} selects configs by exact date, so a config
 * is a per-day object. A full-2024 Pressure run is 7 books x 2 legs x 249
 * trading days = <b>3,486 rows</b>, each with an {@code sma_timeframe} child.
 * That is not a thing to create by hand, and creating it by hand is how the
 * clock columns end up subtly different between March and October.
 *
 * <h3>Why not the EOD detector</h3>
 * {@code EodDowntrendDetectionService} is a different lineage entirely: it
 * decides <i>whether</i> to trade tomorrow from an end-of-day trend scan, and
 * knows nothing about entry windows, exact strike offsets or book ids. Strategy
 * 5 is switched off in {@code strategy_defaults} (changeset 044) precisely so it
 * can never appear in that output. Pressure's configs are not a discovery, they
 * are the fixed grid of a measurement run.
 *
 * <h3>Idempotent by (date, book, side)</h3>
 * A re-run over a window that already has rows creates nothing and reports what
 * it skipped. This matters because the natural workflow is "generate 2024,
 * notice one book is wrong, fix it, regenerate" — and a generator that
 * duplicated on re-run would silently double every book's trade count, which
 * looks exactly like a strategy that suddenly got better.
 *
 * <h3>Rule 10 note</h3>
 * This persists through the repositories rather than {@code TradeConfigAdminService},
 * following the precedent {@code EodDowntrendDetectionService} set for the
 * {@code tradeconfig.generation} package. The part of the admin service's
 * contract that actually matters here — invalidating the date-keyed config cache
 * so a replay in the same JVM sees new rows — is done explicitly at the end.
 */
@Slf4j
@Service
public class PressureConfigGenerator {

    /** Marks these rows as this generator's output, for scoping a re-run or a cleanup. */
    public static final String SOURCE = "PRESSURE";

    // ---- The spec's fixed numbers. Each is written onto every config row, so
    // ---- the running system reads them from config (CLAUDE.md #9) and they are
    // ---- editable per book afterwards without touching code.
    /** Target, in premium points (index points for the SPOT book). */
    private static final BigDecimal TARGET_POINTS = new BigDecimal("50");
    /** Stop, in premium points. */
    private static final BigDecimal STOP_POINTS = new BigDecimal("50");
    /**
     * "Arm when favorable excursion &gt;= +25, then exit when it falls back to
     * +25" — a pure give-back trail, expressed as a single rung locking at its
     * own trigger. See {@code TrailLadder} for why that is legal and why it is
     * not the same thing as a +25 target.
     */
    private static final String TRAIL_LADDER = "25:25";
    /** First new entry, inclusive. */
    private static final LocalTime ENTRY_FROM = LocalTime.of(9, 25);
    /** Last new entry, inclusive. */
    private static final LocalTime ENTRY_TO = LocalTime.of(14, 15);
    /** Hard flatten. */
    private static final LocalTime FLATTEN_AT = LocalTime.of(15, 15);
    /** Max hold: 90 minutes = 18 five-minute bars. */
    private static final int MAX_HOLD_MINUTES = 90;
    /** The real strike grid of the imported chain. NOT instrument.strike_points. */
    private static final int STRIKE_STEP = 50;
    /** "Skip trade if premium &lt; 8" — the spec's minimum entry premium. */
    private static final BigDecimal MIN_OPTION_PRICE = new BigDecimal("8");
    /** Lot. */
    private static final int LOT_QUANTITY = 75;
    /** Spot 5-minute is the only series the strategy reads. */
    private static final int TIME_PERIOD_MINUTES = 5;
    /**
     * Written onto the {@code sma_timeframe} child purely to satisfy the
     * pipeline's shape. Strategy 5 never reads an SMA — it reads
     * {@code timePeriod} only, to know which interval to pull — but
     * {@code AnalysisScheduler} skips any timeframe with no registered SMA
     * period, and {@code replaceTimeframes} drops a row whose sma is null.
     */
    private static final int NOMINAL_SMA = 20;

    private final TradeConfigRepository tradeConfigRepository;
    private final SmaTimeframeRepository smaTimeframeRepository;
    private final InstrumentRepository instrumentRepository;
    private final TradingCalendar tradingCalendar;
    private final TradeConfigScheduler tradeConfigScheduler;

    public PressureConfigGenerator(TradeConfigRepository tradeConfigRepository,
                                   SmaTimeframeRepository smaTimeframeRepository,
                                   InstrumentRepository instrumentRepository,
                                   TradingCalendar tradingCalendar,
                                   TradeConfigScheduler tradeConfigScheduler) {
        this.tradeConfigRepository = tradeConfigRepository;
        this.smaTimeframeRepository = smaTimeframeRepository;
        this.instrumentRepository = instrumentRepository;
        this.tradingCalendar = tradingCalendar;
        this.tradeConfigScheduler = tradeConfigScheduler;
    }

    /** What one generation run did. */
    public record Result(int created, int skippedExisting, int tradingDays, List<String> books) {
    }

    /**
     * Generates configs for every trading day in {@code [from, to]}.
     *
     * @param bookIds books to generate, or null/empty for all seven
     * @param instrumentName underlying, e.g. {@code "NIFTY"}
     */
    @Transactional
    public Result generate(LocalDate from, LocalDate to, Set<String> bookIds, String instrumentName) {
        Instrument instrument = instrumentRepository.findAll().stream()
                .filter(i -> i.getInsName() != null && i.getInsName().equalsIgnoreCase(instrumentName))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("No instrument named " + instrumentName));

        List<PressureBook> books = resolveBooks(bookIds);

        // One query for the whole window rather than one per (date, book, side).
        // A 249-day run would otherwise issue ~3,500 existence checks.
        Set<String> existing = new HashSet<>();
        for (TradeConfig tc : tradeConfigRepository.findBySourceAndTradingDateIn(
                SOURCE, tradingDaysBetween(from, to))) {
            existing.add(identity(tc.getTradingDate(), tc.getBookId(), tc.getTradingSide(),
                    tc.getTransactionType()));
        }

        int created = 0;
        int skipped = 0;
        List<LocalDate> days = tradingDaysBetween(from, to);

        for (LocalDate day : days) {
            for (PressureBook book : books) {
                for (PressureBook.Leg leg : book.legs()) {
                    String id = identity(day, book.bookId(), leg.tradingSide(), leg.transactionType());
                    if (!existing.add(id)) {
                        skipped++;
                        continue;
                    }
                    persist(instrument, day, book, leg);
                    created++;
                }
            }
        }

        // The one piece of the TradeConfigAdminService contract that matters to a
        // generator: without this, a replay in the same JVM keeps serving the
        // date-keyed cache it populated before these rows existed.
        tradeConfigScheduler.invalidateConfigsCache();

        log.info("[pressure-config] {} .. {} — created {} config(s), skipped {} already present, "
                        + "over {} trading day(s), books={}",
                from, to, created, skipped, days.size(), books.stream().map(PressureBook::bookId).toList());

        return new Result(created, skipped, days.size(),
                books.stream().map(PressureBook::bookId).toList());
    }

    private void persist(Instrument instrument, LocalDate day, PressureBook book, PressureBook.Leg leg) {
        TradeConfig tc = new TradeConfig();
        tc.setInstrument(instrument);
        tc.setTradingDate(day);
        tc.setTradingSide(leg.tradingSide());
        tc.setTransactionType(leg.transactionType());
        tc.setStratergyId(Strategy5.ID);
        tc.setStrategyIds(String.valueOf(Strategy5.ID));
        tc.setSource(SOURCE);
        tc.setIsActive(Boolean.TRUE);

        // ---- bracket: absolute points, resolved by strategy_defaults POINTS mode
        tc.setTarget(TARGET_POINTS);
        tc.setStopLoss(STOP_POINTS);
        tc.setTrailLadder(TRAIL_LADDER);
        // Explicitly null so nothing resolves a percentage bracket by accident.
        // A stray target_pct would win under PERCENT mode and would be ignored
        // under POINTS - but leaving it set would make the row lie about what it
        // does, which is how 041's whole problem started.
        tc.setTargetPct(null);
        tc.setSlPct(null);
        tc.setMaxSlPoints(null);

        // ---- clock (changeset 042)
        tc.setEntryFrom(ENTRY_FROM);
        tc.setEntryTo(ENTRY_TO);
        tc.setMaxHoldMinutes(MAX_HOLD_MINUTES);
        tc.setFlattenAt(FLATTEN_AT);

        // ---- instrument selection
        tc.setBookId(book.bookId());
        tc.setUnderlyingLeg(book.underlyingLeg());
        tc.setStrikeOffsetPoints(book.strikeOffsetPoints());
        tc.setStrikeStepPoints(book.underlyingLeg() ? null : STRIKE_STEP);
        // The depth columns are the OTHER strike model and must stay null, or
        // calculateStrikesForCandles would expand a set alongside the exact
        // strike and the strategy would have more than one leg to choose from.
        tc.setItmDepth(null);
        tc.setOtmDepth(null);
        tc.setAtmDepth(null);

        // ---- caps
        tc.setLotQuantity(LOT_QUANTITY);
        // Null = no cap. The spec re-arms on exit with no daily trade limit, so
        // "no cap" IS the configured value here rather than an omission.
        tc.setNumberOfTradesPerDay(null);
        tc.setNumberOfParallelTrades(1);
        tc.setMaxParallelPerSide(1);
        // Null = no daily realised-loss cap. The spec names none, and adding one
        // would be an extra filter (explicitly forbidden).
        tc.setMaxLoss(null);

        // ---- entry premium floor: "Skip trade if premium < 8"
        // Not applicable to the spot book, whose "premium" is a five-figure
        // index level - an 8-point floor there would be meaningless noise in
        // the config rather than a rule.
        tc.setMinOptionPrice(book.underlyingLeg() ? null : MIN_OPTION_PRICE);
        tc.setMaxOptionPrice(null);

        TradeConfig saved = tradeConfigRepository.save(tc);

        SmaTimeframe tf = new SmaTimeframe();
        tf.setTradeConfig(saved);
        tf.setTimePeriod(TIME_PERIOD_MINUTES);
        tf.setSma(NOMINAL_SMA);
        smaTimeframeRepository.save(tf);
    }

    private List<PressureBook> resolveBooks(Set<String> bookIds) {
        if (bookIds == null || bookIds.isEmpty()) return PressureBook.all();
        List<PressureBook> out = new ArrayList<>();
        for (String id : bookIds) {
            PressureBook b = PressureBook.byId(id);
            if (b == null) {
                throw new IllegalArgumentException("Unknown book: " + id
                        + " (known: " + PressureBook.all().stream().map(PressureBook::bookId).toList() + ")");
            }
            out.add(b);
        }
        return out;
    }

    /**
     * Trading days in the window, from the same calendar the replay walks — so
     * a config is never generated for a day the backtest will not visit, and
     * never missing for one it will.
     */
    private List<LocalDate> tradingDaysBetween(LocalDate from, LocalDate to) {
        List<LocalDate> days = new ArrayList<>();
        for (LocalDate d = from; !d.isAfter(to); d = d.plusDays(1)) {
            if (tradingCalendar.isTradingDay(d)) days.add(d);
        }
        return days;
    }

    /** Uniqueness key for the idempotency check. */
    private static String identity(LocalDate day, String bookId, String side, String txn) {
        return day + "|" + bookId + "|" + side + "|" + txn;
    }
}
