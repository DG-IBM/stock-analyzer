"""Recommendation engine — Similar and Diversify picks with Claude rationales."""
from __future__ import annotations

import json
import re

import pandas as pd
import streamlit as st

from modules.data import get_universe_df, get_ticker_info
from modules.sentiment import score_tickers_bulk
from modules.llm import client, ICA_MODEL

# ---------------------------------------------------------------------------
# Risk classification from beta
# ---------------------------------------------------------------------------
RISK_LEVELS = ["Low", "Medium", "High", "Extreme"]

def _beta_to_risk(beta: float | None) -> str:
    if beta is None:
        return "Unknown"
    if beta < 0.8:
        return "Low"
    if beta < 1.2:
        return "Medium"
    if beta < 1.8:
        return "High"
    return "Extreme"


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```[a-z]*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    return json.loads(cleaned)


@st.cache_data(ttl="1h", max_entries=200, show_spinner=False)
def generate_why(
    ticker: str,
    sector: str,
    industry: str,
    score: float,
    portfolio_sectors: tuple[str, ...],
) -> str:
    """Ask Claude for a one-sentence rationale for a recommendation."""
    sectors_str = ", ".join(sorted(set(portfolio_sectors))) if portfolio_sectors else "various sectors"
    prompt = (
        f"In one sentence (no quotes, no bullet), explain why {ticker} "
        f"({sector} / {industry}, sentiment score {score:+.2f}) is a good pick "
        f"for a portfolio concentrated in {sectors_str}."
    )
    try:
        response = client.chat.completions.create(
            model=ICA_MODEL,
            max_tokens=80,
            messages=[
                {"role": "system", "content": "You are a concise financial analyst. Reply with one plain sentence only."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip().strip('"').strip("'")
    except Exception:
        return f"{sector} / {industry} — sentiment {score:+.2f}"


def get_recommendations(
    portfolio_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (similar_df, diversify_df) — unfiltered, all columns included.

    Filtering by price, risk, sentiment, and sector is applied in the UI layer
    so cached results can be reused across different filter combinations.

    Each DataFrame has columns:
        Ticker, Sector, Industry, Score, Label, Price, Beta, Risk, % to Target, Why
    """
    held_tickers = set(portfolio_df["Ticker"].str.upper().tolist())
    held_sectors = set(portfolio_df["Sector"].dropna().tolist())
    held_industries = set(portfolio_df["Industry"].dropna().tolist())
    portfolio_sectors_tuple = tuple(sorted(held_sectors))

    total_holdings = len(portfolio_df)

    universe = get_universe_df()
    universe = universe[~universe["Ticker"].isin(held_tickers)]

    # ------------------------------------------------------------------
    # Similar — same sector or industry as holdings
    # ------------------------------------------------------------------
    similar_candidates = universe[
        universe["Sector"].isin(held_sectors) | universe["Industry"].isin(held_industries)
    ]["Ticker"].tolist()

    similar_sentiment = score_tickers_bulk(similar_candidates)
    bullish_similar = (
        similar_sentiment[similar_sentiment["Label"] == "Bullish"]
        .sort_values("Score", ascending=False)
        .head(10)
    )
    similar_rows = _build_rows(bullish_similar, universe, portfolio_sectors_tuple)
    similar_df = pd.DataFrame(similar_rows) if similar_rows else pd.DataFrame(
        columns=["Ticker", "Sector", "Industry", "Score", "Label", "Price", "Beta", "Risk", "% to Target", "Why"]
    )

    # ------------------------------------------------------------------
    # Diversify — sectors absent or underrepresented (< 5% of holdings)
    # ------------------------------------------------------------------
    sector_counts = portfolio_df["Sector"].value_counts()
    underrep_threshold = max(1, total_holdings * 0.05)
    underrep_sectors = {
        s for s in universe["Sector"].unique()
        if sector_counts.get(s, 0) < underrep_threshold
    }

    diversify_candidates = universe[universe["Sector"].isin(underrep_sectors)]["Ticker"].tolist()
    diversify_sentiment = score_tickers_bulk(diversify_candidates)
    bullish_diversify = (
        diversify_sentiment[diversify_sentiment["Label"] == "Bullish"]
        .sort_values("Score", ascending=False)
        .head(10)
    )
    diversify_rows = _build_rows(bullish_diversify, universe, portfolio_sectors_tuple)
    diversify_df = pd.DataFrame(diversify_rows) if diversify_rows else pd.DataFrame(
        columns=["Ticker", "Sector", "Industry", "Score", "Label", "Price", "Beta", "Risk", "% to Target", "Why"]
    )

    return similar_df, diversify_df


def apply_filters(
    df: pd.DataFrame,
    max_price: float | None,
    risk_levels: list[str],
    min_score: float,
    sectors: list[str] | None,
) -> pd.DataFrame:
    """Apply user-selected filters to a recommendations DataFrame."""
    out = df.copy()
    if max_price is not None and "Price" in out.columns:
        out = out[out["Price"] <= max_price]
    if risk_levels and "Risk" in out.columns:
        out = out[out["Risk"].isin(risk_levels)]
    if min_score > -1.0 and "Score" in out.columns:
        out = out[out["Score"] >= min_score]
    if sectors and "Sector" in out.columns:
        out = out[out["Sector"].isin(sectors)]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_rows(
    sentiment_df: pd.DataFrame,
    universe: pd.DataFrame,
    portfolio_sectors_tuple: tuple[str, ...],
) -> list[dict]:
    rows = []
    for _, row in sentiment_df.iterrows():
        ticker = row["Ticker"]
        uni_row = universe[universe["Ticker"] == ticker]
        if uni_row.empty:
            continue
        u = uni_row.iloc[0]
        sector = u["Sector"]
        industry = u["Industry"]
        price = float(u["Price"])
        beta_raw = u.get("Beta")
        beta = float(beta_raw) if beta_raw is not None and str(beta_raw) != "nan" else None
        target_raw = u.get("Target Price")
        target = float(target_raw) if target_raw is not None and str(target_raw) != "nan" else None
        pct_to_target = round((target - price) / price * 100, 1) if target and price else None
        score = float(row["Score"])
        label = row["Label"]
        risk = _beta_to_risk(beta)
        why = generate_why(ticker, sector, industry, score, portfolio_sectors_tuple)
        rows.append({
            "Ticker": ticker,
            "Sector": sector,
            "Industry": industry,
            "Score": score,
            "Label": label,
            "Price": price,
            "Beta": beta,
            "Risk": risk,
            "% to Target": pct_to_target,
            "Why": why,
        })
    return rows
