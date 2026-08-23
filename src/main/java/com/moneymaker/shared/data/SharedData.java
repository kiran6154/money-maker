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
    /**
     * Resolved option symbol per contract, cached to avoid re-resolving the same
     * leg on every tick.
     *
     * <p>Keyed by {@code expiry|strike|optionType} — <b>not</b> by strike alone.
     * A strike is not a contract: on any day with both a CE and a PE config, the
     * two configs walk the same strikes, so a strike-only key hands the second
     * config the first one's token and it silently analyses the wrong leg (a CE
     * config priced off PE candles). The same collision spans expiries on a
     * multi-day run. Build keys with {@link #optionTokenKey}.
     */
    public static Map<String, String> optionTokenMap = new ConcurrentHashMap<>();

    /** Cache key for {@link #optionTokenMap}: one entry per actual contract. */
    public static String optionTokenKey(java.time.LocalDate expiry, Integer strike, String optionType) {
        return expiry + "|" + strike + "|" + optionType;
    }

    /**
     * Trade signals emitted by strategies and pending order-service processing.
     * The order service drains this queue each tick.
     */
    public static Queue<TradeSignal> tradeSignals = new ConcurrentLinkedQueue<>();
}
