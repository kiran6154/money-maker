package com.moneymaker.chart.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Types;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashMap;
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
 * <h3>Why plain JDBC and not JPA</h3>
 * Both entities key on {@code GenerationType.IDENTITY}, and Hibernate
 * <b>disables JDBC insert batching entirely</b> for identity-generated ids —
 * it has to round-trip each insert to read the generated key back. The previous
 * {@code saveAll} implementation therefore issued one INSERT per row plus a
 * resolving SELECT per chunk: tolerable for the ~100k rows the tables held when
 * it was written, hours for the ~3.8M rows of the full ICICI CSV set.
 *
 * <p>So the write path here is a {@code JdbcTemplate.batchUpdate} of
 * {@code INSERT … ON DUPLICATE KEY UPDATE}. Two consequences worth knowing:
 * <ul>
 *   <li>The resolving SELECT is gone — the unique natural key does the dedupe
 *       the in-memory index used to do, including for a key repeated inside one
 *       file, where the later row simply updates the earlier one. Re-importing
 *       a file is still a no-op, so the endpoint stays idempotent.</li>
 *   <li>{@code rewriteBatchedStatements=true} on the JDBC URL is what actually
 *       makes this fast — without it Connector/J still round-trips per row. With
 *       it, MySQL reports {@code Statement.SUCCESS_NO_INFO} per element, so the
 *       old {@code inserted} / {@code updated} split is no longer knowable and
 *       the response reports {@code rows} processed instead.</li>
 * </ul>
 *
 * <h3>Transactions</h3>
 * Deliberately none at method level. A 28k-row file in one transaction is a
 * large undo log for no benefit, and per-chunk commit makes a failed or
 * interrupted import resumable — re-running the file upserts the rows already
 * in and continues.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class HistoricalChartCsvImportService {

    /**
     * Rows per batch. Sized against {@code max_allowed_packet}: 5000 rows of
     * ~150 bytes rewrites into a ~750 KB multi-row INSERT, comfortably under
     * the 64 MB default.
     */
    private static final int CHUNK_SIZE = 5000;

    /**
     * {@code VALUES(col)} rather than the 8.0.19+ row-alias form
     * ({@code … AS new ON DUPLICATE KEY UPDATE open = new.open}). The alias form
     * is the non-deprecated spelling, but {@code VALUES()} is understood by every
     * MySQL from 5.7 through 9.x and this file should not pin the deployable
     * server version.
     */
    private static final String SPOT_UPSERT = """
            INSERT INTO historical_spot_candles
                (datetime, stock_code, exchange_code, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                open = VALUES(open), high = VALUES(high), low = VALUES(low),
                close = VALUES(close), volume = VALUES(volume)
            """;

    private static final String OPTION_UPSERT = """
            INSERT INTO historical_option_candles
                (datetime, stock_code, exchange_code, expiry_date, strike_price, option_right,
                 open, high, low, close, volume, open_interest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                open = VALUES(open), high = VALUES(high), low = VALUES(low),
                close = VALUES(close), volume = VALUES(volume),
                open_interest = VALUES(open_interest)
            """;

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

    private final JdbcTemplate jdbcTemplate;

    public Map<String, Integer> importSpot(MultipartFile file) throws IOException {
        int rows = 0;
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
                    rows += flushSpot(chunk);
                    chunk.clear();
                }
            }
            rows += flushSpot(chunk);
        }
        log.info("[historical-import] spot file={} rows={}", file.getOriginalFilename(), rows);
        return Map.of("rows", rows);
    }

    public Map<String, Integer> importOptions(MultipartFile file) throws IOException {
        int rows = 0;
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
                    rows += flushOptions(chunk);
                    chunk.clear();
                }
            }
            rows += flushOptions(chunk);
        }
        log.info("[historical-import] options file={} rows={}", file.getOriginalFilename(), rows);
        return Map.of("rows", rows);
    }

    // ---------------------------------------------------------------- flush

    private int flushSpot(List<SpotRow> chunk) {
        if (chunk.isEmpty()) {
            return 0;
        }
        jdbcTemplate.batchUpdate(SPOT_UPSERT, new BatchPreparedStatementSetter() {
            @Override
            public void setValues(PreparedStatement ps, int i) throws SQLException {
                SpotRow row = chunk.get(i);
                ps.setObject(1, row.dateTime);
                ps.setString(2, row.stockCode);
                ps.setString(3, row.exchangeCode);
                ps.setBigDecimal(4, row.open);
                ps.setBigDecimal(5, row.high);
                ps.setBigDecimal(6, row.low);
                ps.setBigDecimal(7, row.close);
                setNullableLong(ps, 8, row.volume);
            }

            @Override
            public int getBatchSize() {
                return chunk.size();
            }
        });
        return chunk.size();
    }

    private int flushOptions(List<OptionRow> chunk) {
        if (chunk.isEmpty()) {
            return 0;
        }
        jdbcTemplate.batchUpdate(OPTION_UPSERT, new BatchPreparedStatementSetter() {
            @Override
            public void setValues(PreparedStatement ps, int i) throws SQLException {
                OptionRow row = chunk.get(i);
                ps.setObject(1, row.dateTime);
                ps.setString(2, row.stockCode);
                ps.setString(3, row.exchangeCode);
                ps.setObject(4, row.expiryDate);
                ps.setBigDecimal(5, row.strikePrice);
                ps.setString(6, row.optionRight);
                ps.setBigDecimal(7, row.open);
                ps.setBigDecimal(8, row.high);
                ps.setBigDecimal(9, row.low);
                ps.setBigDecimal(10, row.close);
                setNullableLong(ps, 11, row.volume);
                setNullableLong(ps, 12, row.openInterest);
            }

            @Override
            public int getBatchSize() {
                return chunk.size();
            }
        });
        return chunk.size();
    }

    /** {@code volume} / {@code open_interest} are optional in the CSV contract. */
    private static void setNullableLong(PreparedStatement ps, int index, Long value) throws SQLException {
        if (value == null) {
            ps.setNull(index, Types.BIGINT);
        } else {
            ps.setLong(index, value);
        }
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

    /**
     * Upper-cases every keyed string column on the way in. Load-bearing: the
     * historical repositories match with a plain {@code =} so the natural-key
     * index stays usable, which relies on writers normalising rather than on a
     * {@code UPPER(...)} in the query.
     */
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
}
