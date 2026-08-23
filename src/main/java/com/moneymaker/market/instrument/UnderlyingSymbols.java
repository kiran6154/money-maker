package com.moneymaker.market.instrument;

import com.moneymaker.entity.Instrument;

import java.util.Locale;

/**
 * Maps an {@link Instrument} row onto the canonical index name used by option
 * symbols and by {@code historical_*_candles.stock_code}.
 *
 * <p>Needed because {@code instrument.ins_name} is not canonical — the seed
 * script stores {@code NIFTY50} while both the Kite trading symbols
 * ({@code NIFTY24JAN21700CE}) and the imported ICICI CSVs ({@code stock_code=NIFTY})
 * use plain {@code NIFTY}. Order matters: {@code BANKNIFTY} must be tested
 * before {@code NIFTY}, since it contains it.
 *
 * <p>Extracted from {@code AnalysisScheduler.toOptionSymbolPrefix} so the
 * instrument resolvers can share one definition.
 */
public final class UnderlyingSymbols {

    private UnderlyingSymbols() {
    }

    /** Canonical index name, or {@code ""} when the instrument has no usable name. */
    public static String canonicalName(Instrument instrument) {
        if (instrument == null || instrument.getInsName() == null || instrument.getInsName().isBlank()) {
            return "";
        }
        String name = instrument.getInsName().toUpperCase(Locale.ROOT);
        if (name.contains("BANKNIFTY")) {
            return "BANKNIFTY";
        }
        if (name.contains("FINNIFTY")) {
            return "FINNIFTY";
        }
        if (name.contains("NIFTY")) {
            return "NIFTY";
        }
        return name.replaceAll("[^A-Z]", "");
    }
}
