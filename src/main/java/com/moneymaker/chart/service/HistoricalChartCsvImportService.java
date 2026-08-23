package com.moneymaker.chart.service;

import com.moneymaker.entity.HistoricalOptionCandle;
import com.moneymaker.entity.HistoricalSpotCandle;
import com.moneymaker.repository.HistoricalOptionCandleRepository;
import com.moneymaker.repository.HistoricalSpotCandleRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Imports ICICI-style 5-minute CSV exports into {@code historical_spot_candles}
 * and {@code historical_option_candles}, upserting on the natural key.
 *
 * <h3>Format tolerance</h3>
 * The upstream exporter is not fully consistent, and the sample files under
 * {@code docs/} prove it: some option exports use the header {@code right} with
 * {@code yyyy-MM-dd HH:mm:ss} timestamps, others use {@code option_right} with
 * {@code dd-MM-yyyy HH:mm}. Rather than force one shape on a producer we do not
 * own, both spellings and all four datetime layouts are accepted. The DB column
 * is {@code option_right} either way ({@code right} is a SQL keyword).
 *
 * <h3>Batching</h3>
 * Rows are processed in chunks of {@link #CHUNK_SIZE}. Each chunk resolves every
 * existing natural key in a single range query, then issues one {@code saveAll}.
 * The previous row-at-a-time SELECT+INSERT cost roughly two round trips per row —
 * about 56k for a 28k-row file.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class HistoricalChartCsvImportService {

    /** Rows resolved and flushed per batch. */
    private static final int CHUNK_SIZE = 1000;

    /** Accepted {@code datetime} layouts, tried in order. */
    private static final List<DateTimeFormatter> DATE_TIME_FORMATTERS = List.of(
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"),
            DateTimeFormatter.ofPattern("dd-MM-yyyy HH:mm:ss"),
            DateTimeFormatter.ofPattern("dd-MM-yyyy HH:mm")
    );

    /** Accepted {@code expiry_date} layouts, tried in order. */
    private static final List<DateTimeFormatter> DATE_FORMATTERS = List.of(
            DateTimeFormatter.ISO_LOCAL_DATE,
            DateTimeFormatter.ofPattern("dd-MM-yyyy")
    );

    /** Header spellings accepted for the CE/PE column. */
    private static final List<String> OPTION_RIGHT_COLUMNS = List.of("right", "option_right");

    private final HistoricalSpotCandleRepository spotCandleRepository;
    private final HistoricalOptionCandleRepository optionCandleRepository;

    @Transactional
    public Map<String, Integer> importSpot(MultipartFile file) throws IOException {
        ImportCounter counter = new ImportCounter();
        try (BufferedReader reader = open(file)) {
            Map<String, Integer> header = readHeader(reader);
            List<SpotRow> chunk = new ArrayList<>(CHUNK_SIZE);
            String line;
            int lineNumber = 1;

            while ((line = reader.readLine()) != null) {
                lineNumber++;
                if (line.isBlank()) {
                    continue;
                }
                chunk.add(parseSpotRow(line.split(",", -1), header, lineNumber));
                if (chunk.size() >= CHUNK_SIZE) {
                    flushSpot(chunk, counter);
                    chunk.clear();
                }
            }
            flushSpot(chunk, counter);
        }
        log.info("[historical-import] spot file={} inserted={} updated={}",
                file.getOriginalFilename(), counter.inserted, counter.updated);
        return counter.toMap();
    }

    @Transactional
    public Map<String, Integer> importOptions(MultipartFile file) throws IOException {
        ImportCounter counter = new ImportCounter();
        try (BufferedReader reader = open(file)) {
            Map<String, Integer> header = readHeader(reader);
            String rightColumn = resolveOptionRightColumn(header);
            List<OptionRow> chunk = new ArrayList<>(CHUNK_SIZE);
            String line;
            int lineNumber = 1;

            while ((line = reader.readLine()) != null) {
                lineNumber++;
                if (line.isBlank()) {
                    continue;
                }
                chunk.add(parseOptionRow(line.split(",", -1), header, rightColumn, lineNumber));
                if (chunk.size() >= CHUNK_SIZE) {
                    flushOptions(chunk, counter);
                    chunk.clear();
                }
            }
            flushOptions(chunk, counter);
        }
        log.info("[historical-import] options file={} inserted={} updated={}",
                file.getOriginalFilename(), counter.inserted, counter.updated);
        return counter.toMap();
    }

    // ---------------------------------------------------------------- flush

    private void flushSpot(List<SpotRow> chunk, ImportCounter counter) {
        if (chunk.isEmpty()) {
            return;
        }

        // One query resolves every natural key in the chunk. A single CSV always
        // carries one (stock_code, exchange_code) pair, so the first row's series
        // bounds the lookup; the in-memory index is still keyed by the full
        // natural key so a mixed file cannot mis-match.
        LocalDateTime from = chunk.get(0).dateTime;
        LocalDateTime to = from;
        for (SpotRow row : chunk) {
            if (row.dateTime.isBefore(from)) from = row.dateTime;
            if (row.dateTime.isAfter(to)) to = row.dateTime;
        }

        SpotRow first = chunk.get(0);
        Map<String, HistoricalSpotCandle> existing = new HashMap<>();
        for (HistoricalSpotCandle candle : spotCandleRepository
                .findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndDateTimeBetween(
                        first.stockCode, first.exchangeCode, from, to)) {
            existing.put(spotKey(candle.getStockCode(), candle.getExchangeCode(), candle.getDateTime()), candle);
        }

        List<HistoricalSpotCandle> toSave = new ArrayList<>(chunk.size());
        for (SpotRow row : chunk) {
            String key = spotKey(row.stockCode, row.exchangeCode, row.dateTime);
            HistoricalSpotCandle candle = existing.get(key);
            boolean isNew = candle == null;
            if (isNew) {
                candle = new HistoricalSpotCandle();
                candle.setDateTime(row.dateTime);
                candle.setStockCode(row.stockCode);
                candle.setExchangeCode(row.exchangeCode);
                // Guard against the same natural key appearing twice in one file.
                existing.put(key, candle);
            }
            candle.setOpen(row.open);
            candle.setHigh(row.high);
            candle.setLow(row.low);
            candle.setClose(row.close);
            candle.setVolume(row.volume);
            toSave.add(candle);
            counter.record(isNew);
        }
        spotCandleRepository.saveAll(toSave);
    }

    private void flushOptions(List<OptionRow> chunk, ImportCounter counter) {
        if (chunk.isEmpty()) {
            return;
        }

        // Resolve existing rows one *series* at a time, not by a bare datetime
        // range. A range query would return every strike alive in that window —
        // and since the CSV is ordered strike-major, a chunk spans days for a
        // single strike, so the range would sweep the whole file's worth of rows
        // on every chunk. Chunks normally touch one or two series, so this is one
        // or two indexed lookups.
        Map<String, HistoricalOptionCandle> existing = new HashMap<>();
        for (SeriesBounds bounds : optionSeriesBounds(chunk).values()) {
            for (HistoricalOptionCandle candle : optionCandleRepository.findRangeAsc(
                    bounds.stockCode, bounds.exchangeCode, bounds.expiryDate,
                    bounds.strikePrice, bounds.optionRight, bounds.from, bounds.to)) {
                existing.put(optionKey(candle.getStockCode(), candle.getExchangeCode(), candle.getExpiryDate(),
                        candle.getStrikePrice(), candle.getOptionRight(), candle.getDateTime()), candle);
            }
        }

        List<HistoricalOptionCandle> toSave = new ArrayList<>(chunk.size());
        for (OptionRow row : chunk) {
            String key = optionKey(row.stockCode, row.exchangeCode, row.expiryDate,
                    row.strikePrice, row.optionRight, row.dateTime);
            HistoricalOptionCandle candle = existing.get(key);
            boolean isNew = candle == null;
            if (isNew) {
                candle = new HistoricalOptionCandle();
                candle.setDateTime(row.dateTime);
                candle.setStockCode(row.stockCode);
                candle.setExchangeCode(row.exchangeCode);
                candle.setExpiryDate(row.expiryDate);
                candle.setStrikePrice(row.strikePrice);
                candle.setOptionRight(row.optionRight);
                existing.put(key, candle);
            }
            candle.setOpen(row.open);
            candle.setHigh(row.high);
            candle.setLow(row.low);
            candle.setClose(row.close);
            candle.setVolume(row.volume);
            candle.setOpenInterest(row.openInterest);
            toSave.add(candle);
            counter.record(isNew);
        }
        optionCandleRepository.saveAll(toSave);
    }

    /** Distinct option series in a chunk, each with the datetime window it spans. */
    private Map<String, SeriesBounds> optionSeriesBounds(List<OptionRow> chunk) {
        Map<String, SeriesBounds> bySeries = new LinkedHashMap<>();
        for (OptionRow row : chunk) {
            String seriesKey = row.stockCode + "|" + row.exchangeCode + "|" + row.expiryDate + "|"
                    + row.strikePrice.stripTrailingZeros().toPlainString() + "|" + row.optionRight;
            SeriesBounds bounds = bySeries.get(seriesKey);
            if (bounds == null) {
                bySeries.put(seriesKey, new SeriesBounds(row));
            } else {
                bounds.extend(row.dateTime);
            }
        }
        return bySeries;
    }

    /** Natural key of a spot row. */
    private String spotKey(String stockCode, String exchangeCode, LocalDateTime dateTime) {
        return stockCode.toUpperCase(Locale.ROOT) + "|" + exchangeCode.toUpperCase(Locale.ROOT) + "|" + dateTime;
    }

    /**
     * Natural key of an option row. Strike is normalised via
     * {@code stripTrailingZeros} so a {@code 21700} CSV literal indexes to the
     * same key as a stored {@code 21700.0000}.
     */
    private String optionKey(String stockCode, String exchangeCode, LocalDate expiryDate,
                             BigDecimal strikePrice, String optionRight, LocalDateTime dateTime) {
        return stockCode.toUpperCase(Locale.ROOT) + "|" + exchangeCode.toUpperCase(Locale.ROOT) + "|"
                + expiryDate + "|" + strikePrice.stripTrailingZeros().toPlainString() + "|"
                + optionRight.toUpperCase(Locale.ROOT) + "|" + dateTime;
    }

    // ---------------------------------------------------------------- parse

    private SpotRow parseSpotRow(String[] row, Map<String, Integer> header, int lineNumber) {
        SpotRow parsed = new SpotRow();
        parsed.dateTime = dateTime(row, header, "datetime", lineNumber);
        parsed.stockCode = normalize(value(row, header, "stock_code", lineNumber));
        parsed.exchangeCode = normalize(value(row, header, "exchange_code", lineNumber));
        parsed.open = decimal(row, header, "open", lineNumber);
        parsed.high = decimal(row, header, "high", lineNumber);
        parsed.low = decimal(row, header, "low", lineNumber);
        parsed.close = decimal(row, header, "close", lineNumber);
        parsed.volume = optionalLong(row, header, "volume", lineNumber);
        return parsed;
    }

    private OptionRow parseOptionRow(String[] row, Map<String, Integer> header, String rightColumn, int lineNumber) {
        OptionRow parsed = new OptionRow();
        parsed.dateTime = dateTime(row, header, "datetime", lineNumber);
        parsed.stockCode = normalize(value(row, header, "stock_code", lineNumber));
        parsed.exchangeCode = normalize(value(row, header, "exchange_code", lineNumber));
        parsed.expiryDate = date(row, header, "expiry_date", lineNumber);
        parsed.strikePrice = decimal(row, header, "strike_price", lineNumber);
        parsed.optionRight = normalize(value(row, header, rightColumn, lineNumber));
        parsed.open = decimal(row, header, "open", lineNumber);
        parsed.high = decimal(row, header, "high", lineNumber);
        parsed.low = decimal(row, header, "low", lineNumber);
        parsed.close = decimal(row, header, "close", lineNumber);
        parsed.volume = optionalLong(row, header, "volume", lineNumber);
        parsed.openInterest = optionalLong(row, header, "open_interest", lineNumber);
        return parsed;
    }

    private BufferedReader open(MultipartFile file) throws IOException {
        return new BufferedReader(new InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8));
    }

    private Map<String, Integer> readHeader(BufferedReader reader) throws IOException {
        String headerLine = reader.readLine();
        if (headerLine == null || headerLine.isBlank()) {
            throw new IllegalArgumentException("CSV header is required");
        }

        String[] columns = headerLine.split(",", -1);
        Map<String, Integer> header = new HashMap<>();
        for (int i = 0; i < columns.length; i++) {
            header.put(columns[i].trim().toLowerCase(Locale.ROOT), i);
        }
        return header;
    }

    /** Accepts either documented spelling of the CE/PE column. */
    private String resolveOptionRightColumn(Map<String, Integer> header) {
        for (String candidate : OPTION_RIGHT_COLUMNS) {
            if (header.containsKey(candidate)) {
                return candidate;
            }
        }
        throw new IllegalArgumentException(
                "Missing required column: one of " + OPTION_RIGHT_COLUMNS + " must be present");
    }

    private String value(String[] row, Map<String, Integer> header, String column, int lineNumber) {
        Integer index = header.get(column);
        if (index == null) {
            throw new IllegalArgumentException("Missing required column: " + column);
        }
        if (index >= row.length) {
            throw new IllegalArgumentException("Line " + lineNumber + ": missing value for column " + column);
        }
        String value = row[index].trim();
        if (value.isEmpty()) {
            throw new IllegalArgumentException("Line " + lineNumber + ": blank value for column " + column);
        }
        return value;
    }

    private String normalize(String value) {
        return value.trim().toUpperCase(Locale.ROOT);
    }

    private LocalDateTime dateTime(String[] row, Map<String, Integer> header, String column, int lineNumber) {
        String raw = value(row, header, column, lineNumber);
        for (DateTimeFormatter formatter : DATE_TIME_FORMATTERS) {
            try {
                return LocalDateTime.parse(raw, formatter);
            } catch (DateTimeParseException ignored) {
                // try the next accepted layout
            }
        }
        // Reported as IllegalArgumentException so the controller maps it to 400
        // rather than letting DateTimeParseException escape as a 500.
        throw new IllegalArgumentException("Line " + lineNumber + ": unparseable " + column + " value '" + raw
                + "'. Expected one of yyyy-MM-dd HH:mm[:ss] or dd-MM-yyyy HH:mm[:ss]");
    }

    private LocalDate date(String[] row, Map<String, Integer> header, String column, int lineNumber) {
        String raw = value(row, header, column, lineNumber);
        for (DateTimeFormatter formatter : DATE_FORMATTERS) {
            try {
                return LocalDate.parse(raw, formatter);
            } catch (DateTimeParseException ignored) {
                // try the next accepted layout
            }
        }
        throw new IllegalArgumentException("Line " + lineNumber + ": unparseable " + column + " value '" + raw
                + "'. Expected yyyy-MM-dd or dd-MM-yyyy");
    }

    private BigDecimal decimal(String[] row, Map<String, Integer> header, String column, int lineNumber) {
        String raw = value(row, header, column, lineNumber);
        try {
            return new BigDecimal(raw);
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("Line " + lineNumber + ": non-numeric " + column + " value '" + raw + "'");
        }
    }

    private Long optionalLong(String[] row, Map<String, Integer> header, String column, int lineNumber) {
        Integer index = header.get(column);
        if (index == null || index >= row.length || row[index].isBlank()) {
            return null;
        }
        String raw = row[index].trim();
        try {
            return Long.valueOf(raw);
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("Line " + lineNumber + ": non-numeric " + column + " value '" + raw + "'");
        }
    }

    // ---------------------------------------------------------------- rows

    private static final class SpotRow {
        private LocalDateTime dateTime;
        private String stockCode;
        private String exchangeCode;
        private BigDecimal open;
        private BigDecimal high;
        private BigDecimal low;
        private BigDecimal close;
        private Long volume;
    }

    /** One option series plus the datetime window a chunk covers for it. */
    private static final class SeriesBounds {
        private final String stockCode;
        private final String exchangeCode;
        private final LocalDate expiryDate;
        private final BigDecimal strikePrice;
        private final String optionRight;
        private LocalDateTime from;
        private LocalDateTime to;

        private SeriesBounds(OptionRow row) {
            this.stockCode = row.stockCode;
            this.exchangeCode = row.exchangeCode;
            this.expiryDate = row.expiryDate;
            this.strikePrice = row.strikePrice;
            this.optionRight = row.optionRight;
            this.from = row.dateTime;
            this.to = row.dateTime;
        }

        private void extend(LocalDateTime dateTime) {
            if (dateTime.isBefore(from)) from = dateTime;
            if (dateTime.isAfter(to)) to = dateTime;
        }
    }

    private static final class OptionRow {
        private LocalDateTime dateTime;
        private String stockCode;
        private String exchangeCode;
        private LocalDate expiryDate;
        private BigDecimal strikePrice;
        private String optionRight;
        private BigDecimal open;
        private BigDecimal high;
        private BigDecimal low;
        private BigDecimal close;
        private Long volume;
        private Long openInterest;
    }

    private static final class ImportCounter {
        private int inserted;
        private int updated;

        private void record(boolean isNew) {
            if (isNew) {
                inserted++;
            } else {
                updated++;
            }
        }

        private Map<String, Integer> toMap() {
            return Map.of("inserted", inserted, "updated", updated);
        }
    }
}
