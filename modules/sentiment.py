"""Sentiment engine — uses Claude via IBM ICA gateway to score news headlines."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from modules.data import fetch_news_headlines
from modules.llm import client, ICA_MODEL

# Batch size: number of tickers scored in a single Claude call.
# Smaller = more reliable JSON responses from ICA. 8 is safe.
_BATCH_SIZE = 8

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
    """Strip optional markdown fences and parse a JSON object."""
    cleaned = re.sub(r"^```[a-z]*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    return json.loads(cleaned)


def _parse_json_list(text: str) -> list:
    """Extract a JSON array from text, tolerating markdown fences and preamble."""
    cleaned = re.sub(r"^```[a-z]*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    # If there's preamble before the '[', slice to the first '['
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
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


@st.cache_data(ttl="15m", max_entries=50, show_spinner=False)
def generate_comparison_verdict(
    tickers: list[str],
    ticker_data: list[dict],   # list of {ticker, info, analyst, sentiment}
    portfolio_context: str,    # plain-text summary of the user's portfolio
) -> str:
    """Ask Claude to compare multiple tickers and recommend the best buy.

    Returns a plain markdown string with the verdict.
    """
    if not ticker_data:
        return "No data available for comparison."

    sections: list[str] = []
    for td in ticker_data:
        t = td["ticker"]
        info = td.get("info", {})
        analyst = td.get("analyst", {})
        sentiment = td.get("sentiment", {})
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        target = analyst.get("targetMeanPrice")
        upside = f"{(target - price) / price * 100:+.1f}%" if target and price else "N/A"
        rec = (analyst.get("recommendationKey") or "N/A").replace("_", " ").title()
        beta = info.get("beta", "N/A")
        sector = info.get("sector", "N/A")
        sections.append(
            f"**{t}** ({sector})\n"
            f"- Price: ${price:,.2f}  |  Analyst target: {'$'+f'{target:,.2f}' if target else 'N/A'}  |  Upside: {upside}\n"
            f"- Analyst rec: {rec}  |  Beta: {beta}\n"
            f"- Sentiment score: {sentiment.get('score', 0):+.2f}  ({sentiment.get('label', 'N/A')})\n"
            f"- Sentiment reasoning: {sentiment.get('reasoning', 'N/A')}"
        )

    ticker_block = "\n\n".join(sections)
    prompt = (
        f"You are a senior equity analyst. Compare these stocks for a potential investor.\n\n"
        f"{ticker_block}\n\n"
        f"The investor's current portfolio context:\n{portfolio_context}\n\n"
        f"Write 3–4 sentences: which stock is the best buy right now and why, "
        f"considering their existing portfolio. Be direct and specific. "
        f"Do not use bullet points — write flowing prose."
    )

    try:
        response = client.chat.completions.create(
            model=ICA_MODEL,
            max_tokens=350,
            messages=[
                {"role": "system", "content": "You are a concise, direct senior equity analyst. Respond in plain prose only."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Could not generate verdict: {e}"


@st.cache_data(ttl="15m", show_spinner=False)
def _score_batch(tickers_tuple: tuple[str, ...]) -> list[dict]:
    """Score a batch of tickers in a single Claude call.

    Takes a tuple (hashable for caching). Returns list of raw dicts.
    """
    tickers = list(tickers_tuple)

    # Fetch headlines for all tickers in this batch concurrently
    def _get_section(ticker: str) -> str:
        headlines = fetch_news_headlines(ticker, max_items=10)
        if headlines:
            joined = "\n".join(f"  - {h}" for h in headlines[:10])
            return f"### {ticker}\n{joined}"
        return f"### {ticker}\n  - No recent headlines available."

    with ThreadPoolExecutor(max_workers=len(tickers)) as pool:
        sections = list(pool.map(_get_section, tickers))

    user_msg = "\n\n".join(sections)

    fallback = [
        {"ticker": t, "score": 0.0, "label": "Neutral", "reasoning": "No data."}
        for t in tickers
    ]
    try:
        response = client.chat.completions.create(
            model=ICA_MODEL,
            max_tokens=200 * len(tickers),   # ~200 tokens per ticker result
            messages=[
                {"role": "system", "content": _SYSTEM_BULK},
                {"role": "user", "content": user_msg},
            ],
        )
        raw_text = response.choices[0].message.content
        raw = _parse_json_list(raw_text)
        if isinstance(raw, dict):
            raw = [{"ticker": k, **v} for k, v in raw.items()]
        return raw if isinstance(raw, list) else fallback
    except Exception as e:
        # Surface the error in the Streamlit sidebar so we can debug
        import streamlit as _st
        _st.sidebar.warning(f"Batch score error ({tickers[0]}…): {e}")
        return fallback


def score_tickers_bulk(tickers: list[str]) -> pd.DataFrame:
    """Score multiple tickers via parallel batched Claude calls.

    Splits tickers into chunks of _BATCH_SIZE, fires ALL chunks concurrently,
    then merges results. Returns DataFrame: Ticker, Score, Label, Reasoning.
    """
    if not tickers:
        return pd.DataFrame(columns=["Ticker", "Score", "Label", "Reasoning"])

    chunks = [
        tuple(tickers[i : i + _BATCH_SIZE])
        for i in range(0, len(tickers), _BATCH_SIZE)
    ]

    results: list[dict] = []
    # Fire all batch calls in parallel — each chunk is an independent Claude request
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        futures = [pool.submit(_score_batch, chunk) for chunk in chunks]
        for future in as_completed(futures):
            results.extend(future.result())

    # Index by ticker for quick lookup; fall back to neutral if missing
    result_map = {r.get("ticker", "").upper(): r for r in results}
    rows = []
    for ticker in tickers:
        r = result_map.get(ticker.upper(), {})
        rows.append({
            "Ticker": ticker,
            "Score": float(r.get("score", 0.0)),
            "Label": r.get("label", "Neutral"),
            "Reasoning": r.get("reasoning", "No data."),
        })

    return pd.DataFrame(rows)
