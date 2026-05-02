package com.moneymaker.shared.data;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.zerodhatech.kiteconnect.KiteConnect;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class SharedData {
   public static List<TradeConfigCombinedDTO> combinedDto;
   public static List<MarketData> marketDataList;
   public static Map<String, List<MarketData>> marketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
   public static List<List<Integer>> strikeList;
   public static Map<String, List<List<Integer>>> strikesByInstrumentAndInterval = new ConcurrentHashMap<>();
   public static List<MarketData> strikeMarketDataList;
   public static Map<String, List<MarketData>> strikeMarketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
   public static Map<String, List<Double>> strikeIndicatorValues;
   public static Map<String, Map<String, List<Double>>> strikeIndicatorsByInstrumentAndInterval = new ConcurrentHashMap<>();
   public static KiteConnect sharedKiteconnect;
}
