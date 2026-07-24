"""Stock Analysis page — deep-dive on a single ticker."""
import streamlit as st
import altair as alt
import pandas as pd

from modules.data import get_ticker_info, get_analyst_data, get_price_history
from modules.sentiment import score_ticker, generate_bull_bear_narrative

st.header(":material/candlestick_chart: Stock Analysis")

ticker_input = st.text_input(
    "Enter a ticker symbol",
    placeholder="e.g. AAPL, MSFT, TSLA",
    label_visibility="collapsed",
).strip().upper()

if not ticker_input:
    st.info("Enter a ticker symbol above to begin analysis.", icon=":material/search:")
    st.stop()


@st.fragment
def render_analysis(ticker: str) -> None:
    with st.spinner(f"Analysing {ticker}…"):
        info = get_ticker_info(ticker)
        analyst = get_analyst_data(ticker)
        history = get_price_history(ticker, period="6mo")
        sentiment = score_ticker(ticker)

    if not info:
        st.error(f"Could not find data for **{ticker}**. Check the symbol and try again.")
        return

    company_name = info.get("longName") or info.get("shortName") or ticker
    st.subheader(f"{company_name} ({ticker})")
    st.caption(f"{info.get('sector', '')} · {info.get('industry', '')}")

    # ── Row 1 — Key metrics ────────────────────────────────────────────────
    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    high_52 = info.get("fiftyTwoWeekHigh") or 0.0
    low_52 = info.get("fiftyTwoWeekLow") or 0.0
    target = analyst.get("targetMeanPrice")
    rec_key = (analyst.get("recommendationKey") or "N/A").replace("_", " ").title()

    with st.container(horizontal=True):
        st.metric("Current Price", f"${price:,.2f}", border=True)
        st.metric("52-Week High", f"${high_52:,.2f}", border=True)
        st.metric("52-Week Low", f"${low_52:,.2f}", border=True)
        st.metric(
            "Consensus Target",
            f"${target:,.2f}" if target else "N/A",
            delta=f"{(target - price) / price * 100:+.1f}%" if target and price else None,
            border=True,
        )
        st.metric("Analyst Rec.", rec_key, border=True)

    st.divider()

    # ── Row 2 — Price chart ────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**6-month price history**")
        if not history.empty:
            chart = (
                alt.Chart(history)
                .mark_line(color="#60A5FA", strokeWidth=2)
                .encode(
                    x=alt.X("Date:T", title="Date", axis=alt.Axis(format="%b %Y")),
                    y=alt.Y(
                        "Close:Q",
                        title="Price (USD)",
                        scale=alt.Scale(zero=False),
                    ),
                    tooltip=[
                        alt.Tooltip("Date:T", format="%b %d, %Y"),
                        alt.Tooltip("Close:Q", format="$.2f", title="Close"),
                        alt.Tooltip("Volume:Q", format=",", title="Volume"),
                    ],
                )
                .properties(height=280)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.warning("Price history unavailable.")

    st.divider()

    # ── Row 3 — Sentiment ──────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Sentiment**")
        score = sentiment["score"]
        label = sentiment["label"]
        reasoning = sentiment["reasoning"]

        label_colour = (
            ":green" if label == "Bullish" else ":red" if label == "Bearish" else ":gray"
        )
        col_label, col_bar = st.columns([1, 3])
        with col_label:
            st.metric("Sentiment Score", f"{score:+.2f}")
            st.markdown(f"{label_colour}[**{label}**]")
        with col_bar:
            # Normalise score to 0-1 for st.progress
            st.write("")  # vertical spacer
            st.progress(
                (score + 1) / 2,
                text=f"Bearish ←{'─' * 20}→ Bullish",
            )
        st.caption(f"*{reasoning}*")

    st.divider()

    # ── Row 4 — Analyst breakdown ──────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Analyst recommendations**")
        rec_labels = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
        rec_keys = ["strongBuy", "buy", "hold", "sell", "strongSell"]
        rec_colours = ["#34D399", "#86EFAC", "#FBBF24", "#F87171", "#EF4444"]

        rec_data = pd.DataFrame({
            "Rating": rec_labels,
            "Count": [analyst.get(k, 0) for k in rec_keys],
            "Color": rec_colours,
        })

        total_recs = rec_data["Count"].sum()
        if total_recs > 0:
            bar = (
                alt.Chart(rec_data)
                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                .encode(
                    y=alt.Y(
                        "Rating:N",
                        sort=rec_labels,
                        title=None,
                        axis=alt.Axis(labelFontSize=12),
                    ),
                    x=alt.X("Count:Q", title="Number of analysts"),
                    color=alt.Color(
                        "Rating:N",
                        scale=alt.Scale(domain=rec_labels, range=rec_colours),
                        legend=None,
                    ),
                    tooltip=["Rating:N", "Count:Q"],
                )
                .properties(height=180)
            )
            st.altair_chart(bar, use_container_width=True)
        else:
            st.info("No analyst recommendations available.")

    st.divider()

    # ── Row 5 — Bull vs. Bear ──────────────────────────────────────────────
    with st.spinner("Generating bull & bear case…"):
        narrative = generate_bull_bear_narrative(
            ticker,
            sentiment.get("bull_headlines", []),
            sentiment.get("bear_headlines", []),
        )

    bull_col, bear_col = st.columns(2, gap="medium")

    with bull_col:
        with st.container(border=True):
            st.markdown("**:green[Bull Case]**")
            st.write(narrative["bull"])
            headlines = sentiment.get("bull_headlines", [])
            if headlines:
                st.markdown("*Supporting headlines:*")
                for h in headlines:
                    st.caption(f"• {h}")

    with bear_col:
        with st.container(border=True):
            st.markdown("**:red[Bear Case]**")
            st.write(narrative["bear"])
            headlines = sentiment.get("bear_headlines", [])
            if headlines:
                st.markdown("*Supporting headlines:*")
                for h in headlines:
                    st.caption(f"• {h}")


render_analysis(ticker_input)
