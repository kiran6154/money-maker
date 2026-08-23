package com.moneymaker.market.instrument;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.ExpiryDates;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.repository.ExpiryDatesRepository;
import com.moneymaker.repository.InstrumentDetailsRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Default resolver: broker instrument tokens from {@code instrument_details},
 * expiries from {@code expiry_dates}. This is the logic that previously lived
 * inline in {@code AnalysisScheduler}, moved verbatim.
 *
 * <p>Note on expiry semantics: this picks the <em>nearest</em> expiry on or after
 * the analysis date, whatever {@code expiry_dates} happens to contain. Nothing
 * here distinguishes weekly from monthly — that is purely a data-seeding
 * decision by the operator. If only month-end rows are seeded, the system trades
 * monthlies silently.
 *
 * <p>Gated on the same property as {@link HistoricalOptionInstrumentResolver}
 * with the opposite value, so exactly one resolver bean exists. A typo in
 * {@code backtest.data-source} leaves neither registered, and startup fails
 * loudly rather than silently picking a source.
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "backtest.data-source", havingValue = "BROKER", matchIfMissing = true)
public class TokenOptionInstrumentResolver implements OptionInstrumentResolver {

    public static final String NAME = "TOKEN";

    private final InstrumentDetailsRepository instrumentDetailsRepository;
    private final ExpiryDatesRepository expiryDatesRepository;

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public String underlyingSymbol(TradeConfigCombinedDTO dto) {
        if (dto == null || dto.getInstrumentDetails() == null
                || dto.getInstrumentDetails().getInstrumentToken() == null) {
            return null;
        }
        return dto.getInstrumentDetails().getInstrumentToken().toString();
    }

    @Override
    public LocalDate resolveExpiry(Instrument instrument, LocalDate analysisDate) {
        if (instrument == null || analysisDate == null) {
            return null;
        }
        return expiryDatesRepository
                .findFirstByInstrumentAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(instrument, analysisDate)
                .map(ExpiryDates::getExpiryDate)
                .orElse(null);
    }

    @Override
    public String optionSymbol(Instrument instrument, LocalDate expiry, Integer strike, String optionType) {
        if (strike == null || optionType == null || instrument == null || expiry == null) {
            return null;
        }

        String expiryString = expiry.toString();
        BigDecimal strikeBigDecimal = new BigDecimal(strike);
        List<InstrumentDetails> matches = instrumentDetailsRepository.findByCriteria(
                instrument.getInsName(),
                expiryString,
                strikeBigDecimal,
                optionType
        );

        if (matches.isEmpty()) {
            log.warn("No InstrumentDetails for {}, expiry={}, strike={}, type={}",
                    instrument.getInsName(), expiryString, strikeBigDecimal, optionType);
            return null;
        }
        if (matches.size() > 1) {
            // Same expiry / strike / type on two listings (e.g. NSE + BSE) — pick
            // the lowest-id row deterministically and warn so the data can be cleaned.
            log.warn("Multiple InstrumentDetails ({}) for {}, expiry={}, strike={}, type={} — picking id={}",
                    matches.size(), instrument.getInsName(), expiryString, strikeBigDecimal,
                    optionType, matches.get(0).getInstrumentToken());
        }

        InstrumentDetails match = matches.get(0);
        return match.getInstrumentToken() == null ? null : match.getInstrumentToken().toString();
    }
}
