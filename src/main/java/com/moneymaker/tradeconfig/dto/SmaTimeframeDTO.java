package com.moneymaker.tradeconfig.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class SmaTimeframeDTO {
    private Integer id;
    private Integer timePeriod;
    private Integer sma;
    private Double slope;
}
