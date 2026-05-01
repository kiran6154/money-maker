package com.moneymaker.scheduler;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.util.ConverterUtility;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.DayOfWeek;
import java.util.ArrayList;
import java.util.List;

import static com.moneymaker.util.ConverterUtility.toBigDecimal;
import static com.moneymaker.util.ConverterUtility.toInteger;

@Slf4j
@Component
public class TradeConfigScheduler {
    @Autowired
    private TradeConfigRepository tradeConfigRepository;
    @Autowired
    private SmaTimeframeRepository smaTimeframeRepository;

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
            List<TradeConfigCombinedDTO> combinedDto=   fetchTradeConfigsByDate(LocalDate.now());
            SharedData.combinedDto = combinedDto;

        }
    }

    public List<TradeConfigCombinedDTO> fetchTradeConfigsByDate(LocalDate date) {

        List<Object[]> results = tradeConfigRepository.fetchCombinedByTradingDate(date);
        log.info("Fetched combined trade configs for date {}: {}", date, results.size());
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
        i++;
        tc.setItmDepth(toInteger(row[i++]));
        tc.setOtmDepth(toInteger(row[i++]));
        tc.setAtmDepth(toInteger(row[i++]));
        // Instrument will be set separately by mapToInstrument
        return tc;
    }

    private Instrument mapToInstrument(Object[] row, TradeConfig tc) {
        // Instrument starts after TradeConfig fields (0-11)
        int i = 16;  // Starting index for Instrument fields
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
        // InstrumentDetails starts after TradeConfig (12) and Instrument (5) fields
        int i = 21;  // Starting index for InstrumentDetails fields
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
