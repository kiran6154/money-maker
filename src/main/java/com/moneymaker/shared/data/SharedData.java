package com.moneymaker.shared.data;

import com.moneymaker.dto.AllTimeFramedto;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.MarketData;
import com.zerodhatech.kiteconnect.KiteConnect;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Queue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;

public class SharedData {
   static {
      allTimeFrameMap = new HashMap<>();
      AllTimeFramedto.initializeDefaults();
   }

   public static List<TradeConfigCombinedDTO> combinedDto;
   public static Map<String, List<MarketData>> marketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
   public static List<List<Integer>> strikeList;
   public static Map<String, List<List<Integer>>> strikesByInstrumentAndInterval = new ConcurrentHashMap<>();
   public static List<MarketData> strikeMarketDataList;
   public static Map<String, List<MarketData>> strikeMarketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
     public static KiteConnect sharedKiteconnect;
    public static Map<Integer, List<Integer>> allTimeFrameMap;
    public static Map<Integer, String> optionTokenMap = new ConcurrentHashMap<>();

    /**
     * Trade signals emitted by strategies and pending order-service processing.
     * The order service drains this queue each tick.
     */
    public static Queue<TradeSignal> tradeSignals = new ConcurrentLinkedQueue<>();
}
