/**
 * Sentinel Hub - Hybrid Logic (Quant + Qual)
 * Filter system: Date↑↓, Price↑↓, Most Pick, ROI 1M, ROI 1Y, Kuro Rec toggle
 */

let sentinelState = {
    stocks: [],           // raw data from API
    pins: [],             // pinned stock codes
    activeStock: null,    // currently displayed stock
    chartInstance: null,
    sortBy: 'latest',     // active sort key
    sortDir: 'desc',      // 'asc' | 'desc' (for date/price toggles)
    category: null,       // price category filter
    kuroRecOnly: false,   // toggle: show only WORTH BUYING stocks
};

// Sort button configuration: id → { asc_key, desc_key }
const SORT_TOGGLES = {
    sortDate:  { desc: 'latest',    asc: 'oldest'     },
    sortPrice: { desc: 'price_desc', asc: 'price_asc' },
};

async function initSentinelHub() {
    await fetchUserPins();
    await fetchStocks();
    setupEventListeners();
}

function setupEventListeners() {
    // Action buttons
    document.getElementById('runTriangulationBtn')?.addEventListener('click', () =>
        triggerAction('/api/sentinel/run', 'Triangulation triggered.'));
    document.getElementById('runPriceUpdateBtn')?.addEventListener('click', () =>
        triggerAction('/api/sentinel/price-update', 'Price update triggered.'));

    // ── Sort filter buttons ──────────────────────────────────────────────────
    document.querySelectorAll('.filter-btn:not(.rec-filter-btn)').forEach(btn => {
        btn.addEventListener('click', () => {
            const btnId = btn.id;

            // If this button is already active AND supports direction toggle → flip
            if (btn.classList.contains('active') && SORT_TOGGLES[btnId]) {
                sentinelState.sortDir = sentinelState.sortDir === 'desc' ? 'asc' : 'desc';
                const key = SORT_TOGGLES[btnId][sentinelState.sortDir];
                sentinelState.sortBy = key;
                updateSortChevron(btn, sentinelState.sortDir);
            } else {
                // Activate this button, deactivate others (but not rec toggle)
                document.querySelectorAll('.filter-btn:not(.rec-filter-btn)').forEach(b => {
                    b.classList.remove('active');
                    // Reset chevrons on other sort buttons
                    const ch = b.querySelector('.sort-chevron');
                    if (ch) ch.className = 'w-3 h-3 chevron-down sort-chevron';
                });
                btn.classList.add('active');

                // Set sort key — toggle buttons start at desc
                if (SORT_TOGGLES[btnId]) {
                    sentinelState.sortDir = 'desc';
                    sentinelState.sortBy = SORT_TOGGLES[btnId].desc;
                    updateSortChevron(btn, 'desc');
                } else {
                    sentinelState.sortBy = btn.dataset.sort;
                }
            }
            fetchStocks();
        });
    });

    // ── Kuro Recommendation toggle ───────────────────────────────────────────
    const recBtn = document.getElementById('toggleKuroRec');
    recBtn?.addEventListener('click', () => {
        sentinelState.kuroRecOnly = !sentinelState.kuroRecOnly;
        recBtn.classList.toggle('active', sentinelState.kuroRecOnly);
        renderStockList(); // client-side filter, no new fetch needed
    });

    // ── Category tabs ────────────────────────────────────────────────────────
    document.querySelectorAll('.category-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.category-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            sentinelState.category = tab.dataset.category === 'all' ? null : tab.dataset.category;
            fetchStocks();
        });
    });
}

function updateSortChevron(btn, dir) {
    const ch = btn.querySelector('.sort-chevron');
    if (!ch) return;
    if (dir === 'asc') {
        ch.className = 'w-3 h-3 chevron-up sort-chevron';
    } else {
        ch.className = 'w-3 h-3 chevron-down sort-chevron';
    }
}

async function triggerAction(url, successMsg) {
    try {
        const resp = await fetch(url, { method: 'POST' });
        const data = await resp.json();
        alert(data.message || successMsg);
    } catch (e) {
        alert('Action failed.');
    }
}

async function fetchUserPins() {
    try {
        const resp = await fetch('/api/sentinel/pins');
        const data = await resp.json();
        if (data.status === 'success') sentinelState.pins = data.pins;
    } catch (e) { console.error('Pins fetch failed', e); }
}

async function fetchStocks() {
    try {
        let url = `/api/sentinel/stocks?sort_by=${sentinelState.sortBy}`;
        if (sentinelState.category) url += `&category=${sentinelState.category}`;

        const resp = await fetch(url);
        const data = await resp.json();
        if (data.status === 'success') {
            sentinelState.stocks = data.stocks;
            renderStockList();
        }
    } catch (e) { console.error('Stocks fetch failed', e); }
}

function getFilteredStocks() {
    let list = sentinelState.stocks;
    if (sentinelState.kuroRecOnly) {
        // Kuro Recommendation: WORTH BUYING + best ROI 1M or ROI 1Y (top 50% within that group)
        const worthy = list.filter(s => s.conclusion === 'WORTH BUYING');
        if (worthy.length === 0) return [];

        // Rank by composite score: roi_1m * 0.4 + roi_1y * 0.6 (favour long-term)
        const scored = worthy.map(s => ({
            ...s,
            _score: (s.projected_roi_1m || 0) * 0.4 + (s.projected_roi_1y || 0) * 0.6,
        })).sort((a, b) => b._score - a._score);

        // Return top half (min 1)
        const topN = Math.max(1, Math.ceil(scored.length / 2));
        return scored.slice(0, topN);
    }
    return list;
}

function renderStockList() {
    const listEl    = document.getElementById('stockList');
    const pinnedEl  = document.getElementById('pinnedStocks');

    const filtered      = getFilteredStocks();
    const pinnedStocks  = filtered.filter(s =>  sentinelState.pins.includes(s.stock_code));
    const otherStocks   = filtered.filter(s => !sentinelState.pins.includes(s.stock_code));

    const getConclusionDot = (c) => {
        if (c === 'WORTH BUYING') return 'bg-emerald-400';
        if (c === 'HOLD')         return 'bg-amber-400';
        if (c)                    return 'bg-red-400';
        return 'bg-gray-600';
    };

    const renderItem = (s, isPinned) => `
        <div class="stock-item group relative flex items-center gap-3 p-3 rounded-xl border transition-all cursor-pointer
            ${sentinelState.activeStock?.stock_code === s.stock_code
                ? 'bg-emerald-500/5 border-emerald-500/30'
                : 'border-gray-800/40 hover:border-emerald-500/30 hover:bg-gray-800/20'}">
            <button onclick="selectStock('${s.stock_code}')" class="flex-1 text-left min-w-0">
                <div class="flex justify-between items-center">
                    <div class="flex items-center gap-2">
                        <span class="w-1.5 h-1.5 rounded-full ${getConclusionDot(s.conclusion)} flex-shrink-0"></span>
                        <span class="font-bold text-gray-200 group-hover:text-emerald-400 transition-colors">${s.stock_code}</span>
                    </div>
                    <span class="text-[10px] font-mono text-gray-400">${formatIDR(s.current_price_per_share)}</span>
                </div>
                <div class="flex justify-between items-center mt-1">
                    <span class="text-[9px] text-gray-500 truncate max-w-[110px]">${s.company_name}</span>
                    <div class="flex gap-2">
                        ${s.projected_roi_1m != null
                            ? `<span class="text-[9px] font-mono ${s.projected_roi_1m >= 0 ? 'text-emerald-400' : 'text-red-400'}">
                                1M:${s.projected_roi_1m >= 0 ? '+' : ''}${s.projected_roi_1m}%</span>`
                            : ''}
                        ${s.projected_roi_1y != null
                            ? `<span class="text-[9px] font-mono ${s.projected_roi_1y >= 0 ? 'text-blue-400' : 'text-red-400'}">
                                1Y:${s.projected_roi_1y >= 0 ? '+' : ''}${s.projected_roi_1y}%</span>`
                            : ''}
                    </div>
                </div>
            </button>
            <button onclick="togglePin('${s.stock_code}')" class="p-1.5 rounded-lg hover:bg-gray-800 transition-colors flex-shrink-0">
                <i data-lucide="star" class="w-4 h-4 ${isPinned ? 'fill-amber-400 text-amber-400' : 'text-gray-600'}"></i>
            </button>
        </div>
    `;

    pinnedEl.innerHTML = pinnedStocks.length
        ? pinnedStocks.map(s => renderItem(s, true)).join('')
        : '<p class="text-[9px] text-gray-600 italic text-center py-2">No pinned stocks yet</p>';

    const emptyMsg = sentinelState.kuroRecOnly
        ? '<p class="text-[9px] text-amber-600/70 italic text-center py-2">No stocks meet Kuro\'s recommendation criteria</p>'
        : '<p class="text-[9px] text-gray-600 italic text-center py-2">No stocks available</p>';

    listEl.innerHTML = otherStocks.length
        ? otherStocks.map(s => renderItem(s, false)).join('')
        : emptyMsg;

    if (window.lucide) lucide.createIcons();
}

async function togglePin(code) {
    try {
        const resp = await fetch(`/api/sentinel/pins/${code}`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'success') {
            await fetchUserPins();
            renderStockList();
        } else {
            alert(data.message);
        }
    } catch (e) { alert('Failed to toggle pin.'); }
}

async function selectStock(code) {
    try {
        const resp = await fetch(`/api/sentinel/stock/${code}`);
        const data = await resp.json();
        if (data.status === 'success') {
            sentinelState.activeStock = data.stock;
            document.getElementById('emptyState').classList.add('hidden');
            document.getElementById('contentArea').classList.remove('hidden');
            renderStockDetail(data.stock);
            renderChart(data.history);
            renderStockList();
        }
    } catch (e) { console.error('Detail fetch failed', e); }
}

function renderStockDetail(s) {
    const detailHeader = document.getElementById('detailHeader');
    const analysisArea = document.getElementById('analysisArea');
    const kuroRecCard  = document.getElementById('kuroRecCard');

    detailHeader.innerHTML = `
        <div>
            <h2 class="text-3xl font-black text-gray-100">${s.stock_code}
                <span class="text-sm font-medium text-gray-500 ml-2">/ ${s.company_name}</span>
            </h2>
            <div class="flex items-center gap-4 mt-2">
                <span class="text-2xl font-mono font-bold text-emerald-400">${formatIDR(s.current_price_per_share)}</span>
                <span class="text-sm font-mono text-gray-400">Rp ${(s.current_price_per_lot || 0).toLocaleString('id-ID')} / LOT</span>
                <span class="px-2 py-0.5 rounded bg-gray-800 text-[10px] font-bold text-gray-400 uppercase border border-gray-700/50">
                    ${(s.price_category || '').replace('_', ' ')}
                </span>
            </div>
        </div>
        <div class="flex flex-col items-end gap-1">
            <span class="conclusion-badge ${getConclusionClass(s.conclusion)}">${s.conclusion || 'PENDING'}</span>
            <span class="text-[10px] text-gray-500">Price: ${formatDate(s.price_updated_at)}</span>
        </div>
    `;

    // ── Kuro Rec Card ──────────────────────────────────────────────────────────
    const hasAnalysis = s.conclusion || s.triangulation_summary || s.projected_roi_1m != null;
    if (hasAnalysis) {
        kuroRecCard.classList.remove('hidden', 'rec-worth', 'rec-hold', 'rec-avoid');
        if (s.conclusion === 'WORTH BUYING') kuroRecCard.classList.add('rec-worth');
        else if (s.conclusion === 'HOLD')    kuroRecCard.classList.add('rec-hold');
        else                                 kuroRecCard.classList.add('rec-avoid');

        const conclusionEl = document.getElementById('kuroConclusion');
        conclusionEl.textContent = s.conclusion || 'PENDING';
        conclusionEl.className = `conclusion-badge text-sm px-4 py-1.5 ${getConclusionClass(s.conclusion)}`;

        document.getElementById('kuroRoi1m').textContent = s.projected_roi_1m != null
            ? `${s.projected_roi_1m >= 0 ? '+' : ''}${s.projected_roi_1m}%` : 'N/A';
        document.getElementById('kuroRoi1y').textContent = s.projected_roi_1y != null
            ? `${s.projected_roi_1y >= 0 ? '+' : ''}${s.projected_roi_1y}%` : 'N/A';
        document.getElementById('kuroSummary').textContent = s.triangulation_summary
            ? `"${s.triangulation_summary}"`
            : 'Analysis pending next triangulation cycle.';
    } else {
        kuroRecCard.classList.add('hidden');
    }

    // ── Analysis Grid ──────────────────────────────────────────────────────────
    analysisArea.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="glass-card rounded-2xl p-6 border-l-4 border-emerald-500">
                <h4 class="text-xs font-bold text-emerald-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                    <i data-lucide="trending-up" class="w-4 h-4"></i> ROI Projections
                </h4>
                <div class="space-y-3">
                    <div class="flex justify-between items-center p-3 rounded-xl bg-gray-900/40 border border-gray-800">
                        <span class="text-gray-400 text-xs">1 Month Potential</span>
                        <span class="text-xl font-bold ${(s.projected_roi_1m || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}">
                            ${s.projected_roi_1m != null ? (s.projected_roi_1m >= 0 ? '+' : '') + s.projected_roi_1m + '%' : 'N/A'}
                        </span>
                    </div>
                    <div class="flex justify-between items-center p-3 rounded-xl bg-gray-900/40 border border-gray-800">
                        <span class="text-gray-400 text-xs">1 Year Potential</span>
                        <span class="text-xl font-bold ${(s.projected_roi_1y || 0) >= 0 ? 'text-blue-400' : 'text-red-400'}">
                            ${s.projected_roi_1y != null ? (s.projected_roi_1y >= 0 ? '+' : '') + s.projected_roi_1y + '%' : 'N/A'}
                        </span>
                    </div>
                </div>
            </div>

            <div class="glass-card rounded-2xl p-6 border-l-4 border-blue-500">
                <h4 class="text-xs font-bold text-blue-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                    <i data-lucide="bar-chart-3" class="w-4 h-4"></i> Market Volume
                </h4>
                <div class="space-y-3">
                    <div class="flex justify-between items-center p-3 rounded-xl bg-gray-900/40 border border-gray-800">
                        <span class="text-gray-400 text-xs">24h Volume</span>
                        <span class="text-lg font-bold text-blue-400">${(s.volume_24h || 0).toLocaleString()}</span>
                    </div>
                    <div class="flex justify-between items-center p-3 rounded-xl bg-gray-900/40 border border-gray-800">
                        <span class="text-gray-400 text-xs">YTD ROI</span>
                        <span class="text-lg font-bold ${(s.ytd_performance || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}">${s.ytd_performance || 0}%</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="glass-card rounded-2xl p-4 border border-gray-800/30">
            <div class="flex items-center justify-between text-[10px] text-gray-600">
                <span>Price updated: <span class="text-gray-400">${formatDate(s.price_updated_at)}</span></span>
                <span>Analysis updated: <span class="text-gray-400">${s.analysis_updated_at ? formatDate(s.analysis_updated_at) : 'Pending'}</span></span>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
}

function renderChart(history) {
    const ctx = document.getElementById('priceChart').getContext('2d');
    const labels = (history || []).map(h => formatDate(h.scan_timestamp, true));
    const prices = (history || []).map(h => h.price_per_share);

    if (sentinelState.chartInstance) sentinelState.chartInstance.destroy();

    sentinelState.chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels.length ? labels : ['No Data'],
            datasets: [{
                label: 'Price',
                data: prices.length ? prices : [0],
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 3,
                fill: true,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#6b7280', font: { size: 9 } } },
                y: { grid: { color: 'rgba(75, 85, 99, 0.1)' }, ticks: { color: '#6b7280', font: { size: 9 } } },
            }
        }
    });
}

// ── Utils ──────────────────────────────────────────────────────────────────────
function formatIDR(val) {
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(val || 0);
}

function formatDate(iso, short = false) {
    if (!iso) return 'N/A';
    const d = new Date(iso);
    if (short) return d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short' });
    return d.toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function getConclusionClass(c) {
    if (c === 'WORTH BUYING') return 'badge-worth';
    if (c === 'HOLD')         return 'badge-hold';
    return 'badge-avoid';
}
