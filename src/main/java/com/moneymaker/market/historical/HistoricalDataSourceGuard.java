package com.moneymaker.market.historical;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Fails startup if the imported-CSV backtest source is enabled while the app is
 * in live mode.
 *
 * <p>{@code backtest.data-source=HISTORICAL_ICICI} makes every candle come from
 * {@code historical_*_candles}. In live mode that would mean placing real orders
 * against 2024 replay prices, so the combination is refused outright rather than
 * warned about — a warning in a startup log is too easy to miss.
 */
@Slf4j
@Component
public class HistoricalDataSourceGuard {

    /** Value of {@code backtest.data-source} that activates the historical source. */
    public static final String HISTORICAL_ICICI = "HISTORICAL_ICICI";

    /** Default value — candles come from the active broker. */
    public static final String BROKER = "BROKER";

    @Value("${app.mode:live}")
    private String appMode;

    @Value("${backtest.data-source:BROKER}")
    private String dataSource;

    @PostConstruct
    void validate() {
        boolean historical = HISTORICAL_ICICI.equalsIgnoreCase(dataSource);
        boolean live = "live".equalsIgnoreCase(appMode);

        if (historical && live) {
            throw new IllegalStateException(
                    "backtest.data-source=HISTORICAL_ICICI is not allowed with app.mode=live. "
                            + "Historical candles are imported replay data — trading live against them would place "
                            + "real orders at stale prices. Set app.mode=backtest, or backtest.data-source=BROKER.");
        }

        if (!historical && !BROKER.equalsIgnoreCase(dataSource)) {
            throw new IllegalStateException(
                    "Unknown backtest.data-source '" + dataSource + "'. Expected " + BROKER
                            + " or " + HISTORICAL_ICICI + ".");
        }

        if (historical) {
            log.info("[backtest] data source = {} — candles will be read from historical_spot_candles / "
                    + "historical_option_candles; no broker market-data calls will be made", HISTORICAL_ICICI);
        }
    }
}
