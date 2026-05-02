"""
--- Header Doc ---
Purpose: Quantitative price data anchor via yfinance for IDX/BEI stocks.
Caller: main.py scheduler (every 30 min, Mon-Fri 09:00-16:00 WIB).
Dependencies: yfinance, finance_db.
Main Functions: run_price_update(), is_market_hours().
Side Effects: DB upserts to market_sentinel_stocks, no LLM calls.
"""
import logging
import yfinance as yf
from datetime import datetime
import pytz
from kuro_backend.finance_db import upsert_sentinel_stock_price

logger = logging.getLogger(__name__)

# Expanded Watchlist: LQ45 + Cheap Mid-caps
WATCHLIST = [
    # LQ45 (representative sample)
    "ADRO.JK", "AKRA.JK", "AMRT.JK", "ANTM.JK", "ASII.JK", "BBCA.JK", "BBNI.JK", "BBRI.JK",
    "BBTN.JK", "BMRI.JK", "BRPT.JK", "BUKA.JK", "CPIN.JK", "EMTK.JK", "ESSA.JK", "EXCL.JK",
    "GGRM.JK", "GOTO.JK", "HRUM.JK", "ICBP.JK", "INCO.JK", "INDF.JK", "INKP.JK", "INTP.JK",
    "ITMG.JK", "KLBF.JK", "MDKA.JK", "MEDC.JK", "MIKA.JK", "PGAS.JK", "PTBA.JK", "SCMA.JK",
    "SMGR.JK", "TBIG.JK", "TLKM.JK", "TOWR.JK", "TPIA.JK", "UNTR.JK", "UNVR.JK", "UNVR.JK",
    # Cheap Mid-caps / High Volume
    "ELSA.JK", "BUMI.JK", "ENRG.JK", "BRMS.JK", "DEWA.JK", "LPPS.JK", "PKPK.JK", "KRAS.JK",
    "META.JK", "MLPL.JK", "WIIM.JK", "DOID.JK", "SMDR.JK", "BSDE.JK", "PWON.JK", "ASRI.JK"
]

def is_market_hours() -> bool:
    """Check if IDX is currently open (Mon-Fri 09:00-16:00 WIB)."""
    tz = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz)
    # Mon=0, Sun=6
    if now.weekday() >= 5:
        return False
    # 09:00 to 16:00
    if now.hour < 9 or now.hour >= 16:
        return False
    return True

def run_price_update(username: str = "Pantronux") -> dict:
    """Fetch latest prices via yfinance and update the database."""
    # Note: We still allow manual runs even outside market hours for testing
    logger.info("[TICKER] Starting price update for %d tickers...", len(WATCHLIST))
    
    results = {"updated": 0, "failed": 0}
    
    try:
        # Batch download for efficiency
        # We use 30d period to ensure we can calculate YTD if needed or just get the latest close
        data = yf.download(WATCHLIST, period="30d", interval="1d", group_by='ticker', progress=False)
        
        for ticker_symbol in WATCHLIST:
            try:
                ticker_data = data[ticker_symbol]
                if ticker_data.empty:
                    logger.warning("[TICKER] No data for %s", ticker_symbol)
                    results["failed"] += 1
                    continue
                
                # Get the latest row
                latest = ticker_data.iloc[-1]
                price = latest["Close"]
                volume = latest["Volume"]
                
                # Check for NaN
                import pandas as pd
                if pd.isna(price) or pd.isna(volume):
                    # Try to find the last non-NaN row
                    valid_rows = ticker_data.dropna(subset=["Close", "Volume"])
                    if not valid_rows.empty:
                        latest = valid_rows.iloc[-1]
                        price = latest["Close"]
                        volume = latest["Volume"]
                    else:
                        logger.warning("[TICKER] No valid numeric data for %s", ticker_symbol)
                        results["failed"] += 1
                        continue
                
                price = float(price)
                volume = int(volume)
                
                # Calculate YTD approx (this is simplified)
                ytd = 0.0 
                
                stock_code = ticker_symbol.replace(".JK", "")
                lot_price = int(price * 100)
                
                # Categorize
                if lot_price < 100000: category = "below_100k"
                elif lot_price < 500000: category = "below_500k"
                else: category = "above_500k"
                
                # Sector and Name - yfinance doesn't provide these in batch download Close/Volume
                # We'll use the stock_code as name for now, or fetch info separately if needed
                # But for speed, we just update what we have.
                success = upsert_sentinel_stock_price(
                    stock_code=stock_code,
                    company_name=stock_code, # Placeholder, updated by LLM later
                    sector="IDX",
                    price_per_share=int(price),
                    price_per_lot=lot_price,
                    price_category=category,
                    volume_24h=volume,
                    ytd_performance=ytd,
                    username=username
                )
                
                if success:
                    results["updated"] += 1
                else:
                    results["failed"] += 1
                    
            except Exception as e:
                logger.error("[TICKER] Failed to process %s: %s", ticker_symbol, e)
                results["failed"] += 1
                
        logger.info("[TICKER] Update complete: %d updated, %d failed.", results["updated"], results["failed"])
        return results
        
    except Exception as e:
        logger.error("[TICKER] Batch download failed: %s", e)
        return {"error": str(e)}

if __name__ == "__main__":
    # Test run
    import logging
    logging.basicConfig(level=logging.INFO)
    run_price_update()
