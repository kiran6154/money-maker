package com.moneymaker.market.instrument;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.market.historical.HistoricalSymbol;
import com.moneymaker.repository.HistoricalOptionCandleRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Resolver for the imported-CSV backtest source. Produces {@link HistoricalSymbol}
 * natural-key strings and never touches {@code instrument_details} or
 * {@code expiry_dates} — neither table has rows for this data, and the design
 * in {@code docs/HISTORICAL_CHART_DATA_PLAN.md} deliberately keeps it that way.
 *
 * <h3>Expiry rule</h3>
 * Nearest {@code expiry_date >= analysisDate} present in
 * {@code historical_option_candles}, i.e. driven by the data itself. This is the
 * same rule {@code HistoricalIciciChartDashboardService} uses, and it is
 * deliberately <b>not</b> {@code ChartExpiryResolver}: that class hard-filters
 * NIFTY to Tuesday / BANKNIFTY to Wednesday, which matches the current NSE
 * convention but silently returns nothing for older data — the sample files are
 * 2024 Thursday weeklies (2024-01-04, 2024-01-11).
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "backtest.data-source", havingValue = "HISTORICAL_ICICI")
public class HistoricalOptionInstrumentResolver implements OptionInstrumentResolver {

    public static final String NAME = "HISTORICAL_ICICI";

    /** Exchange code the importer writes for index spot rows. */
    private static final String SPOT_EXCHANGE = "NSE";

    /** Exchange code the importer writes for option rows. */
    private static final String OPTION_EXCHANGE = "NFO";

    private final HistoricalOptionCandleRepository optionCandleRepository;

    /**
     * Memo for {@link #resolveExpiry}, keyed on {@code stockCode|exchange|analysisDate}.
     *
     * <p>{@code AnalysisScheduler.fetchAndShareStrikeMarketData} calls
     * {@code resolveExpiry} once per <em>(config × timeframe)</em> on every tick —
     * roughly 400 times per backtest day for the same handful of dates. The
     * underlying query has to range over {@code expiry_date} across the whole
     * table, and the imported set is ~3.8M rows, so those repeats dominated the
     * per-day cost. The answer cannot change during a run: nothing writes to
     * {@code historical_option_candles} while a backtest is replaying it.
     *
     * <p>Bounded by the number of distinct trading dates in the run — a few
     * hundred entries at most, each a date and a date.
     *
     * <p>This memo is backtest-only by construction, not by an {@code if}: the
     * whole bean is conditional on {@code backtest.data-source=HISTORICAL_ICICI},
     * and {@code HistoricalDataSourceGuard} fails startup if that is set while
     * {@code app.mode=live}. No shared service grows a mode branch.
     */
    private final Map<String, Optional<LocalDate>> expiryByDate = new ConcurrentHashMap<>();

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public String underlyingSymbol(TradeConfigCombinedDTO dto) {
        return dto == null ? null : underlyingSymbol(dto.getInstrument());
    }

    @Override
    public String underlyingSymbol(Instrument instrument) {
        if (instrument == null) {
            return null;
        }
        // instrument_details is intentionally not consulted — the historical
        // tables are keyed on stock_code, which comes off the instrument row.
        String stockCode = UnderlyingSymbols.canonicalName(instrument);
        if (stockCode.isEmpty()) {
            log.warn("[historical] instrument has no usable name — cannot build an underlying symbol");
            return null;
        }
        return HistoricalSymbol.encodeSpot(stockCode, SPOT_EXCHANGE);
    }

    @Override
    public LocalDate resolveExpiry(Instrument instrument, LocalDate analysisDate) {
        if (instrument == null || analysisDate == null) {
            return null;
        }
        String stockCode = UnderlyingSymbols.canonicalName(instrument);
        if (stockCode.isEmpty()) {
            return null;
        }

        return expiryByDate
                .computeIfAbsent(stockCode + "|" + OPTION_EXCHANGE + "|" + analysisDate,
                        key -> lookupExpiry(stockCode, analysisDate))
                .orElse(null);
    }

    /** Uncached lookup — runs once per {@code (stockCode, analysisDate)} per JVM. */
    private Optional<LocalDate> lookupExpiry(String stockCode, LocalDate analysisDate) {
        Optional<LocalDate> expiry = optionCandleRepository.findNearestExpiryOnOrAfter(
                stockCode, OPTION_EXCHANGE, analysisDate);
        if (expiry.isEmpty()) {
            log.warn("[historical] no expiry on/after {} in historical_option_candles for stockCode={} — "
                    + "import the CSV covering that expiry", analysisDate, stockCode);
        }
        return expiry;
    }

    @Override
    public String optionSymbol(Instrument instrument, LocalDate expiry, Integer strike, String optionType) {
        if (instrument == null || expiry == null || strike == null || optionType == null) {
            return null;
        }
        String stockCode = UnderlyingSymbols.canonicalName(instrument);
        if (stockCode.isEmpty()) {
            return null;
        }
        return HistoricalSymbol.encodeOption(
                stockCode, OPTION_EXCHANGE, expiry, BigDecimal.valueOf(strike), optionType);
    }
}
