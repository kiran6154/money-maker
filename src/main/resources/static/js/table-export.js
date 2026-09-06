/**
 * Shared table export: turn a set of rows into a downloadable CSV or TXT file.
 *
 * <p>Used by the Orders ledger (backtest page) and the Configured trade configs
 * table (trade-configs page). One home rather than a copy each, because the
 * fiddly parts — CSV quoting, the Excel BOM, the formula-injection guard, the
 * object-URL lifecycle — are exactly the parts that rot when duplicated.</p>
 *
 * <h3>Feed it values, not rendered cells</h3>
 * Callers build rows from the underlying objects, never by scraping the DOM. The
 * tables render `—` for null, `₹` before totals and HTML inside several columns;
 * an export carrying those is a screenshot in a spreadsheet's clothing. Null and
 * undefined become an empty cell here, numbers stay numbers, and timestamps stay
 * ISO, so the file is something you can sort and sum.
 */
const TableExport = (function () {

    /**
     * Cells that begin `=`, `+`, `@` or a control character are executed as
     * formulas by Excel and Sheets when the file is opened. Nothing this app
     * exports legitimately starts that way, so prefixing an apostrophe is a
     * guard with no false positives — and it costs nothing next to shipping a
     * file that runs on open.
     *
     * <p>A leading ASCII `-` is deliberately NOT guarded: every one of those is a
     * negative number (P/L, stop loss) that must stay numeric in the sheet.</p>
     */
    function neutralize(text) {
        return /^[=+@\t\r]/.test(text) ? "'" + text : text;
    }

    function cell(value) {
        if (value === null || value === undefined) return '';
        return neutralize(String(value));
    }

    /** RFC 4180: quote when the value holds a delimiter, a quote or a newline. */
    function csvCell(value) {
        const text = cell(value);
        return /[",\r\n]/.test(text) ? '"' + text.replaceAll('"', '""') + '"' : text;
    }

    /**
     * Tab-separated for the .txt flavour. Tabs and newlines inside a value would
     * shift every following column, so they collapse to spaces — TSV has no
     * quoting mechanism to escape them with.
     */
    function txtCell(value) {
        return cell(value).replace(/[\t\r\n]+/g, ' ');
    }

    function serialize(rows, format) {
        const render = format === 'txt' ? txtCell : csvCell;
        const sep = format === 'txt' ? '\t' : ',';
        // CRLF, not LF: Excel is the destination for most of these and it is the
        // line ending RFC 4180 specifies.
        return rows.map(row => row.map(render).join(sep)).join('\r\n');
    }

    function download(filename, text, mime) {
        // The BOM is what stops Excel reading UTF-8 as the local ANSI codepage,
        // which is how ₹ and en-dashes turn into mojibake on open.
        const blob = new Blob(['\uFEFF' + text], { type: mime });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        // Revoked on a timer rather than immediately: some browsers have not
        // finished reading the blob when click() returns.
        setTimeout(() => URL.revokeObjectURL(url), 2000);
    }

    /** Filesystem-safe, and stable enough that two exports sort next to each other. */
    function safeName(baseName) {
        return String(baseName || 'export').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '');
    }

    return {
        /**
         * @param rows   array of arrays; row 0 is the header
         * @param baseName filename without extension, e.g. "orders_2026-09-01_S2"
         * @param format 'csv' or 'txt'
         * @returns the number of data rows written, so the caller can report it
         */
        save: function (rows, baseName, format) {
            const list = Array.isArray(rows) ? rows : [];
            const kind = format === 'txt' ? 'txt' : 'csv';
            const mime = kind === 'txt' ? 'text/plain;charset=utf-8' : 'text/csv;charset=utf-8';
            download(safeName(baseName) + '.' + kind, serialize(list, kind), mime);
            return Math.max(list.length - 1, 0);
        }
    };
})();
