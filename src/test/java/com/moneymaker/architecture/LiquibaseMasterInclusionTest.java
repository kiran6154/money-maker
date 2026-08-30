package com.moneymaker.architecture;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.File;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Guards against the "orphan changeset" failure mode described in
 * {@code docs/GAPS.md} #13 and #14: a numbered Liquibase changeset file lands
 * on disk under {@code db/changelog/} but is never wired into
 * {@code db.changelog-master.xml}, so it silently never runs against any real
 * database. That has happened three times on this project — 005, 016, 017 —
 * and every one was caught by accident (an H2 boot failure, a manual doc
 * audit) rather than by the build. This test makes it a build failure.
 *
 * <p>Two independent directions are checked, because a changeset file and a
 * master {@code <include>} can drift apart in either direction:
 * <ul>
 *   <li>{@link #every_changeset_file_is_referenced_from_master()} — every
 *       {@code NNN_*.xml} file physically present under {@code db/changelog/}
 *       must be {@code <include>}d by the master, unless it is named in
 *       {@link #ALLOWLIST} with a comment pointing at the GAPS entry that
 *       explains why it is intentionally excluded.</li>
 *   <li>{@link #no_dangling_includes_in_master()} — every {@code <include>}
 *       in the master must resolve to a file that actually exists on disk
 *       (catches a rename/delete that forgot to update the master to match).</li>
 * </ul>
 *
 * <p>A third test, {@link #allowlist_entries_are_still_orphans()}, keeps
 * {@link #ALLOWLIST} itself honest: an entry that has been deleted or wired
 * into the master should be removed from the allowlist, not left stale.
 *
 * <p>Pure file I/O — no Spring context, no DB — so it runs in milliseconds
 * and can never be skipped by a broken datasource.
 */
class LiquibaseMasterInclusionTest {

    private static final Path CHANGELOG_DIR =
            Paths.get("src", "main", "resources", "db", "changelog");
    private static final Path MASTER_FILE = CHANGELOG_DIR.resolve("db.changelog-master.xml");

    /** Numbered changeset files: three digits, underscore, anything, .xml. */
    private static final Pattern CHANGESET_NAME = Pattern.compile("^\\d{3}_.*\\.xml$");

    /**
     * Changeset files that exist on disk but are deliberately NOT included in
     * the master. Every entry must carry a comment naming the GAPS entry that
     * explains why — an undocumented entry here defeats the point of the test.
     */
    private static final Set<String> ALLOWLIST = Set.of(
            // Empty. 005_create_market_data_table.xml was removed 2026-08-31 when
            // GAPS #23 was resolved: it gained a tableExists precondition
            // (onFail=MARK_RAN) and is now included in the master ahead of the
            // changesets that ALTER market_data. Verified against a throwaway H2
            // schema by LiquibaseMasterAppliesOnH2Test, both fresh and
            // Hibernate-created.
    );

    private static List<String> changesetFilesOnDisk() {
        File[] files = CHANGELOG_DIR.toFile().listFiles();
        assertThat(files)
                .as("changelog directory should exist and be listable: %s", CHANGELOG_DIR)
                .isNotNull();
        return Arrays.stream(files)
                .filter(File::isFile)
                .map(File::getName)
                .filter(name -> CHANGESET_NAME.matcher(name).matches())
                .sorted()
                .collect(Collectors.toList());
    }

    private static List<String> includedFileBasenames() throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        DocumentBuilder builder = factory.newDocumentBuilder();
        Document doc = builder.parse(MASTER_FILE.toFile());
        NodeList includes = doc.getElementsByTagName("include");

        List<String> basenames = new ArrayList<>();
        for (int i = 0; i < includes.getLength(); i++) {
            Element element = (Element) includes.item(i);
            String file = element.getAttribute("file");
            basenames.add(Paths.get(file).getFileName().toString());
        }
        return basenames;
    }

    @Test
    @DisplayName("every numbered changeset on disk is included in the master, or is on the explicit allowlist")
    void every_changeset_file_is_referenced_from_master() throws Exception {
        List<String> onDisk = changesetFilesOnDisk();
        Set<String> included = new LinkedHashSet<>(includedFileBasenames());

        List<String> orphans = onDisk.stream()
                .filter(name -> !included.contains(name) && !ALLOWLIST.contains(name))
                .collect(Collectors.toList());

        assertThat(orphans)
                .as("Changeset file(s) present under " + CHANGELOG_DIR
                        + " but not <include>d by " + MASTER_FILE.getFileName()
                        + " and not on the ALLOWLIST in this test. Either add an <include> to "
                        + "the master (only safe if the changeset has never been applied to a "
                        + "real database -- see docs/GAPS.md #13), or add it to ALLOWLIST with a "
                        + "comment naming the GAPS entry that explains why it stays excluded.")
                .isEmpty();
    }

    @Test
    @DisplayName("the allowlist does not carry stale entries for files that are deleted or now included")
    void allowlist_entries_are_still_orphans() throws Exception {
        List<String> onDisk = changesetFilesOnDisk();
        Set<String> included = new LinkedHashSet<>(includedFileBasenames());

        List<String> stale = ALLOWLIST.stream()
                .filter(name -> !onDisk.contains(name) || included.contains(name))
                .collect(Collectors.toList());

        assertThat(stale)
                .as("ALLOWLIST entries that are no longer real orphans (file deleted, or now "
                        + "included in the master) -- remove them from ALLOWLIST: " + stale)
                .isEmpty();
    }

    /**
     * A changeset's {@code xsi:schemaLocation} must name an XSD that the
     * liquibase-core on the classpath actually ships. Liquibase runs with
     * {@code secureParsing=true}, so an unbundled name is <b>not</b> fetched over
     * the network — parsing fails outright and the application never starts.
     *
     * <p>Not hypothetical: {@code 005_create_market_data_table.xml} declared
     * {@code dbchangelog-4.23.0.xsd}, which does not exist (the bundled file is
     * {@code dbchangelog-4.23.xsd}). It went unnoticed for as long as it did only
     * because the file was an orphan — nothing ever parsed it. The moment GAPS #23
     * wired it into the master, startup would have died at parse time, before any
     * precondition was evaluated. This test is that failure, moved to build time.
     */
    @Test
    @DisplayName("every changeset declares an XSD that the bundled Liquibase actually ships")
    void schema_locations_resolve_to_a_bundled_xsd() {
        // Read the attribute, not the file text: a comment that merely mentions a
        // bad XSD name is documentation, and matching it would be a false positive.
        Pattern xsdRef = Pattern.compile("dbchangelog-[^\"'\\s/]+\\.xsd");

        List<String> unresolvable = new ArrayList<>();
        List<String> names = new ArrayList<>(changesetFilesOnDisk());
        names.add(MASTER_FILE.getFileName().toString());

        for (String name : names) {
            String schemaLocation;
            try {
                Document doc = DocumentBuilderFactory.newInstance()
                        .newDocumentBuilder().parse(CHANGELOG_DIR.resolve(name).toFile());
                schemaLocation = doc.getDocumentElement().getAttributeNS(
                        "http://www.w3.org/2001/XMLSchema-instance", "schemaLocation");
            } catch (Exception e) {
                unresolvable.add(name + " (unparseable: " + e.getMessage() + ")");
                continue;
            }
            java.util.regex.Matcher m = xsdRef.matcher(schemaLocation == null ? "" : schemaLocation);
            while (m.find()) {
                String xsd = m.group();
                // Liquibase ships these on the classpath under the namespace path
                // it also uses as the remote URL.
                if (getClass().getClassLoader()
                        .getResource("www.liquibase.org/xml/ns/dbchangelog/" + xsd) == null) {
                    unresolvable.add(name + " -> " + xsd);
                }
            }
        }

        assertThat(unresolvable)
                .as("Changeset(s) whose xsi:schemaLocation names an XSD that liquibase-core does not "
                        + "bundle. With secureParsing=true these are not fetched remotely -- the changelog "
                        + "fails to parse and the app will not boot. Use dbchangelog-latest.xsd, or a "
                        + "version the bundled jar actually contains (note: '4.23' is bundled, '4.23.0' "
                        + "is not).")
                .isEmpty();
    }

    @Test
    @DisplayName("every <include> in the master resolves to a file that exists on disk")
    void no_dangling_includes_in_master() throws Exception {
        List<String> included = includedFileBasenames();

        List<String> dangling = included.stream()
                .filter(name -> !CHANGELOG_DIR.resolve(name).toFile().exists())
                .collect(Collectors.toList());

        assertThat(dangling)
                .as("<include> entries in " + MASTER_FILE.getFileName()
                        + " that don't resolve to a real file under " + CHANGELOG_DIR + ": " + dangling)
                .isEmpty();
    }
}
