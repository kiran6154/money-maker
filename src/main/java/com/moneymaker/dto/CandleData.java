package com.moneymaker.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class CandleData {
    private LocalDateTime time;
    private double open;
    private double high;
    private double low;
    private double close;
    private double sma20;
    private double sma50;
    private double sma100;
    private double sma200;
    private double sma500;
    private boolean sma20DownTrending;
    private boolean sma50DownTrending;
    private boolean sma100DownTrending;
    private boolean sma200DownTrending;
    private boolean sma500DownTrending;
}
