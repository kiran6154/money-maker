package com.moneymaker.dto;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.TradeConfig;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class TradeConfigCombinedDTO {
    private TradeConfig tradeConfig;
    private Instrument instrument;
    private InstrumentDetails instrumentDetails;
}

