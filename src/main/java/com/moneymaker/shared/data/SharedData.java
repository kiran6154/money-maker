package com.moneymaker.shared.data;

import com.moneymaker.dto.AllTimeFramedto;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.MarketData;
import com.zerodhatech.kiteconnect.KiteConnect;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
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

   /**
    * The tick ({@code asOf}) that last wrote each key of
    * {@link #strikeMarketDataByInstrumentAndInterval}. Strategies refuse to
    * evaluate a key whose stamp is not the tick being evaluated — a strike that
    * left the config's ATM window stops being refreshed, and before this stamp
    * existed its frozen series kept emitting the same signal for the rest of
    * the session (S8: two entries at a 48-point-stale price). Written alongside
    * every cache put, cleared wherever the cache itself is cleared.
    */
   public static Map<String, LocalDateTime> strikeMarketDataTick = new ConcurrentHashMap<>();
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

    /**
     * The newest cached candle for {@code optionToken} at or before
     * {@code atOrBefore}, taken from the <b>finest interval</b> cached for that
     * contract. Returns null when nothing is cached for the token.
     *
     * <p><b>Why the interval has to be chosen rather than ignored.</b>
     * {@link #strikeMarketDataByInstrumentAndInterval} holds one series per
     * {@code (strike, interval)} and {@code AnalysisScheduler} writes several
     * intervals for the same leg. Callers used to match on the option-token
     * segment of the key alone and take the first hit, which is
     * {@code ConcurrentHashMap} iteration order — so a target or stop-loss could
     * be evaluated against a 10- or 15-minute bar, and a 10-minute series was
     * being written even though no config asked for one. A bar stamped {@code T}
     * only closes at {@code T + width}, so quoting off a coarse bar reads up to
     * fifteen minutes of price that had not happened at the exit timestamp
     * recorded on the row.
     *
     * <p>The finest interval is the right choice rather than the trade's own
     * timeframe: live hands the position monitor a real LTP, so the closest
     * backtest analogue is the shortest bar available. Keeping the monitor on
     * the strategy's coarse timeframe would make backtest exits lag live ones.
     *
     * <p>Two configs can cache the same {@code (token, interval)} under keys that
     * differ only in their depth segments. Those series are fetched with the same
     * arguments and are value-identical, so ties need no further tie-break.
     */
    public static MarketData latestCachedCandle(String optionToken, LocalDateTime atOrBefore) {
        if (optionToken == null) return null;
        Map<String, List<MarketData>> cache = strikeMarketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) return null;

        List<MarketData> finest = null;
        int finestWidth = Integer.MAX_VALUE;
        for (Map.Entry<String, List<MarketData>> e : cache.entrySet()) {
            String[] parts = e.getKey().split("\\|");
            if (parts.length < 5) continue;
            if (!optionToken.equals(parts[4])) continue;
            List<MarketData> list = e.getValue();
            if (list == null || list.isEmpty()) continue;
            int width = intervalMinutes(parts[1]);
            if (width < finestWidth) {
                finestWidth = width;
                finest = list;
            }
        }
        if (finest == null) return null;

        for (int i = finest.size() - 1; i >= 0; i--) {
            MarketData md = finest.get(i);
            if (md == null || md.getTimestamp() == null || md.getClose() == null) continue;
            if (atOrBefore != null && md.getTimestamp().isAfter(atOrBefore)) continue;
            return md;
        }
        return null;
    }

    /**
     * Bar width in minutes for an interval string such as {@code "5minute"}.
     * Anything unparseable sorts last, so a malformed key never wins the
     * finest-interval comparison in {@link #latestCachedCandle}.
     */
    private static int intervalMinutes(String interval) {
        if (interval == null) return Integer.MAX_VALUE;
        String normalized = interval.trim().toLowerCase(Locale.ROOT);
        if (!normalized.endsWith("minute")) return Integer.MAX_VALUE;
        try {
            return Integer.parseInt(normalized.substring(0, normalized.length() - "minute".length()));
        } catch (NumberFormatException ex) {
            return Integer.MAX_VALUE;
        }
    }
}
