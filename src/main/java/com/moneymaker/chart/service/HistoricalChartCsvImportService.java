package com.moneymaker.chart.service;

import com.moneymaker.entity.HistoricalOptionCandle;
import com.moneymaker.entity.HistoricalSpotCandle;
import com.moneymaker.repository.HistoricalOptionCandleRepository;
import com.moneymaker.repository.HistoricalSpotCandleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class HistoricalChartCsvImportService {

    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ISO_LOCAL_DATE;

    private final HistoricalSpotCandleRepository spotCandleRepository;
    private final HistoricalOptionCandleRepository optionCandleRepository;

    public Map<String, Integer> importSpot(MultipartFile file) throws IOException {
        ImportCounter counter = new ImportCounter();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8))) {
            Map<String, Integer> header = readHeader(reader);
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                String[] row = line.split(",", -1);
                HistoricalSpotCandle candle = spotCandleRepository
                        .findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndDateTime(
                                value(row, header, "stock_code"),
                                value(row, header, "exchange_code"),
                                dateTime(row, header, "datetime")
                        )
                        .orElseGet(HistoricalSpotCandle::new);

                boolean isNew = candle.getId() == null;
                candle.setDateTime(dateTime(row, header, "datetime"));
                candle.setStockCode(normalize(value(row, header, "stock_code")));
                candle.setExchangeCode(normalize(value(row, header, "exchange_code")));
                candle.setOpen(decimal(row, header, "open"));
                candle.setHigh(decimal(row, header, "high"));
                candle.setLow(decimal(row, header, "low"));
                candle.setClose(decimal(row, header, "close"));
                candle.setVolume(optionalLong(row, header, "volume"));
                spotCandleRepository.save(candle);
                counter.record(isNew);
            }
        }
        return counter.toMap();
    }

    public Map<String, Integer> importOptions(MultipartFile file) throws IOException {
        ImportCounter counter = new ImportCounter();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8))) {
            Map<String, Integer> header = readHeader(reader);
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                String[] row = line.split(",", -1);
                HistoricalOptionCandle candle = optionCandleRepository
                        .findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndExpiryDateAndStrikePriceAndOptionRightIgnoreCaseAndDateTime(
                                value(row, header, "stock_code"),
                                value(row, header, "exchange_code"),
                                date(row, header, "expiry_date"),
                                decimal(row, header, "strike_price"),
                                value(row, header, "right"),
                                dateTime(row, header, "datetime")
                        )
                        .orElseGet(HistoricalOptionCandle::new);

                boolean isNew = candle.getId() == null;
                candle.setDateTime(dateTime(row, header, "datetime"));
                candle.setStockCode(normalize(value(row, header, "stock_code")));
                candle.setExchangeCode(normalize(value(row, header, "exchange_code")));
                candle.setExpiryDate(date(row, header, "expiry_date"));
                candle.setStrikePrice(decimal(row, header, "strike_price"));
                candle.setOptionRight(normalize(value(row, header, "right")));
                candle.setOpen(decimal(row, header, "open"));
                candle.setHigh(decimal(row, header, "high"));
                candle.setLow(decimal(row, header, "low"));
                candle.setClose(decimal(row, header, "close"));
                candle.setVolume(optionalLong(row, header, "volume"));
                candle.setOpenInterest(optionalLong(row, header, "open_interest"));
                optionCandleRepository.save(candle);
                counter.record(isNew);
            }
        }
        return counter.toMap();
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

    private String value(String[] row, Map<String, Integer> header, String column) {
        Integer index = header.get(column);
        if (index == null) {
            throw new IllegalArgumentException("Missing required column: " + column);
        }
        if (index >= row.length) {
            throw new IllegalArgumentException("Missing value for column: " + column);
        }
        String value = row[index].trim();
        if (value.isEmpty()) {
            throw new IllegalArgumentException("Blank value for column: " + column);
        }
        return value;
    }

    private String normalize(String value) {
        return value.trim().toUpperCase(Locale.ROOT);
    }

    private LocalDateTime dateTime(String[] row, Map<String, Integer> header, String column) {
        return LocalDateTime.parse(value(row, header, column), DATE_TIME_FORMATTER);
    }

    private LocalDate date(String[] row, Map<String, Integer> header, String column) {
        return LocalDate.parse(value(row, header, column), DATE_FORMATTER);
    }

    private BigDecimal decimal(String[] row, Map<String, Integer> header, String column) {
        return new BigDecimal(value(row, header, column));
    }

    private Long optionalLong(String[] row, Map<String, Integer> header, String column) {
        Integer index = header.get(column);
        if (index == null || index >= row.length || row[index].isBlank()) {
            return null;
        }
        return Long.valueOf(row[index].trim());
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
