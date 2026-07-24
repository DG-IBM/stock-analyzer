"""Data layer — all yfinance and RSS fetching with Streamlit caching."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ---------------------------------------------------------------------------
# Candidate universe — ~80 liquid tickers across all 11 GICS sectors.
# Sector / Industry metadata is fetched live from yfinance at runtime.
# ---------------------------------------------------------------------------
CANDIDATE_TICKERS: list[str] = [
    # Technology
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ORCL", "CRM", "ADBE", "AMD",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP", "SCHW", "C", "COF",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY", "AMGN",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TJX", "LOW", "BKNG", "CMG",
    # Consumer Staples
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MDLZ", "CL", "KHC",
    # Energy
    "XOM", "CVX", "COP", "SLB", "PSX", "EOG", "VLO", "MPC",
    # Industrials
    "BA", "CAT", "GE", "HON", "UPS", "RTX", "DE", "LMT", "GD",
    # Utilities
    "NEE", "DUK", "SO", "D", "EXC", "AEP",
    # Real Estate
    "AMT", "PLD", "EQIX", "CCI", "O", "SPG",
    # Materials
    "LIN", "APD", "ECL", "NEM", "FCX", "NUE",
    # Communication Services
    "VZ", "T", "DIS", "NFLX", "CMCSA",
]


# ---------------------------------------------------------------------------
# Portfolio loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl="1h", show_spinner="Loading portfolio…")
def load_portfolio(file_bytes: bytes) -> pd.DataFrame:
    """Read an uploaded Excel file and enrich each row with yfinance data.

    Expected columns (case-insensitive): Ticker, Shares.
    Returns a DataFrame with Ticker, Shares, Sector, Industry,
    Current Price, Market Value, % of Portfolio, Market Cap.
    """
    raw = pd.read_excel(io.BytesIO(file_bytes))
    # Normalise column names
    raw.columns = [c.strip().title() for c in raw.columns]

    missing = [c for c in ("Ticker", "Shares") if c not in raw.columns]
    if missing:
        raise ValueError(f"Excel file is missing required columns: {missing}")

    raw["Ticker"] = raw["Ticker"].astype(str).str.strip().str.upper()
    raw["Shares"] = pd.to_numeric(raw["Shares"], errors="coerce").fillna(0)

    rows: list[dict] = []
    failed: list[str] = []
    for _, row in raw.iterrows():
        ticker = row["Ticker"]
        info = _fetch_info(ticker)
        if info is None:
            failed.append(ticker)
            continue
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        rows.append({
            "Ticker": ticker,
            "Shares": row["Shares"],
            "Sector": info.get("sector", "Unknown"),
            "Industry": info.get("industry", "Unknown"),
            "Current Price": price,
            "Market Value": price * row["Shares"],
            "Market Cap": info.get("marketCap", 0),
        })

    if not rows:
        raise ValueError("No valid tickers found in the uploaded file.")

    df = pd.DataFrame(rows)
    total = df["Market Value"].sum()
    df["% of Portfolio"] = (df["Market Value"] / total * 100) if total > 0 else 0.0
    df._failed_tickers = failed  # carry through for warnings
    return df


# ---------------------------------------------------------------------------
# Universe for recommendations
# ---------------------------------------------------------------------------

@st.cache_data(ttl="1h", show_spinner="Building universe…")
def get_universe_df() -> pd.DataFrame:
    """Fetch Sector / Industry / Price / Beta / Target for every ticker in CANDIDATE_TICKERS."""
    rows: list[dict] = []
    for ticker in CANDIDATE_TICKERS:
        info = _fetch_info(ticker)
        if info is None:
            continue
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        target = info.get("targetMeanPrice")
        beta = info.get("beta")
        rows.append({
            "Ticker": ticker,
            "Sector": info.get("sector", "Unknown"),
            "Industry": info.get("industry", "Unknown"),
            "Price": price,
            "Beta": beta,
            "Target Price": target,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Single-ticker accessors
# ---------------------------------------------------------------------------

@st.cache_data(ttl="5m", max_entries=50, show_spinner=False)
def get_ticker_info(ticker: str) -> dict:
    """Return yfinance info dict for a single ticker. Empty dict on failure."""
    info = _fetch_info(ticker)
    return info if info else {}


@st.cache_data(ttl="5m", max_entries=50, show_spinner=False)
def get_analyst_data(ticker: str) -> dict:
    """Return analyst recommendation counts and consensus price target."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        recs = t.recommendations
        if recs is not None and not recs.empty:
            latest = recs.iloc[-1]
            counts = {
                "strongBuy": int(latest.get("strongBuy", 0)),
                "buy": int(latest.get("buy", 0)),
                "hold": int(latest.get("hold", 0)),
                "sell": int(latest.get("sell", 0)),
                "strongSell": int(latest.get("strongSell", 0)),
            }
        else:
            counts = {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}
        return {
            **counts,
            "targetMeanPrice": info.get("targetMeanPrice"),
            "recommendationKey": info.get("recommendationKey", "N/A"),
        }
    except Exception:
        return {
            "strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0,
            "targetMeanPrice": None, "recommendationKey": "N/A",
        }


@st.cache_data(ttl="5m", max_entries=50, show_spinner=False)
def get_price_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Return OHLCV history from yfinance. Empty DataFrame on failure."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        df = df.reset_index()
        df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
        return df
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# News via Yahoo Finance RSS
# ---------------------------------------------------------------------------

@st.cache_data(ttl="15m", max_entries=100, show_spinner=False)
def fetch_news_headlines(ticker: str, max_items: int = 20) -> list[str]:
    """Pull recent headlines for a ticker from Yahoo Finance RSS."""
    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={ticker}&region=US&lang=en-US"
    )
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        titles: list[str] = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())
            if len(titles) >= max_items:
                break
        return titles
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internal helper — not cached (callers wrap in cached functions)
# ---------------------------------------------------------------------------

def _fetch_info(ticker: str) -> dict | None:
    """Fetch yfinance .info for a ticker. Returns None on any error."""
    try:
        info = yf.Ticker(ticker).info
        # yfinance returns {"trailingPegRatio": None} for bad tickers
        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            return None
        return info
    except Exception:
        return None
