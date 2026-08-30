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
            // docs/GAPS.md #21 -- 005_create_market_data_table.xml predates this
            // project's Liquibase adoption for the market_data table:
            // spring.jpa.hibernate.ddl-auto=update already created the table in
            // every environment that has ever run this app, and this changeset
            // (unlike 016/017) carries no tableExists precondition, so wiring it
            // into master today would throw "table already exists" against any
            // real database. Discovered while resolving GAPS #13/#14 but out of
            // that entry's scope (which covers only 016/017) -- left here
            // pending its own fix (add a tableExists precondition, then include).
            "005_create_market_data_table.xml"
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
