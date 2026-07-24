"""Sentiment engine — uses Claude via IBM ICA gateway to score news headlines."""
from __future__ import annotations

import json
import re

import pandas as pd
import streamlit as st

from modules.data import fetch_news_headlines
from modules.llm import client, ICA_MODEL

# Batch size: number of tickers scored in a single Claude call.
# Larger = fewer API calls but bigger prompt. 15 is a safe balance.
_BATCH_SIZE = 15

_SYSTEM_SENTIMENT = """\
You are a financial sentiment analyst. Given a list of news headlines for a stock ticker, \
return ONLY a valid JSON object with no markdown fences, no extra text, exactly this shape:
{
  "score": <float between -1.0 (most negative) and 1.0 (most positive)>,
  "label": <"Bullish" | "Bearish" | "Neutral">,
  "reasoning": <one concise sentence explaining the overall sentiment>,
  "bull_headlines": [<up to 3 most positive headlines verbatim>],
  "bear_headlines": [<up to 3 most negative headlines verbatim>]
}
"""

_SYSTEM_BULK = """\
You are a financial sentiment analyst. You will receive headlines for multiple stock tickers.
Return ONLY a valid JSON array — one object per ticker — with no markdown fences, no extra text.
Each object must have exactly these keys:
  "ticker": <string>,
  "score": <float -1.0 to 1.0>,
  "label": <"Bullish" | "Bearish" | "Neutral">,
  "reasoning": <one concise sentence>
Respond with only the JSON array, nothing else.
"""

_SYSTEM_BULL_BEAR = """\
You are a senior equity research analyst. Given a set of recent news headlines for a stock, \
write a short bull case and a short bear case. Return ONLY a valid JSON object, no markdown:
{
  "bull": "<2-3 sentence bull case>",
  "bear": "<2-3 sentence bear case>"
}
"""

_FALLBACK: dict = {
    "score": 0.0,
    "label": "Neutral",
    "reasoning": "No headlines available.",
    "bull_headlines": [],
    "bear_headlines": [],
}


def _parse_json(text: str) -> dict:
    """Strip optional markdown fences and parse JSON."""
    cleaned = re.sub(r"^```[a-z]*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    return json.loads(cleaned)


@st.cache_data(ttl="15m", max_entries=100, show_spinner=False)
def score_ticker(ticker: str) -> dict:
    """Score a ticker's sentiment using Claude.

    Returns dict with keys: score, label, reasoning, bull_headlines, bear_headlines.
    """
    headlines = fetch_news_headlines(ticker)
    if not headlines:
        return {**_FALLBACK}

    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    user_msg = f"Ticker: {ticker}\n\nHeadlines:\n{numbered}"

    try:
        response = client.chat.completions.create(
            model=ICA_MODEL,
            max_tokens=512,
            messages=[
                {"role": "system", "content": _SYSTEM_SENTIMENT},
                {"role": "user", "content": user_msg},
            ],
        )
        result = _parse_json(response.choices[0].message.content)
        # Validate required keys
        for key in ("score", "label", "reasoning", "bull_headlines", "bear_headlines"):
            if key not in result:
                result[key] = _FALLBACK[key]
        result["score"] = float(result["score"])
        return result
    except Exception:
        return {**_FALLBACK}


@st.cache_data(ttl="15m", max_entries=50, show_spinner=False)
def generate_bull_bear_narrative(
    ticker: str,
    bull_headlines: list[str],
    bear_headlines: list[str],
) -> dict[str, str]:
    """Ask Claude to write a 2-3 sentence bull case and bear case.

    Returns dict with keys: bull, bear.
    """
    if not bull_headlines and not bear_headlines:
        return {
            "bull": "Insufficient headline data to build a bull case.",
            "bear": "Insufficient headline data to build a bear case.",
        }

    all_headlines = bull_headlines + bear_headlines
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(all_headlines))
    user_msg = f"Ticker: {ticker}\n\nRecent headlines:\n{numbered}"

    try:
        response = client.chat.completions.create(
            model=ICA_MODEL,
            max_tokens=400,
            messages=[
                {"role": "system", "content": _SYSTEM_BULL_BEAR},
                {"role": "user", "content": user_msg},
            ],
        )
        result = _parse_json(response.choices[0].message.content)
        return {
            "bull": result.get("bull", "No bull case generated."),
            "bear": result.get("bear", "No bear case generated."),
        }
    except Exception:
        return {
            "bull": "Could not generate bull case.",
            "bear": "Could not generate bear case.",
        }


@st.cache_data(ttl="15m", show_spinner=False)
def _score_batch(tickers_tuple: tuple[str, ...]) -> list[dict]:
    """Score a batch of tickers in a single Claude call.

    Takes a tuple (hashable for caching). Returns list of raw dicts.
    """
    tickers = list(tickers_tuple)

    # Gather headlines for all tickers in this batch
    sections: list[str] = []
    for ticker in tickers:
        headlines = fetch_news_headlines(ticker, max_items=10)
        if headlines:
            joined = "\n".join(f"  - {h}" for h in headlines[:10])
            sections.append(f"### {ticker}\n{joined}")
        else:
            sections.append(f"### {ticker}\n  - No recent headlines available.")

    user_msg = "\n\n".join(sections)

    fallback = [
        {"ticker": t, "score": 0.0, "label": "Neutral", "reasoning": "No data."}
        for t in tickers
    ]
    try:
        response = client.chat.completions.create(
            model=ICA_MODEL,
            max_tokens=150 * len(tickers),   # ~150 tokens per ticker result
            messages=[
                {"role": "system", "content": _SYSTEM_BULK},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = _parse_json(response.choices[0].message.content)
        # raw should be a list; if Claude returns a dict keyed by ticker, normalise it
        if isinstance(raw, dict):
            raw = [{"ticker": k, **v} for k, v in raw.items()]
        return raw if isinstance(raw, list) else fallback
    except Exception:
        return fallback


def score_tickers_bulk(tickers: list[str]) -> pd.DataFrame:
    """Score multiple tickers via batched Claude calls.

    Splits tickers into chunks of _BATCH_SIZE, fires one Claude call per chunk,
    then merges results. Returns DataFrame: Ticker, Score, Label, Reasoning.
    """
    if not tickers:
        return pd.DataFrame(columns=["Ticker", "Score", "Label", "Reasoning"])

    results: list[dict] = []
    for i in range(0, len(tickers), _BATCH_SIZE):
        chunk = tickers[i : i + _BATCH_SIZE]
        results.extend(_score_batch(tuple(chunk)))

    rows = []
    # Index by ticker for quick lookup; fall back to neutral if missing
    result_map = {r.get("ticker", "").upper(): r for r in results}
    for ticker in tickers:
        r = result_map.get(ticker.upper(), {})
        rows.append({
            "Ticker": ticker,
            "Score": float(r.get("score", 0.0)),
            "Label": r.get("label", "Neutral"),
            "Reasoning": r.get("reasoning", "No data."),
        })

    return pd.DataFrame(rows)
