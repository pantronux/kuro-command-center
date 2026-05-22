import { postJson } from './api.js';
import { setStatus } from './streaming.js';

export async function analyzeMarketSymbol() {
    const symbol = window.prompt('Symbol', '');
    if (!symbol) return;
    try {
        const payload = await postJson('/api/market-v2/analyze', {
            symbol,
            include_news: true,
            publish_alert: false,
        });
        const report = payload.data?.report || {};
        openMarketDrawer(symbol, report);
        setStatus('Market ready', 'ready');
    } catch (error) {
        setStatus(`Market unavailable: ${error.message}`, 'error');
    }
}

export function openMarketDrawer(symbol, report) {
    const drawer = document.getElementById('v2RightDrawer');
    const title = document.getElementById('v2DrawerTitle');
    const content = document.getElementById('v2DrawerContent');
    if (!drawer || !title || !content) return;
    title.textContent = `Market ${symbol}`;
    content.innerHTML = `<pre>${JSON.stringify(report || {}, null, 2)}</pre>`;
    drawer.dataset.open = 'true';
}

export function bindMarket() {
    document.getElementById('v2MarketBtn')?.addEventListener('click', analyzeMarketSymbol);
}
