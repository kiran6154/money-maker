(function () {
    const DEFAULT_INDEX = 'NIFTY';
    const DEFAULT_DATA_SOURCE = 'HISTORICAL_ICICI';
    const DEFAULT_TIMEFRAME = '5m';
    const DEFAULT_SMA_PERIODS = ['20', '50', '100', '200', '500'];
    // Overlay toggles. Both on by default, so the chart looks the same as before
    // anyone touches them. Unlike timeframes/SMA periods, this group is allowed
    // to be fully empty — "hide both" is a legitimate choice.
    const OVERLAY_SMA_HIGH = 'smaHigh';
    const OVERLAY_SUPERTREND = 'supertrend';
    const DEFAULT_OVERLAYS = [OVERLAY_SMA_HIGH, OVERLAY_SUPERTREND];
    const NO_DATA_MESSAGE = 'No market data available for selected date.';
    // The chart is always one continuous series across this many days ending at
    // Date. Not a mode and not a picker: there is no single-day view and no
    // from-date to choose, so there is also no inverted range to guard against.
    const CONTINUOUS_LOOKBACK_DAYS = 45;
    // One click of + or -. Exact inverses (0.8 x 1.25 = 1), so zooming in and
    // back out returns to the range you started from rather than drifting.
    const ZOOM_IN_FACTOR = 0.8;
    const ZOOM_OUT_FACTOR = 1.25;
    // Floor and ceiling in bars. Without the floor, repeated + eventually asks
    // for a zero-width range and the pane goes blank with no way back short of
    // a reload.
    const MIN_VISIBLE_BARS = 5;
    const MAX_VISIBLE_BARS = 20000;
    const CHART_HEIGHT_FALLBACK = 360;
    const MARKET_TIMEZONE = 'Asia/Kolkata';
    const LS_PREFIX = 'mm.chartDashboard.';
    const LS_KEYS = {
        date: LS_PREFIX + 'date',
        dataSource: LS_PREFIX + 'dataSource',
        indexSymbol: LS_PREFIX + 'indexSymbol',
        timeframes: LS_PREFIX + 'timeframes',
        smaPeriods: LS_PREFIX + 'smaPeriods',
        strike: LS_PREFIX + 'strike',
        overlays: LS_PREFIX + 'overlays',
        activeTimeframe: LS_PREFIX + 'activeTimeframe'
    };
    const timeLabelFormatter = new Intl.DateTimeFormat('en-IN', {
        timeZone: MARKET_TIMEZONE,
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
    const dateTimeLabelFormatter = new Intl.DateTimeFormat('en-IN', {
        timeZone: MARKET_TIMEZONE,
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
    // The hover readout shares one formatter so O/H/L/C and the SMA values line
    // up to the same 2 decimals - option premiums and index levels both read as
    // prices here, not as raw doubles.
    const priceFormatter = new Intl.NumberFormat('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });

    // Each period draws TWO lines — SMA over candle lows and SMA over candle highs —
    // in one shared colour, so a period reads as an envelope rather than as two
    // unrelated averages. The low line is the one the strategy actually gates on
    // (see SMAIndicatorImpl, which averages lows deliberately).
    const SMA_CONFIG = {
        20: { lowFields: ['sma20Low'], highFields: ['sma20High'], color: '#2f80ed' },
        50: { lowFields: ['sma50Low'], highFields: ['sma50High'], color: '#27ae60' },
        100: { lowFields: ['sma100Low'], highFields: ['sma100High'], color: '#f2994a' },
        200: { lowFields: ['sma200Low'], highFields: ['sma200High'], color: '#eb5757' },
        500: { lowFields: ['sma500Low'], highFields: ['sma500High'], color: '#6c5ce7' }
    };

    // SuperTrend(7, 3). Colours follow the candle body semantics already used on
    // this chart rather than the SMA palette: the line is a trend state, not
    // another average, so it borrows the up/down teal-red pair and sits thicker.
    const SUPERTREND_CONFIG = {
        field: 'supertrend',
        directionField: 'supertrendUp',
        upColor: '#26a69a',
        downColor: '#ef5350',
        lineWidth: 3,
        label: 'SuperTrend 7,3'
    };

    /**
     * Pane keys. These are the dashboard's own identifiers, NOT the API's
     * `chartType` — the fixed-timeframe panes below are ordinary PE / CE series
     * that happen to be pinned to one timeframe. `PANE_SPEC` maps a key to the
     * series the backend should be asked for and the timeframe to ask at.
     */
    const CHART_TYPES = {
        PE: 'PE',
        UNDERLYING: 'UNDERLYING',
        CE: 'CE',
        PE_15M: 'PE_15M',
        CE_15M: 'CE_15M',
        PE_10M: 'PE_10M',
        CE_10M: 'CE_10M',
        PE_AVG3: 'PE_AVG3',
        CE_AVG3: 'CE_AVG3',
        PE_AVG5: 'PE_AVG5',
        CE_AVG5: 'CE_AVG5'
    };

    /**
     * `series` is what goes on the wire as `chartType`; `timeframe` is the fixed
     * one this pane always draws, or `null` to follow the toolbar's chip;
     * `strikeSpan` is how many strikes either side of the plotted strike the
     * backend averages into one synthetic series, `0` being the plain contract.
     *
     * <p>Pinning is what makes the 15m / 10m rows useful: the 5m/10m/15m chip
     * moves the top two rows, while these keep a standing 15-minute and
     * 10-minute view of the same two legs so the three horizons can be read
     * against each other without touching a control.</p>
     *
     * <p>The two averaged rows answer a different question. A single strike's
     * premium is noisy and steps as the underlying walks across the strike grid;
     * the mean of a ladder straddling the money tracks the underlying instead of
     * tracking which side of a strike it sits on, so an SMA over it is a much
     * quieter line. They follow the toolbar chip rather than pinning, since the
     * comparison being made is against the panes above them at the same
     * timeframe, not across horizons.</p>
     */
    const PANE_SPEC = {
        PE:         { series: 'PE',         timeframe: null,  strikeSpan: 0 },
        UNDERLYING: { series: 'UNDERLYING', timeframe: null,  strikeSpan: 0 },
        CE:         { series: 'CE',         timeframe: null,  strikeSpan: 0 },
        PE_15M:     { series: 'PE',         timeframe: '15m', strikeSpan: 0 },
        CE_15M:     { series: 'CE',         timeframe: '15m', strikeSpan: 0 },
        PE_10M:     { series: 'PE',         timeframe: '10m', strikeSpan: 0 },
        CE_10M:     { series: 'CE',         timeframe: '10m', strikeSpan: 0 },
        PE_AVG3:    { series: 'PE',         timeframe: null,  strikeSpan: 1 },
        CE_AVG3:    { series: 'CE',         timeframe: null,  strikeSpan: 1 },
        PE_AVG5:    { series: 'PE',         timeframe: null,  strikeSpan: 2 },
        CE_AVG5:    { series: 'CE',         timeframe: null,  strikeSpan: 2 }
    };

    const PANE_KEYS = Object.keys(CHART_TYPES).map(key => CHART_TYPES[key]);

    /** The API series behind a pane key. */
    function seriesOf(paneKey) {
        const spec = PANE_SPEC[paneKey];
        return spec ? spec.series : paneKey;
    }

    /** The timeframe a pane draws: its pinned one, else whatever the chip says. */
    function timeframeOf(paneKey) {
        const spec = PANE_SPEC[paneKey];
        return (spec && spec.timeframe) ? spec.timeframe : state.activeTimeframe;
    }

    /** True when the pane is pinned and so ignores the toolbar chip. */
    function isPinned(paneKey) {
        const spec = PANE_SPEC[paneKey];
        return !!(spec && spec.timeframe);
    }

    /** Strikes either side to average into this pane; 0 for a plain contract. */
    function strikeSpanOf(paneKey) {
        const spec = PANE_SPEC[paneKey];
        return spec && spec.strikeSpan ? spec.strikeSpan : 0;
    }

    const state = {
        date: '',
        /** Always derived, never picked: date - CONTINUOUS_LOOKBACK_DAYS. */
        fromDate: '',
        dataSource: DEFAULT_DATA_SOURCE,
        indexSymbol: DEFAULT_INDEX,
        timeframes: [DEFAULT_TIMEFRAME],
        smaPeriods: [...DEFAULT_SMA_PERIODS],
        activeTimeframe: DEFAULT_TIMEFRAME,
        strike: '',
        overlays: [...DEFAULT_OVERLAYS],
        // Built from PANE_KEYS rather than listed, so adding a pane above is a
        // one-line change here instead of three easily-forgotten ones.
        responses: {},
        charts: {},
        controllers: {}
    };

    PANE_KEYS.forEach(paneKey => {
        state.responses[paneKey] = new Map();
        state.charts[paneKey] = null;
        state.controllers[paneKey] = null;
    });

    const els = {
        date: document.getElementById('chartDate'),
        dataSource: document.getElementById('chartDataSource'),
        indexSymbol: document.getElementById('chartIndexSymbol'),
        timeframes: document.getElementById('chartTimeframes'),
        smaPeriods: document.getElementById('chartSmaPeriods'),
        strike: document.getElementById('chartStrike'),
        overlays: document.getElementById('chartOverlays'),
        refreshBtn: document.getElementById('refreshChartsBtn'),
        prevDateBtn: document.getElementById('prevDateBtn'),
        nextDateBtn: document.getElementById('nextDateBtn'),
        todayDateBtn: document.getElementById('todayDateBtn'),
        fullscreenBtn: document.getElementById('fullscreenChartsBtn'),

        /**
         * Filled after `els` is built, from PANE_KEYS. Every pane's element ids
         * are its key's camelCase prefix plus a fixed suffix (PE_15M ->
         * pe15mPaneTitle, pe15mChart, …), so the eleven panes need one rule here
         * rather than eleven twelve-line literals — and the two the underlying
         * pane does not have (expiry, strike) resolve to null on their own.
         */
        panes: {}
    };

    PANE_KEYS.forEach(paneKey => {
        const prefix = paneIdPrefix(paneKey);
        const byId = suffix => document.getElementById(prefix + suffix);
        els.panes[paneKey] = {
            title: byId('PaneTitle'),
            activeBadge: byId('ActiveTimeframe'),
            selectedDate: byId('SelectedDate'),
            selectedIndex: byId('SelectedIndex'),
            selectedTimeframe: byId('SelectedTimeframe'),
            expiryDate: byId('ExpiryDate'),
            atmStrike: byId('AtmStrike'),
            legend: byId('SmaLegend'),
            loading: byId('LoadingState'),
            error: byId('ErrorState'),
            empty: byId('NoDataState'),
            chart: byId('Chart')
        };
    });

    function init() {
        hydrateDefaults();
        bindEvents();
        updateStateFromControls();
        renderSmaLegends();
        renderAllPanesInstruction();
        if (state.date) {
            reloadStrikeOptions().then(refreshAllCharts);
        }
    }

    function hydrateDefaults() {
        // A deep link wins over remembered state. This is what lets the orders
        // ledger open "the chart for this trade": the row links here with the
        // trade's date, index and strike, and those must not be silently
        // overwritten by whatever the last manual session happened to leave in
        // localStorage.
        const url = new URLSearchParams(window.location.search);
        const linked = {
            date: url.get('date'),
            indexSymbol: url.get('indexSymbol'),
            dataSource: url.get('dataSource'),
            strike: url.get('strike')
        };

        const storedDate = readStoredValue(LS_KEYS.date);
        const storedDataSource = readStoredValue(LS_KEYS.dataSource);
        const storedIndex = readStoredValue(LS_KEYS.indexSymbol);
        // Timeframes is single-select, but sessions that predate that still have
        // several values stored. Keep only the first, or the toolbar would come
        // back multi-selected before the user has touched anything.
        const storedTimeframes = readStoredList(LS_KEYS.timeframes, [DEFAULT_TIMEFRAME]).slice(0, 1);
        const storedSmaPeriods = readStoredList(LS_KEYS.smaPeriods, DEFAULT_SMA_PERIODS);
        const storedActiveTimeframe = readStoredValue(LS_KEYS.activeTimeframe);
        const storedStrike = readStoredValue(LS_KEYS.strike);
        const storedOverlays = readStoredListAllowEmpty(LS_KEYS.overlays, DEFAULT_OVERLAYS);

        if (els.indexSymbol) {
            els.indexSymbol.value = linked.indexSymbol || storedIndex || els.indexSymbol.value || DEFAULT_INDEX;
        }
        if (els.dataSource) {
            els.dataSource.value = linked.dataSource || storedDataSource || els.dataSource.value || DEFAULT_DATA_SOURCE;
        }

        setMultiSelectValues(els.timeframes, storedTimeframes);
        setMultiSelectValues(els.smaPeriods, storedSmaPeriods);
        setMultiSelectValues(els.overlays, storedOverlays);
        if (storedActiveTimeframe) {
            state.activeTimeframe = storedActiveTimeframe;
        }

        if (els.date && (linked.date || !els.date.value)) {
            els.date.value = linked.date || storedDate || localDateString(new Date());
        }
        // The ladder itself loads async in init(); remember the choice so
        // reloadStrikeOptions can re-select it if it is still available.
        state.strike = linked.strike || storedStrike || '';
    }

    function bindEvents() {
        if (els.date) els.date.addEventListener('change', onLadderFiltersChanged);
        // Delegated: every pane's buttons are static markup, but the charts
        // behind them are destroyed and rebuilt on every refresh, so binding per
        // button would still have to survive that. One listener does not care.
        document.addEventListener('click', function (event) {
            const button = event.target.closest('.chart-zoom-btn');
            if (!button) return;
            const chartType = button.getAttribute('data-zoom-chart');
            const zoomingIn = button.getAttribute('data-zoom') === 'in';
            zoomChart(chartType, zoomingIn ? ZOOM_IN_FACTOR : ZOOM_OUT_FACTOR);
        });
        if (els.dataSource) els.dataSource.addEventListener('change', onLadderFiltersChanged);
        if (els.indexSymbol) els.indexSymbol.addEventListener('change', onLadderFiltersChanged);
        bindChipGroup(els.timeframes, onFiltersChanged, { single: true });
        bindChipGroup(els.smaPeriods, onFiltersChanged);
        if (els.strike) els.strike.addEventListener('change', onFiltersChanged);
        bindChipGroup(els.overlays, onOverlaysChanged, { allowEmpty: true });
        if (els.refreshBtn) els.refreshBtn.addEventListener('click', refreshAllCharts);
        if (els.prevDateBtn) els.prevDateBtn.addEventListener('click', () => stepDate(-1));
        if (els.nextDateBtn) els.nextDateBtn.addEventListener('click', () => stepDate(1));
        if (els.todayDateBtn) els.todayDateBtn.addEventListener('click', setToday);
        if (els.fullscreenBtn) els.fullscreenBtn.addEventListener('click', toggleFullscreenMode);
        document.addEventListener('keydown', onKeyboardShortcut);
    }

    /**
     * @param options.allowEmpty when false (the default) the group refuses to go
     *        empty, because a chart with zero SMA periods is not a meaningful
     *        state. Overlay toggles pass true — turning everything off is
     *        exactly what "hide the overlays" means.
     * @param options.single makes the group behave like a radio set: picking a
     *        chip clears its siblings, and re-clicking the active one does
     *        nothing rather than deselecting it. Implies allowEmpty:false, since
     *        a radio set that can be emptied is just a checkbox set.
     */
    function bindChipGroup(group, callback, options) {
        if (!group) return;

        const settings = options || {};
        const single = settings.single === true;
        const allowEmpty = !single && settings.allowEmpty === true;
        const chips = () => Array.from(group.querySelectorAll('.chart-chip'));

        const syncPressed = () => {
            chips().forEach(chip => {
                chip.setAttribute('aria-pressed', chip.classList.contains('is-selected') ? 'true' : 'false');
            });
        };

        chips().forEach(button => {
            button.setAttribute('aria-pressed', button.classList.contains('is-selected') ? 'true' : 'false');
            button.addEventListener('click', () => {
                if (single) {
                    // Bail before the callback when the active chip is clicked
                    // again: the selection is unchanged, and onFiltersChanged
                    // would otherwise fire a full eleven-request refresh for it.
                    if (button.classList.contains('is-selected')) return;
                    chips().forEach(chip => chip.classList.toggle('is-selected', chip === button));
                } else {
                    button.classList.toggle('is-selected');
                    if (!allowEmpty && !group.querySelector('.chart-chip.is-selected')) {
                        button.classList.add('is-selected');
                    }
                }
                syncPressed();
                callback();
            });
        });
    }

    function onFiltersChanged() {
        updateStateFromControls();
        normalizeActiveTimeframe();
        persistState();
        renderSmaLegends();
        refreshAllCharts();
    }

    /**
     * Overlays are a pure render concern — the responses already in
     * state.responses carry every SMA and SuperTrend field regardless. So this
     * redraws from cache instead of going through refreshAllCharts, which would
     * fire eleven identical requests just to hide a line.
     */
    function onOverlaysChanged() {
        updateStateFromControls();
        persistState();
        renderSmaLegends();
        renderVisiblePanes();
    }

    /** Filters that invalidate the strike ladder: reload it, then redraw. */
    function onLadderFiltersChanged() {
        updateStateFromControls();
        persistState();
        reloadStrikeOptions().then(onFiltersChanged);
    }

    /**
     * Reloads the strike ladder whenever the date, index or data source changes,
     * since each combination has its own expiry and therefore its own strikes.
     * Keeps the current selection if it still exists, otherwise falls back to
     * ATM (auto) rather than silently charting an unrelated strike.
     */
    function reloadStrikeOptions() {
        if (!els.strike || !state.date) return Promise.resolve();

        const params = new URLSearchParams({
            date: state.date,
            indexSymbol: state.indexSymbol,
            dataSource: state.dataSource,
            chartType: CHART_TYPES.CE
        });

        return fetch('/api/charts/strikes?' + params.toString())
            .then(response => (response.ok ? response.json() : null))
            .then(payload => {
                const previous = state.strike;
                const strikes = payload && Array.isArray(payload.strikes) ? payload.strikes : [];
                const atm = payload && payload.atmStrike != null ? toNumber(payload.atmStrike) : null;

                els.strike.innerHTML = '';

                const autoOption = document.createElement('option');
                autoOption.value = '';
                autoOption.textContent = atm != null
                    ? 'ATM (auto) - ' + formatStrike(atm)
                    : 'ATM (auto)';
                els.strike.appendChild(autoOption);

                strikes.forEach(raw => {
                    const value = toNumber(raw);
                    if (!Number.isFinite(value)) return;
                    const option = document.createElement('option');
                    option.value = String(value);
                    option.textContent = formatStrike(value) + (atm != null && value === atm ? ' (ATM)' : '');
                    els.strike.appendChild(option);
                });

                const stillAvailable = previous
                    && Array.prototype.some.call(els.strike.options, opt => opt.value === previous);
                els.strike.value = stillAvailable ? previous : '';
                state.strike = els.strike.value;
                persistState();
            })
            .catch(() => {
                // Ladder unavailable (offline, bad date, no data) — leave the
                // picker on ATM so the charts still render their default.
                els.strike.innerHTML = '<option value="" selected>ATM (auto)</option>';
                state.strike = '';
            });
    }

    /** Strikes are whole numbers in practice; drop a trailing .0 for readability. */
    function formatStrike(value) {
        return Number.isInteger(value) ? String(value) : String(value);
    }

    function updateStateFromControls() {
        state.date = els.date ? els.date.value : '';
        // Always the 45-day window. Derived rather than entered, so the inverted
        // range the old from-date picker had to guard against cannot occur.
        state.fromDate = continuousFromDate(state.date);
        state.dataSource = els.dataSource && els.dataSource.value ? els.dataSource.value : DEFAULT_DATA_SOURCE;
        state.indexSymbol = els.indexSymbol && els.indexSymbol.value ? els.indexSymbol.value : DEFAULT_INDEX;
        state.timeframes = getSelectedValues(els.timeframes, [DEFAULT_TIMEFRAME]);
        state.smaPeriods = getSelectedValues(els.smaPeriods, DEFAULT_SMA_PERIODS);
        state.strike = els.strike && els.strike.value ? els.strike.value : '';
        state.overlays = getToggledValues(els.overlays);
    }

    /** Chip values with no fallback, so an intentionally empty group stays empty. */
    function getToggledValues(group) {
        if (!group) return [];
        return Array.from(group.querySelectorAll('.chart-chip.is-selected'))
            .map(button => button.dataset.value)
            .filter(Boolean);
    }

    /** Like readStoredList, but a stored empty array is honoured, not replaced. */
    function readStoredListAllowEmpty(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return [...fallback];
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed.map(String) : [...fallback];
        } catch (e) {
            return [...fallback];
        }
    }

    function getSelectedValues(select, fallback) {
        if (!select) return [...fallback];
        if (select.matches && select.matches('.chart-chip-group')) {
            const values = Array.from(select.querySelectorAll('.chart-chip.is-selected'))
                .map(button => button.dataset.value)
                .filter(Boolean);
            return values.length ? values : [...fallback];
        }
        const values = Array.from(select.selectedOptions).map(option => option.value);
        return values.length ? values : [...fallback];
    }

    function setMultiSelectValues(select, values) {
        if (!select) return;
        const wanted = new Set(values);
        if (select.matches && select.matches('.chart-chip-group')) {
            Array.from(select.querySelectorAll('.chart-chip')).forEach(button => {
                button.classList.toggle('is-selected', wanted.has(button.dataset.value));
                button.setAttribute('aria-pressed', wanted.has(button.dataset.value) ? 'true' : 'false');
            });
            return;
        }
        Array.from(select.options).forEach(option => {
            option.selected = wanted.has(option.value);
        });
    }

    function normalizeActiveTimeframe() {
        if (!state.timeframes.includes(state.activeTimeframe)) {
            state.activeTimeframe = state.timeframes.includes(DEFAULT_TIMEFRAME)
                ? DEFAULT_TIMEFRAME
                : state.timeframes[0];
        }
    }

    function refreshAllCharts() {
        if (!state.date) {
            clearResponses();
            renderAllPanesInstruction();
            return;
        }

        clearResponses();
        PANE_KEYS.forEach(fetchPaneData);
    }

    function clearResponses() {
        Object.values(state.responses).forEach(map => map.clear());
    }

    function fetchPaneData(chartType) {
        abortPending(chartType);
        const controller = new AbortController();
        state.controllers[chartType] = controller;

        setPaneLoading(chartType, true);
        setPaneError(chartType, false);
        setPaneEmpty(chartType, false);
        renderPaneMetadata(chartType, null);

        // A pinned pane fetches its own timeframe and ignores the chip; the rest
        // fetch whatever the chip currently selects.
        const wanted = isPinned(chartType) ? [timeframeOf(chartType)] : state.timeframes;
        const requests = wanted.map(timeframe =>
            fetchChartData(chartType, timeframe, controller.signal)
                .then(response => ({ timeframe, response }))
        );

        Promise.all(requests)
            .then(results => {
                if (controller.signal.aborted) return;
                const target = state.responses[chartType];
                results.forEach(result => {
                    target.set(result.timeframe, result.response);
                });
                        renderSmaLegends();
                renderPane(chartType);
            })
            .catch(error => {
                if (error && error.name === 'AbortError') return;
                console.error('[chart-dashboard] fetch failed for', chartType, error);
                renderPaneError(chartType, 'Unable to load market data.');
            })
            .finally(() => {
                if (state.controllers[chartType] === controller) {
                    state.controllers[chartType] = null;
                }
                setPaneLoading(chartType, false);
            });
    }

    function abortPending(chartType) {
        const existing = state.controllers[chartType];
        if (existing) {
            existing.abort();
        }
    }

    function fetchChartData(chartType, timeframe, signal) {
        const params = new URLSearchParams({
            date: state.date,
            dataSource: state.dataSource,
            indexSymbol: state.indexSymbol,
            chartType: seriesOf(chartType),
            timeframe: timeframe,
            smaPeriods: state.smaPeriods.join(',')
        });

        // Always sent, so the backend always draws one series across
        // [fromDate, date]. Its single-day path (fromDate absent) is still
        // supported and still reachable from the API — just not from this page.
        if (state.fromDate) {
            params.set('fromDate', state.fromDate);
        }

        // Blank strike = ATM (auto); the backend resolves it. The underlying
        // chart has no strike, so never send one for it.
        if (state.strike && seriesOf(chartType) !== CHART_TYPES.UNDERLYING) {
            params.set('strike', state.strike);
        }

        // Only sent when the pane actually averages a ladder. Omitting it on the
        // other panes keeps their request identical to what it was, so the plain
        // contract panes cannot be perturbed by this feature.
        const span = strikeSpanOf(chartType);
        if (span > 0 && seriesOf(chartType) !== CHART_TYPES.UNDERLYING) {
            params.set('strikeSpan', String(span));
        }

        return fetch('/api/charts/market-data?' + params.toString(), { signal })
            .then(async response => {
                if (!response.ok) {
                    let message = 'HTTP ' + response.status;
                    try {
                        const body = await response.json();
                        if (body && body.error) message = body.error;
                    } catch (e) {
                        // ignore non-JSON error body
                    }
                    throw new Error(message);
                }
                return response.json();
            });
    }

    function renderAllPanesInstruction() {
        Object.keys(CHART_TYPES).forEach(key => {
            const chartType = CHART_TYPES[key];
            const pane = els.panes[chartType];
            if (!pane) return;
            renderPaneMetadata(chartType, null);
            setPaneLoading(chartType, false);
            setPaneError(chartType, false);
            setPaneEmpty(chartType, true, 'Select a date to load market data.');
            destroyPaneChart(chartType);
        });
    }

    function renderPane(chartType) {
        const pane = els.panes[chartType];
        const response = state.responses[chartType].get(timeframeOf(chartType));

        renderPaneMetadata(chartType, response || null);

        if (!response || !Array.isArray(response.data) || response.data.length === 0) {
            setPaneError(chartType, false);
            setPaneEmpty(chartType, true, NO_DATA_MESSAGE);
            destroyPaneChart(chartType);
            return;
        }

        setPaneError(chartType, false);
        setPaneEmpty(chartType, false);
        renderChart(chartType, response);
    }

    function renderPaneError(chartType, message) {
        const pane = els.panes[chartType];
        if (!pane) return;
        setPaneError(chartType, true, message);
        setPaneEmpty(chartType, false);
        destroyPaneChart(chartType);
    }

    function renderPaneMetadata(chartType, response) {
        const pane = els.panes[chartType];
        if (!pane) return;

        const paneTimeframe = timeframeOf(chartType);

        // chartTypeLabel already special-cases the underlying pane, so the
        // heading and the fallback summary cannot name a pane differently.
        if (pane.title) pane.title.textContent = chartTypeLabel(chartType);
        if (pane.activeBadge) pane.activeBadge.textContent = paneTimeframe;
        if (pane.selectedDate) pane.selectedDate.textContent = state.date || '-';
        if (pane.selectedIndex) pane.selectedIndex.textContent = state.indexSymbol || DEFAULT_INDEX;
        if (pane.selectedTimeframe) pane.selectedTimeframe.textContent = paneTimeframe;
        if (pane.expiryDate) pane.expiryDate.textContent = response && response.expiryDate ? response.expiryDate : '-';
        if (pane.atmStrike) pane.atmStrike.textContent = strikeMetaText(response);
    }

    /**
     * The Strike meta cell. An averaged pane names the ladder it really drew
     * rather than its centre — the backend drops a leg that had no candles, so
     * "±2 avg" in the heading can be three contracts in the data, and the count
     * here is the only place that discrepancy is visible.
     *
     * <p>Driven by the response rather than by the pane's own strikeSpan for
     * exactly that reason: the pane knows what it asked for, only the response
     * knows what came back.</p>
     */
    function strikeMetaText(response) {
        if (!response) return '-';

        const legs = Array.isArray(response.averagedStrikes) ? response.averagedStrikes : [];
        if (legs.length) {
            const values = legs.map(toNumber).filter(Number.isFinite);
            if (values.length) {
                const span = values.length === 1
                    ? formatStrike(values[0])
                    : formatStrike(Math.min.apply(null, values)) + '-' +
                      formatStrike(Math.max.apply(null, values));
                return span + ' (avg of ' + values.length + ')';
            }
        }

        return response.atmStrike != null ? String(response.atmStrike) : '-';
    }

    function renderVisiblePanes() {
        PANE_KEYS.forEach(renderPane);
    }

    function renderSmaLegends() {
        Object.keys(CHART_TYPES).forEach(key => {
            const chartType = CHART_TYPES[key];
            const pane = els.panes[chartType];
            if (!pane || !pane.legend) return;

            pane.legend.innerHTML = '';

            state.smaPeriods.forEach(period => {
                const config = SMA_CONFIG[period];
                if (!config) return;

                const item = document.createElement('span');
                item.className = 'chart-sma-legend-item';
                item.style.color = config.color;
                // One entry per period: the low and high lines share this colour,
                // so the suffix has to say which of them is actually drawn.
                item.innerHTML =
                    '<span class="chart-sma-legend-swatch"></span>' +
                    '<span>SMA ' + escapeHtml(String(period)) +
                    (showSmaHigh() ? ' H/L' : ' L') + '</span>';
                pane.legend.appendChild(item);
            });

            if (showSupertrend()) {
                // One swatch, not two. SuperTrend reads buy or sell at any one
                // moment and never both, so a two-colour key misrepresented the
                // indicator — it is a direction, not a pair of lines.
                const direction = latestSupertrendDirection(
                    state.responses[chartType].get(timeframeOf(chartType)));
                const supertrendItem = document.createElement('span');
                supertrendItem.className = 'chart-sma-legend-item';
                supertrendItem.style.color = direction == null
                    ? 'var(--text-muted)'
                    : (direction ? SUPERTREND_CONFIG.upColor : SUPERTREND_CONFIG.downColor);
                supertrendItem.innerHTML =
                    '<span class="chart-sma-legend-swatch"></span>' +
                    '<span>' + escapeHtml(SUPERTREND_CONFIG.label) +
                    (direction == null ? '' : ' · ' + (direction ? 'Buy' : 'Sell')) +
                    '</span>';
                pane.legend.appendChild(supertrendItem);
            }
        });
    }

    function showSmaHigh() {
        return state.overlays.indexOf(OVERLAY_SMA_HIGH) !== -1;
    }

    function showSupertrend() {
        return state.overlays.indexOf(OVERLAY_SUPERTREND) !== -1;
    }

    function renderChart(chartType, response) {
        const pane = els.panes[chartType];
        if (!pane || !pane.chart) return;

        if (!window.LightweightCharts || typeof window.LightweightCharts.createChart !== 'function') {
            console.warn('[chart-dashboard] lightweight-charts is not available. Falling back to summary view.');
            renderPlaceholderChart(chartType, response);
            return;
        }

        try {
            destroyPaneChart(chartType);

            const chart = createPaneChart(pane.chart);
            const candleSeries = chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderVisible: false,
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350',
                priceLineVisible: true,
                lastValueVisible: true
            });

            const candlestickData = mapCandlestickData(response.data);
            candleSeries.setData(candlestickData);

            // The low line is always drawn — it is the one the strategy gates
            // on. The high line is the optional half of the pair.
            const fieldSets = showSmaHigh()
                ? ['lowFields', 'highFields']
                : ['lowFields'];

            state.smaPeriods.forEach(period => {
                const config = SMA_CONFIG[period];
                if (!config) return;

                // Low and high share the colour and the styling — the pair is
                // meant to read as one band per period.
                fieldSets.forEach(key => {
                    const lineData = mapSmaData(response.data, config[key]);
                    if (!lineData.length) return;

                    const lineSeries = chart.addLineSeries({
                        color: config.color,
                        lineWidth: 2,
                        priceLineVisible: false,
                        lastValueVisible: false,
                        crosshairMarkerVisible: false,
                        lineStyle: window.LightweightCharts.LineStyle.Solid
                    });
                    lineSeries.setData(lineData);
                });
            });

            if (showSupertrend()) {
                renderSupertrend(chart, response.data);
            }

            focusSelectedSession(chart, response.data);
            attachRangeSync(chartType, chart);
            attachResizeHandler(chartType, chart, pane.chart);
            attachCandleTooltip(chartType, chart, pane.chart, response.data);
        } catch (error) {
            console.error('[chart-dashboard] render failed for', chartType, error);
            destroyPaneChart(chartType);
            renderPlaceholderChart(chartType, response);
        }
    }

    function renderPlaceholderChart(chartType, response) {
        const pane = els.panes[chartType];
        if (!pane || !pane.chart) return;

        destroyPaneChart(chartType);

        const candles = response.data || [];
        const first = candles[0] || null;
        const last = candles.length ? candles[candles.length - 1] : null;

        const details = [
            ['Candles', candles.length],
            ['First Candle', first && first.time ? first.time : '-'],
            ['Last Candle', last && last.time ? last.time : '-'],
            ['Last Close', last && last.close != null ? last.close : '-']
        ];

        if (response.expiryDate) {
            details.push(['Expiry', response.expiryDate]);
        }
        if (response.atmStrike != null) {
            details.push(['ATM Strike', response.atmStrike]);
        }

        const rows = details.map(([label, value]) =>
            '<tr><td>' + escapeHtml(String(label)) + '</td><td>' + escapeHtml(String(value)) + '</td></tr>'
        ).join('');

        pane.chart.innerHTML =
            '<div class="chart-placeholder-summary">' +
                '<div class="chart-placeholder-title">' + escapeHtml(chartTypeLabel(chartType)) + ' Summary</div>' +
                '<table class="kv-table"><tbody>' + rows + '</tbody></table>' +
            '</div>';

        state.charts[chartType] = { chart: null, container: pane.chart, fallback: true };
    }

    /**
     * A pane's display name, used by both the heading and the fallback summary
     * so the two cannot disagree.
     *
     * <p>"ATM" is only honest while the picker is on auto — once a strike is
     * chosen explicitly the name has to carry it instead. A pinned pane appends
     * its timeframe, since several option panes otherwise share a name and only
     * the badge tells them apart; an averaged pane appends its ladder width for
     * the same reason.</p>
     */
    function chartTypeLabel(chartType) {
        const series = seriesOf(chartType);
        if (series === CHART_TYPES.UNDERLYING) return state.indexSymbol || DEFAULT_INDEX;

        let label = state.strike ? series + ' ' + state.strike : 'ATM ' + series;
        const span = strikeSpanOf(chartType);
        if (span > 0) {
            label += ' ±' + span + ' avg';
        }
        if (isPinned(chartType)) {
            label += ' · ' + timeframeOf(chartType);
        }
        return label;
    }

    function setPaneLoading(chartType, visible) {
        const pane = els.panes[chartType];
        if (!pane || !pane.loading) return;
        pane.loading.style.display = visible ? '' : 'none';
        const root = getPaneRoot(chartType);
        if (root) root.classList.toggle('is-loading', visible);
    }

    function setPaneError(chartType, visible, message) {
        const pane = els.panes[chartType];
        if (!pane || !pane.error) return;
        pane.error.style.display = visible ? '' : 'none';
        if (visible && message) {
            pane.error.textContent = message;
        }
    }

    function setPaneEmpty(chartType, visible, message) {
        const pane = els.panes[chartType];
        if (!pane || !pane.empty) return;
        pane.empty.style.display = visible ? '' : 'none';
        if (visible && message) {
            pane.empty.textContent = message;
        }
    }

    function createPaneChart(container) {
        container.innerHTML = '';

        const size = getChartSize(container);
        return window.LightweightCharts.createChart(container, {
            width: size.width,
            height: size.height,
            layout: {
                background: { color: '#ffffff' },
                textColor: '#54606e',
                fontFamily: 'Segoe UI, sans-serif'
            },
            localization: {
                locale: 'en-IN',
                timeFormatter: formatChartDateTime
            },
            grid: {
                vertLines: { color: '#edf1f5' },
                horzLines: { color: '#edf1f5' }
            },
            crosshair: {
                mode: window.LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    color: '#9aa5b1',
                    labelBackgroundColor: '#1f2933'
                },
                horzLine: {
                    color: '#9aa5b1',
                    labelBackgroundColor: '#1f2933'
                }
            },
            rightPriceScale: {
                borderColor: '#e5eaf0',
                scaleMargins: { top: 0.1, bottom: 0.1 }
            },
            timeScale: {
                borderColor: '#e5eaf0',
                timeVisible: true,
                secondsVisible: false,
                tickMarkFormatter: formatChartTickMark
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: false
            },
            handleScale: {
                axisPressedMouseMove: true,
                mouseWheel: true,
                pinch: true
            }
        });
    }

    function mapCandlestickData(candles) {
        return [...candles]
            .sort(compareCandlesByTime)
            .map(candle => ({
                time: toChartTime(candle.time),
                open: toNumber(candle.open),
                high: toNumber(candle.high),
                low: toNumber(candle.low),
                close: toNumber(candle.close)
            }));
    }

    function mapSmaData(candles, fields) {
        return [...candles]
            .sort(compareCandlesByTime)
            .map(candle => ({
                time: toChartTime(candle.time),
                value: getSmaValue(candle, fields)
            }))
            .filter(point => point.time != null && Number.isFinite(point.value));
    }

    /**
     * What SuperTrend is saying at the right-hand edge of the chart: {@code true}
     * for buy, {@code false} for sell, {@code null} while the ATR is still warming
     * up and there is no reading at all.
     *
     * <p>Walks back from the newest bar rather than reading the last element
     * outright, so trailing warm-up or gap bars cannot report "no signal" on a
     * series that plainly has one.</p>
     */
    function latestSupertrendDirection(response) {
        if (!response || !Array.isArray(response.data)) return null;
        for (let i = response.data.length - 1; i >= 0; i--) {
            const direction = response.data[i][SUPERTREND_CONFIG.directionField];
            if (direction != null) return direction === true;
        }
        return null;
    }

    /**
     * SuperTrend: one line series whose colour changes at each flip.
     *
     * <p>{@code LineData.color} overrides the series colour per point in
     * lightweight-charts v4, so the band is a single continuous series carrying
     * green points while the trend is up and red while it is down.</p>
     *
     * <p>This replaced a two-series design — one green series and one red, each
     * holding whitespace for the other's bars — which was meant to interleave
     * into one colour-changing line and instead rendered as <b>two separate
     * lines drawn at once</b>. One series makes that failure structurally
     * impossible: there is only ever one line to draw.</p>
     */
    function renderSupertrend(chart, candles) {
        if (!Array.isArray(candles) || !candles.length) return;

        const points = [];
        let hasReading = false;

        [...candles].sort(compareCandlesByTime).forEach(candle => {
            const time = toChartTime(candle.time);
            if (time == null) return;

            const value = toNumber(candle[SUPERTREND_CONFIG.field]);
            const isUp = candle[SUPERTREND_CONFIG.directionField];

            // Genuine whitespace: the warm-up bars before the ATR has enough
            // history to produce a band at all.
            if (!Number.isFinite(value) || isUp == null) {
                points.push({ time });
                return;
            }

            points.push({
                time: time,
                value: value,
                color: isUp === true ? SUPERTREND_CONFIG.upColor : SUPERTREND_CONFIG.downColor
            });
            hasReading = true;
        });

        if (!hasReading) return;

        const series = chart.addLineSeries({
            // Only a fallback for a point that somehow carries no colour of its
            // own; every point above sets one.
            color: SUPERTREND_CONFIG.downColor,
            lineWidth: SUPERTREND_CONFIG.lineWidth,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            lineStyle: window.LightweightCharts.LineStyle.Solid
        });
        series.setData(points);
    }

    /**
     * Kite-style click readout: O/H/L/C plus every SMA value behind the clicked
     * candle. Click a candle to pin the readout; click it again, click empty
     * plot area, or press Escape to dismiss it.
     *
     * <p>Pinning rather than tracking the pointer is the point of the gesture -
     * the numbers stay put while you read across the panes, and each pane
     * holds its own pin so an underlying candle and its CE / PE counterparts can
     * be compared side by side.</p>
     *
     * <p>The candle is looked up in the API payload by click time rather than
     * read out of {@code param.seriesData}. seriesData only carries what was
     * actually drawn, so the SMA highs would drop out of the readout whenever
     * the smaHigh overlay is off - and the values a strategy gated on are
     * exactly the ones worth seeing.</p>
     */
    function attachCandleTooltip(chartType, chart, container, candles) {
        if (!container || !Array.isArray(candles) || !candles.length) return;

        const byTime = new Map();
        candles.forEach(candle => {
            const time = toChartTime(candle.time);
            if (time != null) byTime.set(time, candle);
        });
        if (!byTime.size) return;

        const tooltip = document.createElement('div');
        tooltip.className = 'chart-tooltip';
        tooltip.style.display = 'none';
        container.appendChild(tooltip);

        let pinnedTime = null;

        // Reports whether anything was actually dismissed, so Escape can fall
        // through to the fullscreen toggle when no readout is open.
        const hide = () => {
            if (tooltip.style.display === 'none') return false;
            pinnedTime = null;
            tooltip.style.display = 'none';
            return true;
        };

        chart.subscribeClick(param => {
            const point = param ? param.point : null;
            const candle = param && param.time != null ? byTime.get(param.time) : null;

            // A click on empty plot area reports a null time, or a point outside
            // the canvas - either way it means "dismiss".
            if (!candle || !point ||
                point.x < 0 || point.y < 0 ||
                point.x > container.clientWidth || point.y > container.clientHeight) {
                hide();
                return;
            }

            // Clicking the pinned candle again toggles the readout off, so one
            // gesture both opens and closes it.
            if (pinnedTime === param.time) {
                hide();
                return;
            }

            pinnedTime = param.time;
            tooltip.innerHTML = buildTooltipHtml(candle);
            tooltip.style.display = '';
            positionTooltip(tooltip, container, point);
        });

        // Exposed so Escape can dismiss a pin. No teardown hook is needed - the
        // tooltip node is a child of the container renderChart wipes, and the
        // click subscription dies with the chart.
        const entry = state.charts[chartType];
        if (entry) {
            entry.hideTooltip = hide;
        }
    }

    /** Dismisses every pinned readout. True if at least one was open. */
    function hideAllTooltips() {
        let dismissed = false;
        Object.keys(CHART_TYPES).forEach(key => {
            const entry = state.charts[CHART_TYPES[key]];
            if (entry && typeof entry.hideTooltip === 'function' && entry.hideTooltip()) {
                dismissed = true;
            }
        });
        return dismissed;
    }

    function buildTooltipHtml(candle) {
        const open = toNumber(candle.open);
        const close = toNumber(candle.close);
        const bothPrices = Number.isFinite(open) && Number.isFinite(close);
        const directionClass = bothPrices ? (close >= open ? 'is-up' : 'is-down') : '';

        let html = '<div class="chart-tooltip-time">' +
            escapeHtml(formatChartDateTime(toChartTime(candle.time))) + '</div>';

        html += '<div class="chart-tooltip-ohlc">' +
            tooltipOhlcCell('O', candle.open, '') +
            tooltipOhlcCell('H', candle.high, '') +
            tooltipOhlcCell('L', candle.low, '') +
            tooltipOhlcCell('C', candle.close, directionClass) +
            '</div>';

        if (bothPrices) {
            const diff = close - open;
            const pct = open !== 0 ? (diff / open) * 100 : null;
            html += '<div class="chart-tooltip-change ' + directionClass + '">' +
                escapeHtml((diff >= 0 ? '+' : '') + formatPrice(diff) +
                    (pct == null ? '' : ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%)')) +
                '</div>';
        }

        const lines = [];
        state.smaPeriods.forEach(period => {
            const config = SMA_CONFIG[period];
            if (!config) return;

            const low = getSmaValue(candle, config.lowFields);
            const high = getSmaValue(candle, config.highFields);
            if (!Number.isFinite(low) && !Number.isFinite(high)) return;

            // Mirrors the legend: the low half is always named because that is
            // what the strategy gates on; the high half only when it is drawn.
            let value = 'L ' + formatPrice(low);
            if (showSmaHigh() && Number.isFinite(high)) {
                value += '   H ' + formatPrice(high);
            }

            lines.push(tooltipLineRow(config.color, 'SMA ' + period, value));
        });

        if (showSupertrend()) {
            const supertrend = toNumber(candle[SUPERTREND_CONFIG.field]);
            if (Number.isFinite(supertrend)) {
                const isUp = candle[SUPERTREND_CONFIG.directionField] === true;
                lines.push(tooltipLineRow(
                    isUp ? SUPERTREND_CONFIG.upColor : SUPERTREND_CONFIG.downColor,
                    SUPERTREND_CONFIG.label,
                    formatPrice(supertrend) + '   ' + (isUp ? 'UP' : 'DOWN')
                ));
            }
        }

        if (lines.length) {
            html += '<div class="chart-tooltip-lines">' + lines.join('') + '</div>';
        }

        return html;
    }

    function tooltipOhlcCell(label, value, extraClass) {
        return '<span class="chart-tooltip-ohlc-cell ' + extraClass + '">' +
            '<span class="chart-tooltip-ohlc-label">' + label + '</span>' +
            '<span class="chart-tooltip-ohlc-value">' + escapeHtml(formatPrice(value)) + '</span>' +
            '</span>';
    }

    function tooltipLineRow(color, label, value) {
        return '<div class="chart-tooltip-row">' +
            '<span class="chart-tooltip-swatch" style="color:' + escapeHtml(color) + '"></span>' +
            '<span class="chart-tooltip-label">' + escapeHtml(label) + '</span>' +
            '<span class="chart-tooltip-value">' + escapeHtml(value) + '</span>' +
            '</div>';
    }

    /**
     * Keeps the tooltip beside the cursor and fully inside the pane - flipping
     * to the other side of the crosshair when it would run past an edge.
     * .chart-canvas clips its overflow, so an unclamped tooltip near the right
     * or bottom edge would be cut in half rather than simply spilling out.
     */
    function positionTooltip(tooltip, container, point) {
        const margin = 12;
        const width = tooltip.offsetWidth;
        const height = tooltip.offsetHeight;

        let left = point.x + margin;
        if (left + width > container.clientWidth - margin) {
            left = point.x - width - margin;
        }

        let top = point.y + margin;
        if (top + height > container.clientHeight - margin) {
            top = point.y - height - margin;
        }

        tooltip.style.left = clampToPane(left, width, container.clientWidth, margin) + 'px';
        tooltip.style.top = clampToPane(top, height, container.clientHeight, margin) + 'px';
    }

    function clampToPane(value, size, available, margin) {
        const max = Math.max(margin, available - size - margin);
        return Math.max(margin, Math.min(value, max));
    }

    function formatPrice(value) {
        const num = toNumber(value);
        return Number.isFinite(num) ? priceFormatter.format(num) : '-';
    }

    function compareCandlesByTime(left, right) {
        const leftTime = toChartTime(left.time);
        const rightTime = toChartTime(right.time);
        return leftTime - rightTime;
    }

    /**
     * Points the viewport at the selected date, with the rest of the 45-day
     * window sitting off-screen to the left for the user to scroll back to.
     *
     * <p>The window exists so the SMAs are warm and the recent past is one drag
     * away — not so that six weeks can be squeezed into one pane. Fitting all of
     * it made the selected session a few pixels wide, which is the thing this
     * function exists to prevent.</p>
     *
     * <p>Matched on the raw ISO string's date prefix rather than by converting
     * the epoch seconds back to a calendar day: the API already returns
     * {@code +05:30} timestamps, so a prefix compare is exactly the market's own
     * session boundary and needs no timezone arithmetic to get wrong.</p>
     *
     * <p>Falls back to {@code fitContent()} when the selected date has no bars in
     * this series — a holiday, or an option leg that had not started trading yet.
     * Showing the whole window is a worse view but an honest one; an empty
     * viewport would just look broken.</p>
     */
    function focusSelectedSession(chart, candles) {
        const timeScale = chart.timeScale();
        const times = (candles || [])
            .filter(candle => String(candle && candle.time || '').startsWith(state.date))
            .map(candle => toChartTime(candle.time))
            .filter(time => time != null);

        if (times.length < 2) {
            timeScale.fitContent();
            return;
        }

        const from = Math.min.apply(null, times);
        const to = Math.max.apply(null, times);
        if (!(to > from)) {
            timeScale.fitContent();
            return;
        }
        timeScale.setVisibleRange({ from: from, to: to });
    }

    /**
     * Resizes a pane without moving the viewport.
     *
     * <p>Both callers used to {@code fitContent()} here, which re-fitted to the
     * whole 45-day window on every resize and every fullscreen toggle — undoing
     * the session focus and discarding wherever the user had scrolled to. Keeping
     * the logical range means the same bars stay on screen and simply get more
     * room.</p>
     */
    /**
     * One + / - step on a pane, zooming about the centre of what is on screen.
     *
     * <p>Centre rather than the right edge: the buttons sit beside a chart the
     * user has usually already scrolled to a particular bar, and anchoring to the
     * edge would slide that bar out of view on every click.</p>
     *
     * <p>Works on the logical range (bar indices) rather than {@code barSpacing},
     * so it composes with {@code focusSelectedSession} and the resize handler —
     * all three speak the same units.</p>
     */
    function zoomChart(chartType, factor) {
        const current = state.charts[chartType];
        if (!current || !current.chart) return;

        const timeScale = current.chart.timeScale();
        const range = timeScale.getVisibleLogicalRange();
        if (!range) return;

        const centre = (range.from + range.to) / 2;
        let half = ((range.to - range.from) / 2) * factor;
        half = Math.min(Math.max(half, MIN_VISIBLE_BARS / 2), MAX_VISIBLE_BARS / 2);

        timeScale.setVisibleLogicalRange({ from: centre - half, to: centre + half });
    }

    /**
     * Guard against the obvious feedback loop: every {@code setVisibleRange} below
     * makes that chart fire its own range-changed event, which would come back
     * here and re-broadcast forever.
     */
    let syncingRanges = false;

    /**
     * Mirrors one pane's visible window onto the other six.
     *
     * <p><b>Time range, not logical range.</b> The panes no longer share a
     * timeframe — bar 40 of a 5-minute series and bar 40 of a 15-minute series are
     * three quarters of an hour apart — so syncing bar indices would drift the
     * pinned rows out of alignment with the top ones. Wall-clock times mean the
     * same instant on every pane whatever its bucket size, which is the whole
     * point of showing three horizons at once.</p>
     *
     * <p>Each {@code setVisibleRange} is guarded: a range can fall entirely
     * outside a given pane's data — an option leg that had not started trading
     * yet — and lightweight-charts throws rather than clamping. One pane refusing
     * a window must not stop the rest from following.</p>
     */
    function broadcastVisibleRange(sourceKey, range) {
        if (syncingRanges || !range) return;
        syncingRanges = true;
        try {
            PANE_KEYS.forEach(paneKey => {
                if (paneKey === sourceKey) return;
                const entry = state.charts[paneKey];
                if (!entry || !entry.chart) return;
                try {
                    entry.chart.timeScale().setVisibleRange(range);
                } catch (error) {
                    // This pane cannot show that window; the others still can.
                }
            });
        } finally {
            syncingRanges = false;
        }
    }

    /**
     * Makes a pane a sync source. Covers every way the window can move — the
     * +/- buttons, the mouse wheel, a drag — because all of them end in the same
     * range-changed event.
     */
    function attachRangeSync(chartType, chart) {
        chart.timeScale().subscribeVisibleTimeRangeChange(range => {
            broadcastVisibleRange(chartType, range);
        });
    }

    function applyChartSize(chart, container) {
        const timeScale = chart.timeScale();
        const range = timeScale.getVisibleLogicalRange();
        const size = getChartSize(container);
        chart.applyOptions({ width: size.width, height: size.height });
        if (range) {
            timeScale.setVisibleLogicalRange(range);
        }
    }

    function toChartTime(value) {
        const parsed = Date.parse(value);
        if (Number.isNaN(parsed)) {
            return null;
        }

        return Math.floor(parsed / 1000);
    }

    function toNumber(value) {
        return typeof value === 'number' ? value : Number(value);
    }

    function getSmaValue(candle, fields) {
        if (!candle || !Array.isArray(fields)) {
            return null;
        }

        for (const field of fields) {
            const rawValue = candle[field];
            if (rawValue == null) {
                continue;
            }

            const value = toNumber(rawValue);
            if (Number.isFinite(value)) {
                return value;
            }
        }

        return null;
    }

    function formatChartTickMark(time) {
        const date = toDateFromChartTime(time);
        return date ? timeLabelFormatter.format(date) : '';
    }

    function formatChartDateTime(time) {
        const date = toDateFromChartTime(time);
        return date ? dateTimeLabelFormatter.format(date) : '';
    }

    function toDateFromChartTime(time) {
        if (typeof time === 'number') {
            return new Date(time * 1000);
        }

        if (time && typeof time === 'object' && 'year' in time && 'month' in time && 'day' in time) {
            return new Date(Date.UTC(time.year, time.month - 1, time.day));
        }

        return null;
    }

    function attachResizeHandler(chartType, chart, container) {
        const resize = () => {
            applyChartSize(chart, container);
        };

        if (typeof ResizeObserver === 'function') {
            const observer = new ResizeObserver(() => resize());
            observer.observe(container);
            state.charts[chartType] = {
                chart: chart,
                container: container,
                resizeObserver: observer,
                resizeHandler: resize,
                fallback: false
            };
            return;
        }

        window.addEventListener('resize', resize);
        state.charts[chartType] = {
            chart: chart,
            container: container,
            resizeHandler: resize,
            fallback: false
        };
    }

    function destroyPaneChart(chartType) {
        const current = state.charts[chartType];
        const pane = els.panes[chartType];

        if (current) {
            if (current.resizeObserver) {
                current.resizeObserver.disconnect();
            }
            if (current.resizeHandler) {
                window.removeEventListener('resize', current.resizeHandler);
            }
            if (current.chart && typeof current.chart.remove === 'function') {
                current.chart.remove();
            }
        }

        if (pane && pane.chart) {
            pane.chart.innerHTML = '';
        }

        state.charts[chartType] = null;
    }

    function getChartSize(container) {
        const width = Math.max(container.clientWidth || 0, 280);
        const height = Math.max(container.clientHeight || 0, CHART_HEIGHT_FALLBACK);
        return { width: width, height: height };
    }

    /**
     * The pane's root <article>. Ids follow the key: PE -> pePane,
     * PE_15M -> pe15mPane — derived rather than listed so a new pane needs no
     * edit here.
     */
    function getPaneRoot(chartType) {
        return document.getElementById(paneIdPrefix(chartType) + 'Pane');
    }

    /** camelCase element-id prefix for a pane key: PE_15M -> "pe15m". */
    function paneIdPrefix(paneKey) {
        return String(paneKey).toLowerCase().replace(/_(.)/g, (m, c) => c.toUpperCase());
    }

    function stepDate(days) {
        if (!els.date || !els.date.value) return;
        const date = parseDateInput(els.date.value);
        if (!date) return;
        date.setDate(date.getDate() + days);
        els.date.value = localDateString(date);
        onFiltersChanged();
    }

    function setToday() {
        if (!els.date) return;
        els.date.value = localDateString(new Date());
        onFiltersChanged();
    }

    function toggleFullscreenMode() {
        document.body.classList.toggle('chart-fullscreen');
        if (els.fullscreenBtn) {
            els.fullscreenBtn.textContent = document.body.classList.contains('chart-fullscreen')
                ? 'Exit Fullscreen'
                : 'Fullscreen';
        }
        setTimeout(resizeVisibleCharts, 40);
    }

    function resizeVisibleCharts() {
        Object.keys(CHART_TYPES).forEach(key => {
            const chartType = CHART_TYPES[key];
            const current = state.charts[chartType];
            if (!current || !current.chart || !current.container) return;
            applyChartSize(current.chart, current.container);
        });
    }

    function onKeyboardShortcut(event) {
        const target = event.target;
        const tagName = target && target.tagName ? target.tagName.toLowerCase() : '';
        const isTyping = tagName === 'input' || tagName === 'select' || tagName === 'textarea';

        // Layered Escape: clear pinned readouts first, leave fullscreen only
        // once there are none left to clear.
        if (event.key === 'Escape' && hideAllTooltips()) {
            event.preventDefault();
            return;
        }

        if (event.key === 'Escape' && document.body.classList.contains('chart-fullscreen')) {
            event.preventDefault();
            toggleFullscreenMode();
            return;
        }

        if (isTyping || event.ctrlKey || event.metaKey || event.altKey) {
            return;
        }

        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            stepDate(-1);
            return;
        }
        if (event.key === 'ArrowRight') {
            event.preventDefault();
            stepDate(1);
            return;
        }
        if (event.key && event.key.toLowerCase() === 'r') {
            event.preventDefault();
            refreshAllCharts();
            return;
        }

        // 1/2/3 now *pick* the timeframe rather than switching between several
        // loaded ones. Under the old multi-select group this checked
        // state.timeframes.includes(...), which since the group went
        // single-select would have made two of the three keys silently dead.
        const timeframeByKey = { 1: '5m', 2: '10m', 3: '15m' };
        const timeframe = timeframeByKey[event.key];
        if (timeframe && els.timeframes &&
            els.timeframes.querySelector('.chart-chip[data-value="' + timeframe + '"]')) {
            event.preventDefault();
            setMultiSelectValues(els.timeframes, [timeframe]);
            onFiltersChanged();
        }
    }

    function persistState() {
        try {
            localStorage.setItem(LS_KEYS.date, state.date || '');
            // Both were written by earlier versions of this page (a from-date
            // string, then the toggle). Neither has a control any more, so drop
            // them rather than leaving dead entries in every returning browser.
            localStorage.removeItem(LS_PREFIX + 'continuous');
            localStorage.removeItem(LS_PREFIX + 'fromDate');
            localStorage.setItem(LS_KEYS.dataSource, state.dataSource || DEFAULT_DATA_SOURCE);
            localStorage.setItem(LS_KEYS.indexSymbol, state.indexSymbol || DEFAULT_INDEX);
            localStorage.setItem(LS_KEYS.timeframes, JSON.stringify(state.timeframes || [DEFAULT_TIMEFRAME]));
            localStorage.setItem(LS_KEYS.smaPeriods, JSON.stringify(state.smaPeriods || DEFAULT_SMA_PERIODS));
            localStorage.setItem(LS_KEYS.activeTimeframe, state.activeTimeframe || DEFAULT_TIMEFRAME);
            localStorage.setItem(LS_KEYS.strike, state.strike || '');
            localStorage.setItem(LS_KEYS.overlays, JSON.stringify(state.overlays || []));
        } catch (e) {
            // localStorage can be disabled; the dashboard still works for this session.
        }
    }

    function readStoredValue(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            return null;
        }
    }

    function readStoredList(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return [...fallback];
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) && parsed.length ? parsed.map(String) : [...fallback];
        } catch (e) {
            return [...fallback];
        }
    }

    function parseDateInput(value) {
        if (!value) return null;
        const parts = value.split('-').map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }

    /** The continuous window's start: CONTINUOUS_LOOKBACK_DAYS before the to-date. */
    function continuousFromDate(toDateValue) {
        const toDate = parseDateInput(toDateValue);
        if (!toDate) return '';
        toDate.setDate(toDate.getDate() - CONTINUOUS_LOOKBACK_DAYS);
        return localDateString(toDate);
    }

    function localDateString(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return year + '-' + month + '-' + day;
    }

    function escapeHtml(value) {
        return value
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    init();
})();
