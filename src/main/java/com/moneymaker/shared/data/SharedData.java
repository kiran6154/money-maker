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

        // Two hash lookups, no scan and no key parsing. This used to iterate the
        // WHOLE strike cache and run key.split("\\|") on every entry just to read
        // one segment — see the note on strikeSeriesByToken for why that turned
        // out to be 87% of a Pressure replay.
        Map<Integer, List<MarketData>> byInterval = strikeSeriesByToken.get(optionToken);
        if (byInterval == null || byInterval.isEmpty()) return null;

        List<MarketData> finest = null;
        int finestWidth = Integer.MAX_VALUE;
        for (Map.Entry<Integer, List<MarketData>> e : byInterval.entrySet()) {
            List<MarketData> list = e.getValue();
            if (list == null || list.isEmpty()) continue;
            int width = e.getKey();
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
     * Contract-id index over {@link #strikeMarketDataByInstrumentAndInterval}:
     * {@code optionToken -> intervalMinutes -> series}.
     *
     * <h3>Why this exists</h3>
     * {@link #latestCachedCandle} is called once per OPEN position per tick (and
     * again by the force-close sweep) and its only question is "newest bar for
     * this contract". It used to answer that by walking every entry of the strike
     * cache and calling {@code key.split("\\|")} — a regex split allocating seven
     * strings — purely to read segment 4.
     *
     * <p>The cost scales with the number of <b>configs in the run</b>, not with
     * the number of positions being monitored, because every config writes into
     * the same cache. With one or two configs that is a handful of entries and
     * nobody notices; the Pressure books are the first to run twelve at once, and
     * there it measured as <b>87% of the whole replay</b> (a day's
     * {@code positions} phase at 105 s out of 114 s, while SQL accounted for only
     * ~1.4 s per 60 s of wall time). See GAPS #27.</p>
     *
     * <h3>Maintained only through {@link #putStrikeSeries} / {@link #clearStrikeCaches}</h3>
     * A side index is only as sound as the guarantee that nothing writes the main
     * map behind its back — the same one-owner rule {@code TrailLadder} and
     * {@code StrategyIds} follow. <b>Do not put into
     * {@code strikeMarketDataByInstrumentAndInterval} directly.</b> A key written
     * without its index entry is invisible to the position monitor, which means
     * the trade silently stops being quoted and its stop-loss can never fire —
     * exactly the S8 failure this cache already had once.
     *
     * <h3>Collisions are benign</h3>
     * Two configs can cache the same {@code (token, interval)} under keys that
     * differ only in their depth segments. Those series are fetched with identical
     * arguments and are value-identical, so the later write simply replaces the
     * earlier one — which is the same answer the old scan gave, since it treated
     * such ties as interchangeable.
     */
    public static Map<String, Map<Integer, List<MarketData>>> strikeSeriesByToken = new ConcurrentHashMap<>();

    /**
     * The one supported way to publish a strike series.
     *
     * <p>Writes the main cache, the {@link #strikeMarketDataTick} freshness stamp
     * and the {@link #strikeSeriesByToken} index together, parsing the key once
     * here rather than on every read.
     *
     * @param key        {@code instrumentToken|interval|optionType|strike|optionToken|itmDepth|otmDepth}
     * @param series     the candles; null or empty is ignored
     * @param observedAt the tick that produced it, for the S8 freshness stamp
     */
    public static void putStrikeSeries(String key, List<MarketData> series, LocalDateTime observedAt) {
        if (key == null || series == null || series.isEmpty()) return;
        strikeMarketDataByInstrumentAndInterval.put(key, series);
        if (observedAt != null) {
            strikeMarketDataTick.put(key, observedAt);
        }
        String[] parts = key.split("\\|");
        if (parts.length < 5) return;
        strikeSeriesByToken
                .computeIfAbsent(parts[4], k -> new ConcurrentHashMap<>())
                .put(intervalMinutes(parts[1]), series);
    }

    /**
     * Clears the strike cache and everything derived from it, together.
     *
     * <p>Called from the replay's per-day teardown. Clearing the main map without
     * the index would leave the position monitor quoting yesterday's candles for
     * a contract that is no longer cached — stale prices that look entirely
     * normal in the ledger.
     */
    public static void clearStrikeCaches() {
        strikeMarketDataByInstrumentAndInterval.clear();
        strikeMarketDataTick.clear();
        strikeSeriesByToken.clear();
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
