package com.moneymaker.architecture;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Build-time guard preventing the orphan-changeset bug class (GAPS #13/#14).
 *
 * <p><b>The bug:</b> a developer adds a new Liquibase changeset file but
 * forgets to wire it into {@code db.changelog-master.xml}. Production
 * silently tolerates the omission because Hibernate {@code ddl-auto=update}
 * creates the schema from JPA entities. Subsequent {@code ALTER TABLE}
 * changesets that depend on the missing one work on production but fail on
 * any fresh database (CI, dev laptop, new env). M0.1 surfaced this with
 * orphan {@code 005_create_market_data_table.xml}; we then discovered the
 * same pattern with {@code 016} and {@code 017}.
 *
 * <p><b>The guard:</b> every {@code .xml} file under {@code db/changelog/}
 * (excluding the master itself) must be referenced from the master via an
 * {@code <include file="…"/>} entry. New changeset files that aren't wired
 * in fail this test, surfacing the omission at build time instead of at
 * "production has a different schema than test" time.
 *
 * <p>If you intentionally want to defer wiring a changeset (e.g. it's a
 * forward-looking migration not ready to ship), <b>delete the file</b>
 * until it's ready. Keeping it in the source tree without an include is
 * the bug this test exists to prevent.
 */
class LiquibaseMasterInclusionTest {

    /** Path to the changelog directory, relative to the project root. */
    private static final Path CHANGELOG_DIR = Paths.get("src/main/resources/db/changelog");

    /** Filename of the master changelog (excluded from the orphan scan). */
    private static final String MASTER_FILE = "db.changelog-master.xml";

    /** Matches {@code <include file="db/changelog/XXX.xml"/>} (with or without quotes / spaces / self-close). */
    private static final Pattern INCLUDE_PATTERN =
            Pattern.compile("<include\\s+file\\s*=\\s*\"([^\"]+)\"");

    @Test
    void every_changeset_file_is_referenced_from_master() throws IOException {
        Set<String> onDisk = findChangesetFiles();
        Set<String> referenced = parseIncludedFiles();

        // Strip the leading "db/changelog/" so the two sets compare apples-to-apples.
        Set<String> onDiskNames = onDisk.stream()
                .map(p -> Paths.get(p).getFileName().toString())
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));
        Set<String> referencedNames = referenced.stream()
                .map(p -> Paths.get(p).getFileName().toString())
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));

        Set<String> orphans = new LinkedHashSet<>(onDiskNames);
        orphans.removeAll(referencedNames);

        assertThat(orphans)
                .as("Liquibase changesets present on disk but not wired into %s. " +
                    "Either include them via <include file=\"db/changelog/<name>\"/> in the master, " +
                    "or delete them from the source tree until they're ready to ship. " +
                    "See GAPS #13 / #14 in docs/GAPS.md for context.",
                    MASTER_FILE)
                .isEmpty();
    }

    @Test
    void no_dangling_includes_in_master_that_dont_resolve_to_a_real_file() throws IOException {
        Set<String> referenced = parseIncludedFiles();

        // Each reference is a classpath-style path like "db/changelog/001_*.xml".
        // Resolve relative to "src/main/resources/" and verify each exists.
        Path resourceRoot = Paths.get("src/main/resources");
        Set<String> missing = new LinkedHashSet<>();
        for (String ref : referenced) {
            Path resolved = resourceRoot.resolve(ref);
            if (!Files.exists(resolved)) {
                missing.add(ref);
            }
        }

        assertThat(missing)
                .as("Master changelog %s references files that don't exist on disk. " +
                    "Either restore the missing files or remove the dangling <include> entries.",
                    MASTER_FILE)
                .isEmpty();
    }

    /* ---------------- helpers ---------------- */

    private static Set<String> findChangesetFiles() throws IOException {
        try (Stream<Path> stream = Files.list(CHANGELOG_DIR)) {
            return stream
                    .filter(p -> p.getFileName().toString().endsWith(".xml"))
                    .filter(p -> !p.getFileName().toString().equals(MASTER_FILE))
                    .map(Path::toString)
                    .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));
        }
    }

    private static Set<String> parseIncludedFiles() throws IOException {
        Path master = CHANGELOG_DIR.resolve(MASTER_FILE);
        String xml = Files.readString(master, StandardCharsets.UTF_8);
        Set<String> includes = new LinkedHashSet<>();
        Matcher m = INCLUDE_PATTERN.matcher(xml);
        while (m.find()) {
            includes.add(m.group(1));
        }
        return includes;
    }
}
