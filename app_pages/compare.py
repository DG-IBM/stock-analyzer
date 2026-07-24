"""Compare page — side-by-side analysis of 2–3 tickers, portfolio-aware."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import altair as alt
import pandas as pd
import streamlit as st

from modules.data import get_analyst_data, get_price_history, get_ticker_info
from modules.sentiment import generate_comparison_verdict, score_ticker

st.title(":material/compare_arrows: Compare stocks")
st.caption("Side-by-side price performance, sentiment, analyst ratings, and a Claude verdict.")

# ── Portfolio context ─────────────────────────────────────────────────────
portfolio_df: pd.DataFrame | None = st.session_state.get("portfolio")

if portfolio_df is not None:
    held_tickers  = portfolio_df["Ticker"].tolist()
    held_sectors  = portfolio_df["Sector"].dropna().unique().tolist()
    top_holding   = portfolio_df.loc[portfolio_df["Market Value"].idxmax(), "Ticker"]
    total_value   = portfolio_df["Market Value"].sum()
    portfolio_context = (
        f"Holdings: {', '.join(held_tickers)}. "
        f"Sectors: {', '.join(held_sectors)}. "
        f"Top holding: {top_holding}. "
        f"Total value: ${total_value:,.0f}."
    )
    st.caption(
        f":material/pie_chart: Portfolio loaded — {len(held_tickers)} holdings across "
        f"{len(held_sectors)} sectors. Claude's verdict will factor this in."
    )
else:
    portfolio_context = "No portfolio loaded. Analyse purely on fundamentals and sentiment."
    st.caption(
        ":material/info: No portfolio loaded — upload holdings on the **Portfolio** page "
        "to get a portfolio-aware verdict."
    )

st.space("small")

# ── Ticker entry ──────────────────────────────────────────────────────────
with st.container(border=True):
    st.caption("TICKERS & PERIOD")
    col_a, col_b, col_c, col_period = st.columns([2, 2, 2, 2])
    with col_a:
        t1 = st.text_input("Ticker 1", placeholder="e.g. AAPL",
                           label_visibility="collapsed", key="cmp_t1").strip().upper()
    with col_b:
        t2 = st.text_input("Ticker 2", placeholder="e.g. MSFT",
                           label_visibility="collapsed", key="cmp_t2").strip().upper()
    with col_c:
        t3 = st.text_input("Ticker 3 (optional)", placeholder="e.g. NVDA",
                           label_visibility="collapsed", key="cmp_t3").strip().upper()
    with col_period:
        period = st.segmented_control(
            "Period", options=["1mo", "3mo", "6mo", "1y", "2y"],
            default="6mo", key="cmp_period",
        )

tickers = [t for t in [t1, t2, t3] if t]

if len(tickers) < 2:
    st.space("small")
    st.caption(":material/edit: Enter at least 2 ticker symbols above.")
    st.stop()

# ── Fetch all data concurrently ───────────────────────────────────────────
@st.cache_data(ttl="5m", show_spinner=False)
def _fetch_all(tickers_tuple: tuple[str, ...], period: str) -> list[dict]:
    def _one(ticker: str) -> dict:
        return {
            "ticker":    ticker,
            "info":      get_ticker_info(ticker),
            "analyst":   get_analyst_data(ticker),
            "history":   get_price_history(ticker, period=period),
            "sentiment": score_ticker(ticker),
        }
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(tickers_tuple)) as pool:
        futures = {pool.submit(_one, t): t for t in tickers_tuple}
        for f in as_completed(futures):
            d = f.result()
            results[d["ticker"]] = d
    return [results[t] for t in tickers_tuple if t in results]


with st.spinner(f"Fetching data for {', '.join(tickers)}…"):
    ticker_data = _fetch_all(tuple(tickers), period or "6mo")

if not ticker_data:
    st.error("Could not load data for any of the tickers entered.", icon=":material/error:")
    st.stop()

PALETTE    = ["#60A5FA", "#34D399", "#A78BFA", "#F87171"]
colour_map = {td["ticker"]: PALETTE[i % len(PALETTE)] for i, td in enumerate(ticker_data)}

# ── Section 1 — At a glance cards ─────────────────────────────────────────
st.subheader("At a glance")
metric_cols = st.columns(len(ticker_data), gap="medium")

for col, td in zip(metric_cols, ticker_data):
    ticker   = td["ticker"]
    info     = td["info"]
    analyst  = td["analyst"]
    sentiment = td["sentiment"]

    price   = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    target  = analyst.get("targetMeanPrice")
    upside  = f"{(target - price) / price * 100:+.1f}%" if target and price else "—"
    rec     = (analyst.get("recommendationKey") or "N/A").replace("_", " ").title()
    beta    = info.get("beta")
    score   = sentiment.get("score", 0.0)
    label   = sentiment.get("label", "N/A")
    lcolour = "green" if label == "Bullish" else "red" if label == "Bearish" else "gray"
    company = info.get("longName") or info.get("shortName") or ticker
    sector  = info.get("sector", "—")
    colour  = colour_map[ticker]

    with col:
        with st.container(border=True):
            # Colour dot + ticker header
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px'>"
                f"<span style='width:10px;height:10px;border-radius:50%;"
                f"background:{colour};display:inline-block'></span>"
                f"<strong style='font-size:16px'>{ticker}</strong>"
                f"</div>"
                f"<div style='color:#94A3B8;font-size:11px;margin-top:2px'>{company}</div>"
                f"<div style='color:#64748B;font-size:10px'>{sector}</div>",
                unsafe_allow_html=True,
            )
            st.space("small")
            # Stacked metrics — no inner columns, works at any width
            st.metric("Price",       f"${price:,.2f}")
            st.metric("Target",      f"${target:,.2f}" if target else "—", delta=upside)
            st.metric("Analyst rec", rec)
            st.metric("Beta",        f"{beta:.2f}" if beta else "—")
            st.metric("Sentiment",   f"{score:+.2f}")
            st.badge(label, color=lcolour)

st.space("small")

# ── Section 2 — Normalised price chart ───────────────────────────────────
with st.container(border=True):
    st.subheader("Price performance (indexed to 100)", divider=False)
    frames: list[pd.DataFrame] = []
    for td in ticker_data:
        hist = td["history"]
        if hist.empty:
            continue
        df = hist[["Date", "Close"]].copy()
        df["Ticker"] = td["ticker"]
        first = df["Close"].iloc[0]
        df["Indexed"] = df["Close"] / first * 100 if first else df["Close"]
        frames.append(df)

    if frames:
        combined      = pd.concat(frames, ignore_index=True)
        ticker_list   = combined["Ticker"].unique().tolist()
        norm_chart = (
            alt.Chart(combined)
            .mark_line(strokeWidth=2.5)
            .encode(
                x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %Y")),
                y=alt.Y("Indexed:Q", title="Indexed price (start = 100)",
                        scale=alt.Scale(zero=False)),
                color=alt.Color(
                    "Ticker:N",
                    scale=alt.Scale(
                        domain=ticker_list,
                        range=[colour_map.get(t, "#94A3B8") for t in ticker_list],
                    ),
                    legend=alt.Legend(title=None, orient="top"),
                ),
                tooltip=[
                    alt.Tooltip("Date:T",    format="%b %d, %Y"),
                    alt.Tooltip("Ticker:N"),
                    alt.Tooltip("Indexed:Q", format=".1f",   title="Indexed"),
                    alt.Tooltip("Close:Q",   format="$.2f",  title="Close"),
                ],
            )
            .properties(height=320)
        )
        baseline = (
            alt.Chart(pd.DataFrame({"y": [100]}))
            .mark_rule(strokeDash=[6, 3], color="#475569", opacity=0.4)
            .encode(y="y:Q")
        )
        st.altair_chart(norm_chart + baseline, use_container_width=True)
    else:
        st.caption("Price history unavailable.")

st.space("small")

# ── Section 3 — Sentiment + Analysts side-by-side via tabs ───────────────
tab_sent, tab_analyst = st.tabs([
    ":material/psychology: Sentiment",
    ":material/groups: Analysts",
])

with tab_sent:
    sent_cols = st.columns(len(ticker_data), gap="medium")
    for col, td in zip(sent_cols, ticker_data):
        s         = td["sentiment"]
        score     = s.get("score", 0.0)
        label     = s.get("label", "N/A")
        reasoning = s.get("reasoning", "—")
        lcolour   = "green" if label == "Bullish" else "red" if label == "Bearish" else "gray"
        with col:
            with st.container(border=True):
                h_row, b_row = st.columns([3, 1], vertical_alignment="center")
                with h_row:
                    st.markdown(f"**{td['ticker']}**")
                with b_row:
                    st.badge(label, color=lcolour)
                st.progress((score + 1) / 2,
                            text=f"{score:+.2f}  ·  Bearish ◀──▶ Bullish")
                st.caption(f"*{reasoning}*")
                if s.get("bull_headlines"):
                    with st.expander("Bull headlines", icon=":material/trending_up:",
                                     expanded=False):
                        for h in s["bull_headlines"]:
                            st.caption(f"• {h}")
                if s.get("bear_headlines"):
                    with st.expander("Bear headlines", icon=":material/trending_down:",
                                     expanded=False):
                        for h in s["bear_headlines"]:
                            st.caption(f"• {h}")

with tab_analyst:
    rec_labels  = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    rec_keys    = ["strongBuy",  "buy", "hold", "sell", "strongSell"]
    rec_colours = ["#34D399", "#86EFAC", "#FBBF24", "#F87171", "#EF4444"]

    analyst_cols = st.columns(len(ticker_data), gap="medium")
    for col, td in zip(analyst_cols, ticker_data):
        analyst = td["analyst"]
        counts  = [analyst.get(k, 0) for k in rec_keys]
        rec_df  = pd.DataFrame({"Rating": rec_labels, "Count": counts})
        with col:
            with st.container(border=True):
                st.markdown(f"**{td['ticker']}**")
                if sum(counts) > 0:
                    bar = (
                        alt.Chart(rec_df)
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            y=alt.Y("Rating:N", sort=rec_labels, title=None,
                                    axis=alt.Axis(labelLimit=80)),
                            x=alt.X("Count:Q", title=None,
                                    axis=alt.Axis(tickMinStep=1)),
                            color=alt.Color(
                                "Rating:N",
                                scale=alt.Scale(domain=rec_labels, range=rec_colours),
                                legend=None,
                            ),
                            tooltip=["Rating:N", "Count:Q"],
                        )
                        # No fixed height — let use_container_width scale it
                        .properties(height=160)
                    )
                    st.altair_chart(bar, use_container_width=True)
                else:
                    st.caption("No analyst data.")

st.space("small")

# ── Section 4 — Claude's verdict ─────────────────────────────────────────
with st.container(border=True):
    v_head, v_badge = st.columns([5, 1], vertical_alignment="center")
    with v_head:
        st.subheader(":material/auto_awesome: Claude's verdict", divider=False)
    with v_badge:
        if portfolio_df is not None:
            st.badge("Portfolio-aware", color="violet",
                     icon=":material/pie_chart:")
        else:
            st.badge("No portfolio", color="gray")

    with st.spinner("Generating verdict…"):
        verdict = generate_comparison_verdict(
            tickers=tickers,
            ticker_data=[
                {"ticker": td["ticker"], "info": td["info"],
                 "analyst": td["analyst"], "sentiment": td["sentiment"]}
                for td in ticker_data
            ],
            portfolio_context=portfolio_context,
        )
    st.space("small")
    st.write(verdict)
