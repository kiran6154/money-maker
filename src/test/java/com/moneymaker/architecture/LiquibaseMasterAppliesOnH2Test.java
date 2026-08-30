package com.moneymaker.architecture;

import liquibase.Contexts;
import liquibase.LabelExpression;
import liquibase.Liquibase;
import liquibase.database.Database;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.DirectoryResourceAccessor;
import liquibase.resource.ResourceAccessor;
import liquibase.resource.SearchPathResourceAccessor;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilderFactory;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The verification GAPS #23 said to budget time for, run against a throwaway
 * in-memory H2 schema rather than any real database.
 *
 * <p>{@code 005_create_market_data_table.xml} sat on disk unwired into the master
 * from the beginning, so it has never run anywhere, while
 * {@code spring.jpa.hibernate.ddl-auto=update} created {@code market_data} from
 * the {@code MarketData} JPA entity on every boot. Wiring it in is only safe if it
 * is a no-op when the table already exists — which is what the {@code tableExists}
 * precondition with {@code onFail=MARK_RAN} buys, and what these tests actually
 * execute rather than assert about.
 *
 * <p>Two runs, because the two populations differ and both must work:
 * <ul>
 *   <li><b>Fresh database</b> — nothing pre-created. 005 executes and creates the
 *       table, so 007 / 013 have something to {@code ALTER}. This is the case that
 *       makes putting the file under Liquibase worth anything at all.</li>
 *   <li><b>Hibernate got there first</b> — {@code market_data} pre-created before
 *       Liquibase runs, i.e. every environment that has ever booted this app.
 *       005 must be recorded {@code MARK_RAN}, not fail. Without the precondition
 *       this throws "table already exists" and takes startup down.</li>
 * </ul>
 *
 * <h3>Why a slice of the master and not the whole thing</h3>
 * The changelog is not H2-portable end to end:
 * {@code 032_backfill_trade_order_strategy_id.xml} uses MySQL's
 * {@code UPDATE … JOIN … SET} form, which H2 rejects with a syntax error. Rather
 * than fake that away, these tests run only the changesets that touch
 * {@code market_data} — <b>in the order the real master lists them</b>, read out of
 * {@code db.changelog-master.xml} at test time. So the ordering constraint that
 * matters here (005 must precede the two {@code ALTER}s) is enforced against the
 * real file: move the include below 007 and
 * {@link #applies_from_scratch()} fails, not just
 * {@link #master_orders_005_before_the_alters_that_depend_on_it()}.
 *
 * <p>No Spring context and no MySQL: H2 in {@code MODE=MySQL}, a unique in-memory
 * schema per test, dropped when the connection closes.
 */
class LiquibaseMasterAppliesOnH2Test {

    private static final Path CHANGELOG_DIR = Paths.get("src", "main", "resources", "db", "changelog");
    private static final Path MASTER_FILE = CHANGELOG_DIR.resolve("db.changelog-master.xml");

    /** {@code src/main/resources} — the root the master's include paths are relative to. */
    private static final File RESOURCE_ROOT = new File("src/main/resources");

    /** Where the generated slice changelog is written. A build artifact, not a source file. */
    private static final Path GENERATED_DIR = Paths.get("target", "liquibase-test");
    private static final String GENERATED_NAME = "market-data-slice.xml";

    /** Every changeset in the master that creates or alters {@code market_data}. */
    private static final List<String> MARKET_DATA_CHANGESETS = List.of(
            "005_create_market_data_table.xml",
            "007_add_sma_value_to_market_data.xml",
            "013_add_sma_value20_to_market_data.xml");

    /* ---------------- reading the real master ---------------- */

    /** The master's {@code <include file=…>} values, in document order. */
    private static List<String> masterIncludesInOrder() throws Exception {
        Document doc = DocumentBuilderFactory.newInstance()
                .newDocumentBuilder().parse(MASTER_FILE.toFile());
        NodeList includes = doc.getElementsByTagName("include");
        List<String> files = new ArrayList<>();
        for (int i = 0; i < includes.getLength(); i++) {
            files.add(((Element) includes.item(i)).getAttribute("file"));
        }
        return files;
    }

    /**
     * Writes a changelog containing only the {@code market_data} changesets, keeping
     * the master's own ordering. Lives under {@code target/} so it is a build
     * artifact, and next to the master so its relative includes still resolve.
     */
    private static String marketDataSliceChangelog() throws Exception {
        List<String> slice = masterIncludesInOrder().stream()
                .filter(f -> MARKET_DATA_CHANGESETS.contains(Paths.get(f).getFileName().toString()))
                .toList();

        assertThat(slice)
                .as("the master should include every market_data changeset: %s", MARKET_DATA_CHANGESETS)
                .hasSize(MARKET_DATA_CHANGESETS.size());

        StringBuilder xml = new StringBuilder("""
                <?xml version="1.0" encoding="UTF-8"?>
                <databaseChangeLog
                        xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
                        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                        xsi:schemaLocation="
                           http://www.liquibase.org/xml/ns/dbchangelog
                           http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-latest.xsd">
                """);
        for (String file : slice) {
            xml.append("    <include file=\"").append(file).append("\"/>\n");
        }
        xml.append("</databaseChangeLog>\n");

        Files.createDirectories(GENERATED_DIR);
        Files.writeString(GENERATED_DIR.resolve(GENERATED_NAME), xml.toString(), StandardCharsets.UTF_8);
        return GENERATED_NAME;
    }

    /* ---------------- H2 plumbing ---------------- */

    private static Connection freshH2() throws Exception {
        String name = "gaps23_" + UUID.randomUUID().toString().replace("-", "");
        return DriverManager.getConnection("jdbc:h2:mem:" + name + ";MODE=MySQL", "sa", "");
    }

    private static void runChangelog(Connection connection, String changelogPath) throws Exception {
        Database database = DatabaseFactory.getInstance()
                .findCorrectDatabaseImplementation(new JdbcConnection(connection));
        // Two roots: target/liquibase-test holds the generated slice, and
        // src/main/resources is what its "db/changelog/…" includes resolve against —
        // the same relative paths the real master uses, so the real files are what run.
        try (ResourceAccessor accessor = new SearchPathResourceAccessor(
                new DirectoryResourceAccessor(GENERATED_DIR.toAbsolutePath().toFile()),
                new DirectoryResourceAccessor(RESOURCE_ROOT.getAbsoluteFile()))) {
            // Deliberately not closed: Liquibase.close() closes the Database, which
            // closes the JDBC connection underneath it — and the caller still needs
            // that connection to read DATABASECHANGELOG back. The in-memory schema
            // goes away with the connection the caller does close.
            Liquibase liquibase = new Liquibase(changelogPath, accessor, database);
            liquibase.update(new Contexts(), new LabelExpression());
        }
    }

    /** The {@code EXECUTED} / {@code MARK_RAN} exec type Liquibase recorded for one changeset id. */
    private static String execType(Connection connection, String changesetId) throws Exception {
        try (Statement st = connection.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT EXECTYPE FROM DATABASECHANGELOG WHERE ID = '" + changesetId + "'")) {
            List<String> types = new ArrayList<>();
            while (rs.next()) {
                types.add(rs.getString(1));
            }
            assertThat(types)
                    .as("exactly one DATABASECHANGELOG row for changeset '%s'", changesetId)
                    .hasSize(1);
            return types.get(0);
        }
    }

    private static boolean columnExists(Connection connection, String table, String column) throws Exception {
        try (ResultSet rs = connection.getMetaData()
                .getColumns(null, null, table.toUpperCase(), column.toUpperCase())) {
            return rs.next();
        }
    }

    /* ---------------- the verification ---------------- */

    @Test
    @DisplayName("fresh database: 005 executes, creates market_data, and the later ALTERs land on it")
    void applies_from_scratch() throws Exception {
        String changelog = marketDataSliceChangelog();
        try (Connection connection = freshH2()) {
            runChangelog(connection, changelog);

            assertThat(execType(connection, "005_create_market_data_table"))
                    .as("on a fresh database 005 has work to do")
                    .isEqualTo("EXECUTED");
            assertThat(columnExists(connection, "market_data", "sma_value")).isTrue();
            assertThat(columnExists(connection, "market_data", "sma_value20")).isTrue();
        }
    }

    @Test
    @DisplayName("Hibernate got there first: 005 is MARK_RAN, not a 'table already exists' failure")
    void applies_when_market_data_already_exists() throws Exception {
        String changelog = marketDataSliceChangelog();
        try (Connection connection = freshH2()) {
            // Stands in for spring.jpa.hibernate.ddl-auto=update having created the
            // table from the MarketData entity — the state of every environment that
            // has ever booted this app.
            try (Statement st = connection.createStatement()) {
                st.execute("""
                        CREATE TABLE market_data (
                          id INT AUTO_INCREMENT PRIMARY KEY,
                          timestamp TIMESTAMP NOT NULL,
                          open DECIMAL(10,2) NOT NULL,
                          high DECIMAL(10,2) NOT NULL,
                          low DECIMAL(10,2) NOT NULL,
                          close DECIMAL(10,2) NOT NULL,
                          instrumenttoken VARCHAR(100) NOT NULL
                        )""");
            }

            runChangelog(connection, changelog);

            assertThat(execType(connection, "005_create_market_data_table"))
                    .as("the precondition must skip the createTable, not fail the migration")
                    .isEqualTo("MARK_RAN");
            assertThat(columnExists(connection, "market_data", "sma_value"))
                    .as("the later ALTERs still run against the pre-existing table")
                    .isTrue();
        }
    }

    @Test
    @DisplayName("the master includes 005 before every changeset that ALTERs market_data")
    void master_orders_005_before_the_alters_that_depend_on_it() throws Exception {
        List<String> basenames = masterIncludesInOrder().stream()
                .map(f -> Paths.get(f).getFileName().toString())
                .toList();

        int create = basenames.indexOf("005_create_market_data_table.xml");
        assertThat(create).as("005_create_market_data_table.xml must be included in the master").isNotNegative();

        for (String alter : List.of("007_add_sma_value_to_market_data.xml",
                                    "013_add_sma_value20_to_market_data.xml")) {
            assertThat(basenames.indexOf(alter))
                    .as("%s ALTERs market_data, so the createTable must be included before it", alter)
                    .isGreaterThan(create);
        }
    }
}
