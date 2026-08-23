package com.moneymaker.market.instrument;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;

import java.time.LocalDate;

/**
 * Turns "which instrument, which expiry, which option leg" into the {@code symbol}
 * strings {@code MarketDataService.fetchHistoricalData} expects.
 *
 * <p>Exists so {@code AnalysisScheduler} does not have to know whether it is
 * running against broker instrument tokens or against imported historical data.
 * The two implementations resolve from entirely different tables:
 *
 * <ul>
 *   <li>{@link TokenOptionInstrumentResolver} — {@code instrument_details} +
 *       {@code expiry_dates}, producing Zerodha instrument tokens. The default.</li>
 *   <li>{@link HistoricalOptionInstrumentResolver} — {@code historical_option_candles},
 *       producing {@code HistoricalSymbol} natural-key strings. Active only when
 *       {@code backtest.data-source=HISTORICAL_ICICI}.</li>
 * </ul>
 *
 * <p>Every method returns {@code null} when it cannot resolve, and callers are
 * expected to skip that config / strike and log — this mirrors the pre-existing
 * behaviour in {@code AnalysisScheduler}.
 */
public interface OptionInstrumentResolver {

    /** Short name for logs, e.g. {@code TOKEN} or {@code HISTORICAL_ICICI}. */
    String getName();

    /** Symbol for the config's underlying/index series, or {@code null} if unresolvable. */
    String underlyingSymbol(TradeConfigCombinedDTO dto);

    /** Expiry to trade on {@code analysisDate}, or {@code null} if none is available. */
    LocalDate resolveExpiry(Instrument instrument, LocalDate analysisDate);

    /** Symbol for one option leg, or {@code null} if unresolvable. */
    String optionSymbol(Instrument instrument, LocalDate expiry, Integer strike, String optionType);
}
