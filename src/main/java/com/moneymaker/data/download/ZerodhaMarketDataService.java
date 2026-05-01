package com.moneymaker.data.download;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.moneymaker.login.config.BrokerProperties;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.math.BigDecimal;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Service
public class ZerodhaMarketDataService {

    private static final DateTimeFormatter ZERODHA_DATE_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private static final ZoneId INDIA_ZONE =
            ZoneId.of("Asia/Kolkata");

    private final BrokerProperties properties;
    private final RestTemplate http;
    private final OptionsDataRepository optionsDataRepository;

    public ZerodhaMarketDataService(
            BrokerProperties properties,
            RestTemplate brokerRestTemplate,
            OptionsDataRepository optionsDataRepository) {
        this.properties = properties;
        this.http = brokerRestTemplate;
        this.optionsDataRepository = optionsDataRepository;
    }

    public Map<Double, NiftyOptionPair> fetchNiftyOptionsData(String accessToken) {
        try {
            List<ZerodhaInstrument> instruments = fetchInstruments(accessToken);

            LocalDate now = LocalDate.now(INDIA_ZONE);
            String currentExpiry = now.format(
                    DateTimeFormatter.ofPattern("yyMMM")
            ).toUpperCase();

            List<ZerodhaInstrument> niftyOptions = instruments.stream()
                    .filter(inst -> inst.getName() != null
                            && inst.getName().contains("NIFTY"))
                    .filter(inst -> "CE".equals(inst.getInstrumentType())
                            || "PE".equals(inst.getInstrumentType()))
                    .filter(inst -> inst.getExpiry() != null
                            && inst.getExpiry().contains(currentExpiry))
                    .collect(Collectors.toList());

            Map<String, ZerodhaQuote> quotes =
                    fetchQuotes(accessToken, niftyOptions);

            return groupOptions(niftyOptions, quotes);

        } catch (Exception e) {
            log.error("Failed to fetch Nifty options data", e);
            throw new RuntimeException("Failed to fetch Nifty options data", e);
        }
    }

    public void fetchAndSaveOptionsData(String symbol, String accessToken) {
        try {
            Map<Double, NiftyOptionPair> data =
                    fetchOptionsDataForSymbol(symbol, accessToken);

            LocalDate today = LocalDate.now(INDIA_ZONE);

            List<OptionsDataEntity> entities = data.values()
                    .stream()
                    .flatMap(pair -> {
                        List<OptionsDataEntity> list = new ArrayList<>();

                        if (pair.getCall() != null) {
                            list.add(createEntity(symbol, pair.getCall(), today));
                        }

                        if (pair.getPut() != null) {
                            list.add(createEntity(symbol, pair.getPut(), today));
                        }

                        return list.stream();
                    })
                    .collect(Collectors.toList());

            optionsDataRepository.saveAll(entities);

            log.info("Saved {} option records for {}", entities.size(), symbol);

            LocalDate cutoff = today.minusDays(45);
            optionsDataRepository.deleteBySymbolAndDataDateBefore(symbol, cutoff);

        } catch (Exception e) {
            log.error("Failed to fetch and save options data for {}", symbol, e);
        }
    }

    public void fetchAndSaveOptionsDataForExpiry(
            String symbol,
            String expiryDate,
            String accessToken) {
        try {
            Map<Double, NiftyOptionPair> data =
                    fetchOptionsDataForSymbolAndExpiry(
                            symbol,
                            expiryDate,
                            accessToken
                    );

            LocalDate today = LocalDate.now(INDIA_ZONE);

            List<OptionsDataEntity> entities = data.values()
                    .stream()
                    .flatMap(pair -> {
                        List<OptionsDataEntity> list = new ArrayList<>();

                        if (pair.getCall() != null) {
                            list.add(createEntity(symbol, pair.getCall(), today));
                        }

                        if (pair.getPut() != null) {
                            list.add(createEntity(symbol, pair.getPut(), today));
                        }

                        return list.stream();
                    })
                    .collect(Collectors.toList());

            optionsDataRepository.saveAll(entities);

            log.info(
                    "Saved {} option records for {} expiry {}",
                    entities.size(),
                    symbol,
                    expiryDate
            );

        } catch (Exception e) {
            log.error("Failed to fetch and save options data for expiry", e);
        }
    }

    private List<ZerodhaInstrument> fetchInstruments(String accessToken) {
        BrokerProperties.Zerodha cfg = properties.getZerodha();

        HttpHeaders headers = new HttpHeaders();
        headers.set(
                "Authorization",
                "token " + cfg.getApiKey() + ":" + accessToken
        );
        headers.set("X-Kite-Version", "3");

        String url = cfg.getApiBaseUrl() + "/instruments";

        ResponseEntity<String> response = http.exchange(
                url,
                HttpMethod.GET,
                new HttpEntity<>(headers),
                String.class
        );

        List<String> lines =
                Arrays.asList(response.getBody().split("\n"));

        return lines.stream()
                .skip(1)
                .map(this::parseInstrumentLine)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private ZerodhaInstrument parseInstrumentLine(String line) {
        String[] parts = line.split(",");

        if (parts.length < 12) {
            return null;
        }

        try {
            return ZerodhaInstrument.builder()
                    .instrumentToken(Long.parseLong(parts[0]))
                    .exchange(parts[1])
                    .tradingsymbol(parts[2])
                    .name(parts[3])
                    .lastPrice(Double.parseDouble(parts[4]))
                    .expiry(parts[5])
                    .strike(Double.parseDouble(parts[6]))
                    .tickSize(Double.parseDouble(parts[7]))
                    .lotSize(Integer.parseInt(parts[8]))
                    .instrumentType(parts[9])
                    .segment(parts[10])
                    .exchangeToken(parts[11])
                    .build();

        } catch (Exception e) {
            return null;
        }
    }

    /**
     * Fetches last trading day's full session
     */
    private Map<String, ZerodhaQuote> fetchQuotes(
            String accessToken,
            List<ZerodhaInstrument> instruments) {

        if (instruments.isEmpty()) {
            return Map.of();
        }

        BrokerProperties.Zerodha cfg = properties.getZerodha();

        HttpHeaders headers = new HttpHeaders();
        headers.set(
                "Authorization",
                "token " + cfg.getApiKey() + ":" + accessToken
        );
        headers.set("X-Kite-Version", "3");

        Map<String, ZerodhaQuote> result = new HashMap<>();

        LocalDate tradingDate = getPreviousTradingDay();

        LocalDateTime from = tradingDate.atTime(9, 15);
        LocalDateTime to = tradingDate.atTime(15, 30);

        for (ZerodhaInstrument inst : instruments) {

            if (inst.getInstrumentToken() <= 0) {
                continue;
            }

            try {
                String url = UriComponentsBuilder
                        .fromHttpUrl(
                                cfg.getApiBaseUrl()
                                        + "/instruments/historical/"
                                        + inst.getInstrumentToken()
                                        + "/5minute"
                        )
                        .queryParam(
                                "from",
                                from.format(ZERODHA_DATE_FORMAT)
                        )
                        .queryParam(
                                "to",
                                to.format(ZERODHA_DATE_FORMAT)
                        )
                        .queryParam("oi", 1)
                        .encode()
                        .toUriString();

                log.info("Calling Zerodha historical API: {}", url);

                ResponseEntity<Map> response =
                        http.exchange(
                                url,
                                HttpMethod.GET,
                                new HttpEntity<>(headers),
                                Map.class
                        );

                Map<String, Object> data =
                        (Map<String, Object>) response.getBody().get("data");

                List<List<Object>> candles =
                        (List<List<Object>>) data.get("candles");

                if (candles != null && !candles.isEmpty()) {
                    List<Object> latest =
                            candles.get(candles.size() - 1);

                    ZerodhaQuote quote =
                            ZerodhaQuote.builder()
                                    .instrumentToken((int) inst.getInstrumentToken())
                                    .lastPrice(Double.parseDouble(latest.get(4).toString()))
                                    .ohlc(
                                            Map.of(
                                                    "open", Double.parseDouble(latest.get(1).toString()),
                                                    "high", Double.parseDouble(latest.get(2).toString()),
                                                    "low", Double.parseDouble(latest.get(3).toString()),
                                                    "close", Double.parseDouble(latest.get(4).toString())
                                            )
                                    )
                                    .volume(Integer.parseInt(latest.get(5).toString()))
                                    .oi(
                                            latest.size() > 6
                                                    ? Integer.parseInt(latest.get(6).toString())
                                                    : 0
                                    )
                                    .build();

                    result.put(
                            inst.getExchange()
                                    + ":"
                                    + inst.getTradingsymbol(),
                            quote
                    );
                }

            } catch (Exception e) {
                log.error(
                        "Failed fetching 5min candle for {}",
                        inst.getTradingsymbol(),
                        e
                );
            }
        }

        return result;
    }

    private LocalDate getPreviousTradingDay() {
        LocalDate date = LocalDate.now(INDIA_ZONE).minusDays(1);

        while (date.getDayOfWeek() == DayOfWeek.SATURDAY
                || date.getDayOfWeek() == DayOfWeek.SUNDAY) {
            date = date.minusDays(1);
        }

        return date;
    }

    private NiftyOptionData createOptionData(
            ZerodhaInstrument instrument,
            ZerodhaQuote quote) {

        return NiftyOptionData.builder()
                .tradingsymbol(instrument.getTradingsymbol())
                .strike(instrument.getStrike())
                .expiry(instrument.getExpiry())
                .instrumentType(instrument.getInstrumentType())
                .lastPrice(
                        quote != null
                                ? quote.getLastPrice()
                                : instrument.getLastPrice())
                .oi(
                        quote != null
                                ? quote.getOi()
                                : 0)
                .volume(
                        quote != null
                                ? quote.getVolume()
                                : 0)
                .build();
    }

    private Map<Double, NiftyOptionPair> fetchOptionsDataForSymbol(
            String symbol,
            String accessToken) {

        List<ZerodhaInstrument> instruments =
                fetchInstruments(accessToken);

        List<ZerodhaInstrument> options =
                instruments.stream()
                        .filter(inst ->
                                inst.getTradingsymbol() != null
                                        && inst.getTradingsymbol().contains(symbol))
                        .filter(inst ->
                                "CE".equals(inst.getInstrumentType())
                                        || "PE".equals(inst.getInstrumentType()))
                        .collect(Collectors.toList());

        String currentExpiry =
                options.stream()
                        .map(ZerodhaInstrument::getExpiry)
                        .filter(Objects::nonNull)
                        .distinct()
                        .sorted()
                        .findFirst()
                        .orElse(null);

        if (currentExpiry == null) {
            return Map.of();
        }

        List<ZerodhaInstrument> currentOptions =
                options.stream()
                        .filter(inst ->
                                currentExpiry.equals(inst.getExpiry()))
                        .collect(Collectors.toList());

        Map<String, ZerodhaQuote> quotes =
                fetchQuotes(accessToken, currentOptions);

        return groupOptions(currentOptions, quotes);
    }

    private Map<Double, NiftyOptionPair> fetchOptionsDataForSymbolAndExpiry(
            String symbol,
            String targetExpiry,
            String accessToken) {

        List<ZerodhaInstrument> instruments =
                fetchInstruments(accessToken);

        List<ZerodhaInstrument> targetOptions =
                instruments.stream()
                        .filter(inst ->
                                symbol.equals(inst.getName()))
                        .filter(inst ->
                                targetExpiry.equalsIgnoreCase(inst.getExpiry()))
                        .filter(inst ->
                                "CE".equals(inst.getInstrumentType())
                                        || "PE".equals(inst.getInstrumentType()))
                        .collect(Collectors.toList());

        Map<String, ZerodhaQuote> quotes =
                fetchQuotes(accessToken, targetOptions);

        return groupOptions(targetOptions, quotes);
    }

    private Map<Double, NiftyOptionPair> groupOptions(
            List<ZerodhaInstrument> options,
            Map<String, ZerodhaQuote> quotes) {

        return options.stream()
                .collect(Collectors.groupingBy(
                        ZerodhaInstrument::getStrike))
                .entrySet()
                .stream()
                .collect(Collectors.toMap(
                        Map.Entry::getKey,
                        entry -> {
                            ZerodhaInstrument ce =
                                    entry.getValue().stream()
                                            .filter(inst ->
                                                    "CE".equals(inst.getInstrumentType()))
                                            .findFirst()
                                            .orElse(null);

                            ZerodhaInstrument pe =
                                    entry.getValue().stream()
                                            .filter(inst ->
                                                    "PE".equals(inst.getInstrumentType()))
                                            .findFirst()
                                            .orElse(null);

                            return new NiftyOptionPair(
                                    ce != null
                                            ? createOptionData(
                                            ce,
                                            quotes.get(
                                                    ce.getExchange()
                                                            + ":"
                                                            + ce.getTradingsymbol()))
                                            : null,
                                    pe != null
                                            ? createOptionData(
                                            pe,
                                            quotes.get(
                                                    pe.getExchange()
                                                            + ":"
                                                            + pe.getTradingsymbol()))
                                            : null
                            );
                        }
                ));
    }

    private OptionsDataEntity createEntity(
            String symbol,
            NiftyOptionData data,
            LocalDate date) {

        return OptionsDataEntity.builder()
                .symbol(symbol)
                .strike(BigDecimal.valueOf(data.getStrike()))
                .expiry(data.getExpiry())
                .type(data.getInstrumentType())
                .dataDate(date)
                .lastPrice(BigDecimal.valueOf(data.getLastPrice()))
                .oi(data.getOi())
                .volume(data.getVolume())
                .createdAt(LocalDateTime.now())
                .build();
    }

    @Data
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ZerodhaInstrument {
        private long instrumentToken;
        private String exchange;
        private String tradingsymbol;
        private String name;
        private double lastPrice;
        private String expiry;
        private double strike;
        private double tickSize;
        private int lotSize;
        private String instrumentType;
        private String segment;
        private String exchangeToken;
    }

    @Data
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ZerodhaQuote {
        private int instrumentToken;
        private double lastPrice;
        private Map<String, Double> ohlc;
        private Integer oi;
        private Integer oiDayHigh;
        private Integer oiDayLow;
        private Integer volume;
    }

    @Data
    @Builder
    public static class NiftyOptionData {
        private String tradingsymbol;
        private double strike;
        private String expiry;
        private String instrumentType;
        private double lastPrice;
        private int oi;
        private int volume;
    }

    @Data
    @AllArgsConstructor
    public static class NiftyOptionPair {
        private NiftyOptionData call;
        private NiftyOptionData put;
    }
}