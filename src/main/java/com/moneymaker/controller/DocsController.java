package com.moneymaker.controller;

import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.commonmark.Extension;
import org.commonmark.ext.autolink.AutolinkExtension;
import org.commonmark.ext.gfm.tables.TablesExtension;
import org.commonmark.ext.heading.anchor.HeadingAnchorExtension;
import org.commonmark.node.Node;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.html.HtmlRenderer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Auto-discovering Markdown docs viewer.
 *
 * <p>Lists every {@code .md} file under {@code ${docs.root}} (workspace root
 * by default) and renders any selected file as HTML inside the standard
 * Thymeleaf shell. Drop a new {@code .md} file under {@code docs/} (or at
 * the workspace root) and it appears in the menu without any code change.</p>
 *
 * <ul>
 *   <li>{@code GET /docs}         – sidebar of every discovered Markdown file.</li>
 *   <li>{@code GET /docs/view}    – renders the selected file (query param {@code file}).</li>
 * </ul>
 *
 * <p>The {@code file} parameter is the document's <i>relative</i> path under
 * the configured root and is validated against directory traversal.</p>
 */
@Slf4j
@Controller
@RequiredArgsConstructor
public class DocsController {

    /** Root directory scanned for *.md files. Defaults to the working directory. */
    @Value("${docs.root:.}")
    private String docsRoot;

    /** Maximum depth to recurse when scanning. */
    @Value("${docs.max-depth:4}")
    private int maxDepth;

    private static final List<Extension> EXTENSIONS = List.of(
            TablesExtension.create(),
            AutolinkExtension.create(),
            HeadingAnchorExtension.create()
    );
    private static final Parser PARSER = Parser.builder().extensions(EXTENSIONS).build();
    private static final HtmlRenderer RENDERER = HtmlRenderer.builder().extensions(EXTENSIONS).build();

    @GetMapping("/docs")
    public String list(@RequestParam(value = "file", required = false) String file, Model model) {
        List<DocEntry> docs = discoverDocs();
        model.addAttribute("activePage", "docs");
        model.addAttribute("docs", docs);

        if (file != null && !file.isBlank()) {
            return view(file, model);
        }
        // Default: open the first doc (Readme if present)
        DocEntry first = docs.stream()
                .filter(d -> d.getRelativePath().equalsIgnoreCase("Readme.md"))
                .findFirst()
                .orElse(docs.isEmpty() ? null : docs.get(0));
        if (first != null) {
            return view(first.getRelativePath(), model);
        }
        model.addAttribute("docTitle", "No documents found");
        model.addAttribute("docHtml", "<p>No <code>.md</code> files were found under <code>" + docsRoot + "</code>.</p>");
        model.addAttribute("currentFile", null);
        return "docs/view";
    }

    @GetMapping("/docs/view")
    public String view(@RequestParam("file") String file, Model model) {
        Path root = Paths.get(docsRoot).toAbsolutePath().normalize();
        Path target = root.resolve(file).toAbsolutePath().normalize();
        if (!target.startsWith(root)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Path traversal blocked");
        }
        if (!Files.exists(target) || !Files.isRegularFile(target)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Doc not found: " + file);
        }
        if (!file.toLowerCase().endsWith(".md")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Only .md files can be rendered");
        }
        try {
            String md = Files.readString(target);
            Node parsed = PARSER.parse(md);
            String html = RENDERER.render(parsed);

            model.addAttribute("activePage", "docs");
            model.addAttribute("docs", discoverDocs());
            model.addAttribute("currentFile", file);
            model.addAttribute("docTitle", file);
            model.addAttribute("docHtml", html);
            return "docs/view";
        } catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Failed to read " + file, e);
        }
    }

    /* ---------- helpers ---------- */

    private List<DocEntry> discoverDocs() {
        Path root = Paths.get(docsRoot).toAbsolutePath().normalize();
        if (!Files.isDirectory(root)) {
            log.warn("[Docs] root {} is not a directory", root);
            return List.of();
        }
        List<DocEntry> out = new ArrayList<>();
        try {
            Files.walkFileTree(root, java.util.EnumSet.noneOf(FileVisitOption.class), maxDepth,
                    new SimpleFileVisitor<>() {
                        @Override
                        public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                            String name = dir.getFileName() == null ? "" : dir.getFileName().toString();
                            // Skip noisy / build / hidden directories.
                            if (name.startsWith(".") || name.equals("target") || name.equals("node_modules")
                                    || name.equals("build") || name.equals("out")) {
                                return FileVisitResult.SKIP_SUBTREE;
                            }
                            return FileVisitResult.CONTINUE;
                        }
                        @Override
                        public FileVisitResult visitFile(Path f, BasicFileAttributes attrs) {
                            String name = f.getFileName().toString();
                            if (name.toLowerCase().endsWith(".md")) {
                                Path rel = root.relativize(f);
                                String relStr = rel.toString().replace('\\', '/');
                                String group = rel.getNameCount() > 1 ? rel.getName(0).toString() : "root";
                                out.add(new DocEntry(name, relStr, group));
                            }
                            return FileVisitResult.CONTINUE;
                        }
                    });
        } catch (IOException e) {
            log.warn("[Docs] failed to scan {}: {}", root, e.getMessage());
        }
        // root-level docs first, then by group, then by name
        out.sort(Comparator
                .comparing((DocEntry d) -> !d.getGroup().equals("root"))
                .thenComparing(DocEntry::getGroup)
                .thenComparing(DocEntry::getName, String.CASE_INSENSITIVE_ORDER));
        return out;
    }

    @Data
    public static class DocEntry {
        private final String name;          // file name only, e.g. ARCHITECTURE.md
        private final String relativePath;  // e.g. docs/ARCHITECTURE.md
        private final String group;         // top-level folder, or "root"
    }
}

