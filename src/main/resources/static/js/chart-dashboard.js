(function () {
    const DEFAULT_INDEX = 'NIFTY';
    const DEFAULT_DATA_SOURCE = 'HISTORICAL_ICICI';
    const DEFAULT_TIMEFRAME = '5m';
    const DEFAULT_SMA_PERIODS = ['20', '50', '100', '200', '500'];
    const NO_DATA_MESSAGE = 'No market data available for selected date.';
    const CHART_HEIGHT_FALLBACK = 360;
    const MARKET_TIMEZONE = 'Asia/Kolkata';
    const LS_PREFIX = 'mm.chartDashboard.';
    const LS_KEYS = {
        date: LS_PREFIX + 'date',
        dataSource: LS_PREFIX + 'dataSource',
        indexSymbol: LS_PREFIX + 'indexSymbol',
        timeframes: LS_PREFIX + 'timeframes',
        smaPeriods: LS_PREFIX + 'smaPeriods',
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

    const CHART_TYPES = {
        PE: 'PE',
        UNDERLYING: 'UNDERLYING',
        CE: 'CE'
    };

    const state = {
        date: '',
        dataSource: DEFAULT_DATA_SOURCE,
        indexSymbol: DEFAULT_INDEX,
        timeframes: [DEFAULT_TIMEFRAME],
        smaPeriods: [...DEFAULT_SMA_PERIODS],
        activeTimeframe: DEFAULT_TIMEFRAME,
        responses: {
            PE: new Map(),
            UNDERLYING: new Map(),
            CE: new Map()
        },
        charts: {
            PE: null,
            UNDERLYING: null,
            CE: null
        },
        controllers: {
            PE: null,
            UNDERLYING: null,
            CE: null
        }
    };

    const els = {
        date: document.getElementById('chartDate'),
        dataSource: document.getElementById('chartDataSource'),
        indexSymbol: document.getElementById('chartIndexSymbol'),
        timeframes: document.getElementById('chartTimeframes'),
        smaPeriods: document.getElementById('chartSmaPeriods'),
        refreshBtn: document.getElementById('refreshChartsBtn'),
        prevDateBtn: document.getElementById('prevDateBtn'),
        nextDateBtn: document.getElementById('nextDateBtn'),
        todayDateBtn: document.getElementById('todayDateBtn'),
        fullscreenBtn: document.getElementById('fullscreenChartsBtn'),

        panes: {
            PE: {
                title: null,
                activeBadge: document.getElementById('peActiveTimeframe'),
                selectedDate: document.getElementById('peSelectedDate'),
                selectedIndex: document.getElementById('peSelectedIndex'),
                selectedTimeframe: document.getElementById('peSelectedTimeframe'),
                expiryDate: document.getElementById('peExpiryDate'),
                atmStrike: document.getElementById('peAtmStrike'),
                tabs: document.getElementById('peTimeframeTabs'),
                legend: document.getElementById('peSmaLegend'),
                loading: document.getElementById('peLoadingState'),
                error: document.getElementById('peErrorState'),
                empty: document.getElementById('peNoDataState'),
                chart: document.getElementById('peChart')
            },
            UNDERLYING: {
                title: document.getElementById('underlyingPaneTitle'),
                activeBadge: document.getElementById('underlyingActiveTimeframe'),
                selectedDate: document.getElementById('underlyingSelectedDate'),
                selectedIndex: document.getElementById('underlyingSelectedIndex'),
                selectedTimeframe: document.getElementById('underlyingSelectedTimeframe'),
                expiryDate: null,
                atmStrike: null,
                tabs: document.getElementById('underlyingTimeframeTabs'),
                legend: document.getElementById('underlyingSmaLegend'),
                loading: document.getElementById('underlyingLoadingState'),
                error: document.getElementById('underlyingErrorState'),
                empty: document.getElementById('underlyingNoDataState'),
                chart: document.getElementById('underlyingChart')
            },
            CE: {
                title: null,
                activeBadge: document.getElementById('ceActiveTimeframe'),
                selectedDate: document.getElementById('ceSelectedDate'),
                selectedIndex: document.getElementById('ceSelectedIndex'),
                selectedTimeframe: document.getElementById('ceSelectedTimeframe'),
                expiryDate: document.getElementById('ceExpiryDate'),
                atmStrike: document.getElementById('ceAtmStrike'),
                tabs: document.getElementById('ceTimeframeTabs'),
                legend: document.getElementById('ceSmaLegend'),
                loading: document.getElementById('ceLoadingState'),
                error: document.getElementById('ceErrorState'),
                empty: document.getElementById('ceNoDataState'),
                chart: document.getElementById('ceChart')
            }
        }
    };

    function init() {
        hydrateDefaults();
        bindEvents();
        updateStateFromControls();
        renderTimeframeTabs();
        renderSmaLegends();
        renderAllPanesInstruction();
        if (state.date) {
            refreshAllCharts();
        }
    }

    function hydrateDefaults() {
        const storedDate = readStoredValue(LS_KEYS.date);
        const storedDataSource = readStoredValue(LS_KEYS.dataSource);
        const storedIndex = readStoredValue(LS_KEYS.indexSymbol);
        const storedTimeframes = readStoredList(LS_KEYS.timeframes, [DEFAULT_TIMEFRAME]);
        const storedSmaPeriods = readStoredList(LS_KEYS.smaPeriods, DEFAULT_SMA_PERIODS);
        const storedActiveTimeframe = readStoredValue(LS_KEYS.activeTimeframe);

        if (els.indexSymbol) {
            els.indexSymbol.value = storedIndex || els.indexSymbol.value || DEFAULT_INDEX;
        }
        if (els.dataSource) {
            els.dataSource.value = storedDataSource || els.dataSource.value || DEFAULT_DATA_SOURCE;
        }

        setMultiSelectValues(els.timeframes, storedTimeframes);
        setMultiSelectValues(els.smaPeriods, storedSmaPeriods);
        if (storedActiveTimeframe) {
            state.activeTimeframe = storedActiveTimeframe;
        }

        if (els.date && !els.date.value) {
            els.date.value = storedDate || localDateString(new Date());
        }
    }

    function bindEvents() {
        if (els.date) els.date.addEventListener('change', onFiltersChanged);
        if (els.dataSource) els.dataSource.addEventListener('change', onFiltersChanged);
        if (els.indexSymbol) els.indexSymbol.addEventListener('change', onFiltersChanged);
        bindChipGroup(els.timeframes, onFiltersChanged);
        bindChipGroup(els.smaPeriods, onFiltersChanged);
        if (els.refreshBtn) els.refreshBtn.addEventListener('click', refreshAllCharts);
        if (els.prevDateBtn) els.prevDateBtn.addEventListener('click', () => stepDate(-1));
        if (els.nextDateBtn) els.nextDateBtn.addEventListener('click', () => stepDate(1));
        if (els.todayDateBtn) els.todayDateBtn.addEventListener('click', setToday);
        if (els.fullscreenBtn) els.fullscreenBtn.addEventListener('click', toggleFullscreenMode);
        document.addEventListener('keydown', onKeyboardShortcut);
    }

    function bindChipGroup(group, callback) {
        if (!group) return;
        Array.from(group.querySelectorAll('.chart-chip')).forEach(button => {
            button.setAttribute('aria-pressed', button.classList.contains('is-selected') ? 'true' : 'false');
            button.addEventListener('click', () => {
                button.classList.toggle('is-selected');
                if (!group.querySelector('.chart-chip.is-selected')) {
                    button.classList.add('is-selected');
                }
                Array.from(group.querySelectorAll('.chart-chip')).forEach(chip => {
                    chip.setAttribute('aria-pressed', chip.classList.contains('is-selected') ? 'true' : 'false');
                });
                callback();
            });
        });
    }

    function onFiltersChanged() {
        updateStateFromControls();
        normalizeActiveTimeframe();
        persistState();
        renderTimeframeTabs();
        renderSmaLegends();
        refreshAllCharts();
    }

    function updateStateFromControls() {
        state.date = els.date ? els.date.value : '';
        state.dataSource = els.dataSource && els.dataSource.value ? els.dataSource.value : DEFAULT_DATA_SOURCE;
        state.indexSymbol = els.indexSymbol && els.indexSymbol.value ? els.indexSymbol.value : DEFAULT_INDEX;
        state.timeframes = getSelectedValues(els.timeframes, [DEFAULT_TIMEFRAME]);
        state.smaPeriods = getSelectedValues(els.smaPeriods, DEFAULT_SMA_PERIODS);
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
        fetchPaneData(CHART_TYPES.PE);
        fetchPaneData(CHART_TYPES.UNDERLYING);
        fetchPaneData(CHART_TYPES.CE);
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

        const requests = state.timeframes.map(timeframe =>
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
                renderTimeframeTabs();
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
            chartType: chartType,
            timeframe: timeframe,
            smaPeriods: state.smaPeriods.join(',')
        });

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
        const response = state.responses[chartType].get(state.activeTimeframe);

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

        if (pane.title && chartType === CHART_TYPES.UNDERLYING) {
            pane.title.textContent = state.indexSymbol || DEFAULT_INDEX;
        }
        if (pane.activeBadge) pane.activeBadge.textContent = state.activeTimeframe;
        if (pane.selectedDate) pane.selectedDate.textContent = state.date || '-';
        if (pane.selectedIndex) pane.selectedIndex.textContent = state.indexSymbol || DEFAULT_INDEX;
        if (pane.selectedTimeframe) pane.selectedTimeframe.textContent = state.activeTimeframe;
        if (pane.expiryDate) pane.expiryDate.textContent = response && response.expiryDate ? response.expiryDate : '-';
        if (pane.atmStrike) pane.atmStrike.textContent = response && response.atmStrike != null ? response.atmStrike : '-';
    }

    function renderTimeframeTabs() {
        Object.keys(CHART_TYPES).forEach(key => {
            const chartType = CHART_TYPES[key];
            const pane = els.panes[chartType];
            if (!pane || !pane.tabs) return;

            pane.tabs.innerHTML = '';
            state.timeframes.forEach(timeframe => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-ghost chart-timeframe-tab' +
                    (timeframe === state.activeTimeframe ? ' is-active' : '');
                btn.textContent = timeframe;
                btn.dataset.timeframe = timeframe;
                btn.addEventListener('click', () => {
                    if (state.activeTimeframe === timeframe) return;
                    state.activeTimeframe = timeframe;
                    persistState();
                    renderTimeframeTabs();
                    renderVisiblePanes();
                });
                pane.tabs.appendChild(btn);
            });
        });
    }

    function renderVisiblePanes() {
        renderPane(CHART_TYPES.PE);
        renderPane(CHART_TYPES.UNDERLYING);
        renderPane(CHART_TYPES.CE);
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
                // One entry per period: the low and high lines share this colour.
                item.innerHTML =
                    '<span class="chart-sma-legend-swatch"></span>' +
                    '<span>SMA ' + escapeHtml(String(period)) + ' H/L</span>';
                pane.legend.appendChild(item);
            });

            const supertrendItem = document.createElement('span');
            supertrendItem.className = 'chart-sma-legend-item';
            supertrendItem.style.color = SUPERTREND_CONFIG.upColor;
            supertrendItem.innerHTML =
                '<span class="chart-sma-legend-swatch"></span>' +
                '<span style="color:' + SUPERTREND_CONFIG.downColor + '">' +
                '<span class="chart-sma-legend-swatch"></span></span>' +
                '<span>' + escapeHtml(SUPERTREND_CONFIG.label) + '</span>';
            pane.legend.appendChild(supertrendItem);
        });
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

            state.smaPeriods.forEach(period => {
                const config = SMA_CONFIG[period];
                if (!config) return;

                // Low and high share the colour and the styling — the pair is
                // meant to read as one band per period.
                [config.lowFields, config.highFields].forEach(fields => {
                    const lineData = mapSmaData(response.data, fields);
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

            renderSupertrend(chart, response.data);

            chart.timeScale().fitContent();
            attachResizeHandler(chartType, chart, pane.chart);
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

    function chartTypeLabel(chartType) {
        if (chartType === CHART_TYPES.PE) return 'ATM PE';
        if (chartType === CHART_TYPES.CE) return 'ATM CE';
        return state.indexSymbol || DEFAULT_INDEX;
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
     * SuperTrend is one line that changes colour when the trend flips, which a
     * single lightweight-charts line series cannot express. So it is drawn as two
     * series — one green, one red — where each carries whitespace points
     * ({time} with no value) for the bars belonging to the other. Whitespace
     * breaks the line instead of connecting across it, so the two series
     * interleave into what looks like one colour-changing line.
     */
    function renderSupertrend(chart, candles) {
        if (!Array.isArray(candles) || !candles.length) return;

        const sorted = [...candles].sort(compareCandlesByTime);
        const upPoints = [];
        const downPoints = [];
        let hasUp = false;
        let hasDown = false;

        sorted.forEach(candle => {
            const time = toChartTime(candle.time);
            if (time == null) return;

            const value = toNumber(candle[SUPERTREND_CONFIG.field]);
            const isUp = candle[SUPERTREND_CONFIG.directionField];

            if (!Number.isFinite(value) || isUp == null) {
                upPoints.push({ time });
                downPoints.push({ time });
                return;
            }

            if (isUp === true) {
                upPoints.push({ time, value });
                downPoints.push({ time });
                hasUp = true;
            } else {
                upPoints.push({ time });
                downPoints.push({ time, value });
                hasDown = true;
            }
        });

        if (!hasUp && !hasDown) return;

        const baseOptions = {
            lineWidth: SUPERTREND_CONFIG.lineWidth,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            lineStyle: window.LightweightCharts.LineStyle.Solid
        };

        if (hasUp) {
            const upSeries = chart.addLineSeries(
                Object.assign({}, baseOptions, { color: SUPERTREND_CONFIG.upColor })
            );
            upSeries.setData(upPoints);
        }

        if (hasDown) {
            const downSeries = chart.addLineSeries(
                Object.assign({}, baseOptions, { color: SUPERTREND_CONFIG.downColor })
            );
            downSeries.setData(downPoints);
        }
    }

    function compareCandlesByTime(left, right) {
        const leftTime = toChartTime(left.time);
        const rightTime = toChartTime(right.time);
        return leftTime - rightTime;
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
            const size = getChartSize(container);
            chart.applyOptions({ width: size.width, height: size.height });
            chart.timeScale().fitContent();
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

    function getPaneRoot(chartType) {
        if (chartType === CHART_TYPES.PE) return document.getElementById('pePane');
        if (chartType === CHART_TYPES.UNDERLYING) return document.getElementById('underlyingPane');
        if (chartType === CHART_TYPES.CE) return document.getElementById('cePane');
        return null;
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
            const size = getChartSize(current.container);
            current.chart.applyOptions({ width: size.width, height: size.height });
            current.chart.timeScale().fitContent();
        });
    }

    function onKeyboardShortcut(event) {
        const target = event.target;
        const tagName = target && target.tagName ? target.tagName.toLowerCase() : '';
        const isTyping = tagName === 'input' || tagName === 'select' || tagName === 'textarea';

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

        const timeframeByKey = { 1: '5m', 2: '10m', 3: '15m' };
        const timeframe = timeframeByKey[event.key];
        if (timeframe && state.timeframes.includes(timeframe)) {
            event.preventDefault();
            state.activeTimeframe = timeframe;
            persistState();
            renderTimeframeTabs();
            renderVisiblePanes();
        }
    }

    function persistState() {
        try {
            localStorage.setItem(LS_KEYS.date, state.date || '');
            localStorage.setItem(LS_KEYS.dataSource, state.dataSource || DEFAULT_DATA_SOURCE);
            localStorage.setItem(LS_KEYS.indexSymbol, state.indexSymbol || DEFAULT_INDEX);
            localStorage.setItem(LS_KEYS.timeframes, JSON.stringify(state.timeframes || [DEFAULT_TIMEFRAME]));
            localStorage.setItem(LS_KEYS.smaPeriods, JSON.stringify(state.smaPeriods || DEFAULT_SMA_PERIODS));
            localStorage.setItem(LS_KEYS.activeTimeframe, state.activeTimeframe || DEFAULT_TIMEFRAME);
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
