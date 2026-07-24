"""Stock Analysis page — deep-dive on a single ticker."""
import streamlit as st
import altair as alt
import pandas as pd

from modules.data import get_ticker_info, get_analyst_data, get_price_history
from modules.sentiment import score_ticker, generate_bull_bear_narrative

st.title(":material/candlestick_chart: Stock analysis")
st.caption("Enter any ticker for price history, sentiment, analyst consensus, and a bull vs bear breakdown.")

# ── Ticker input ───────────────────────────────────────────────────────────
ticker_input = st.text_input(
    "Ticker",
    placeholder="e.g. AAPL, MSFT, TSLA",
    label_visibility="collapsed",
).strip().upper()

if not ticker_input:
    st.space("medium")
    with st.container(border=True):
        st.markdown(":material/search: Enter a ticker symbol above to begin.")
    st.stop()


@st.fragment
def render_analysis(ticker: str) -> None:
    with st.spinner(f"Loading {ticker}…"):
        info      = get_ticker_info(ticker)
        analyst   = get_analyst_data(ticker)
        history   = get_price_history(ticker, period="6mo")
        sentiment = score_ticker(ticker)

    if not info:
        st.error(f"No data found for **{ticker}**. Check the symbol and try again.",
                 icon=":material/error:")
        return

    # ── Page header ────────────────────────────────────────────────────────
    company = info.get("longName") or info.get("shortName") or ticker
    sector  = info.get("sector", "")
    industry = info.get("industry", "")

    h_col, badge_col = st.columns([5, 1], vertical_alignment="bottom")
    with h_col:
        st.subheader(f"{company} ({ticker})")
        st.caption(f"{sector}  ·  {industry}")
    with badge_col:
        label      = sentiment.get("label", "Neutral")
        badge_col_name = "green" if label == "Bullish" else "red" if label == "Bearish" else "gray"
        st.badge(label, color=badge_col_name)

    st.space("small")

    # ── Row 1 — Key metrics ────────────────────────────────────────────────
    price  = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    high52 = info.get("fiftyTwoWeekHigh") or 0.0
    low52  = info.get("fiftyTwoWeekLow") or 0.0
    target = analyst.get("targetMeanPrice")
    rec    = (analyst.get("recommendationKey") or "N/A").replace("_", " ").title()
    upside = f"{(target - price) / price * 100:+.1f}%" if target and price else None

    with st.container(horizontal=True):
        st.metric("Price",            f"${price:,.2f}",              border=True)
        st.metric("52-week high",     f"${high52:,.2f}",             border=True)
        st.metric("52-week low",      f"${low52:,.2f}",              border=True)
        st.metric("Consensus target", f"${target:,.2f}" if target else "N/A",
                  delta=upside, border=True)
        st.metric("Analyst rec",      rec,                           border=True)

    st.space("small")

    # ── Tabs for the rest ──────────────────────────────────────────────────
    tab_price, tab_sentiment, tab_analyst, tab_bull_bear = st.tabs([
        ":material/show_chart: Price",
        ":material/psychology: Sentiment",
        ":material/groups: Analysts",
        ":material/balance: Bull vs Bear",
    ])

    # ── Price chart ────────────────────────────────────────────────────────
    with tab_price:
        period_choice = st.segmented_control(
            "Period",
            options=["1mo", "3mo", "6mo", "1y", "2y"],
            default="6mo",
            key=f"period_{ticker}",
        )
        hist = get_price_history(ticker, period=period_choice or "6mo")
        if not hist.empty:
            line = (
                alt.Chart(hist)
                .mark_area(
                    line={"color": "#60A5FA", "strokeWidth": 2},
                    color=alt.Gradient(
                        gradient="linear",
                        stops=[
                            alt.GradientStop(color="#60A5FA44", offset=0),
                            alt.GradientStop(color="#60A5FA00", offset=1),
                        ],
                        x1=1, x2=1, y1=1, y2=0,
                    ),
                )
                .encode(
                    x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %Y")),
                    y=alt.Y("Close:Q", title="Price (USD)", scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip("Date:T",   format="%b %d, %Y"),
                        alt.Tooltip("Close:Q",  format="$.2f",  title="Close"),
                        alt.Tooltip("Volume:Q", format=",",     title="Volume"),
                    ],
                )
                .properties(height=300)
            )
            st.altair_chart(line, use_container_width=True)
        else:
            st.caption("Price history unavailable.")

    # ── Sentiment ──────────────────────────────────────────────────────────
    with tab_sentiment:
        score     = sentiment["score"]
        reasoning = sentiment["reasoning"]

        s_left, s_right = st.columns([1, 3], vertical_alignment="center")
        with s_left:
            st.metric("Sentiment score", f"{score:+.2f}")
            st.badge(label, color=badge_col_name)
        with s_right:
            st.progress(
                (score + 1) / 2,
                text="Bearish ◀──────────────────────▶ Bullish",
            )
        st.caption(f"*{reasoning}*")

    # ── Analyst breakdown ──────────────────────────────────────────────────
    with tab_analyst:
        rec_labels  = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
        rec_keys    = ["strongBuy", "buy", "hold", "sell", "strongSell"]
        rec_colours = ["#34D399", "#86EFAC", "#FBBF24", "#F87171", "#EF4444"]

        rec_data   = pd.DataFrame({
            "Rating": rec_labels,
            "Count":  [analyst.get(k, 0) for k in rec_keys],
        })
        total_recs = rec_data["Count"].sum()

        if total_recs > 0:
            # Summary badges
            with st.container(horizontal=True):
                for rating, key, colour in zip(rec_labels, rec_keys, rec_colours):
                    count = analyst.get(key, 0)
                    if count:
                        st.metric(rating, str(count), border=True)

            st.space("small")
            bar = (
                alt.Chart(rec_data)
                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                .encode(
                    y=alt.Y("Rating:N", sort=rec_labels, title=None,
                            axis=alt.Axis(labelFontSize=12)),
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
            st.caption("No analyst recommendations available for this ticker.")

    # ── Bull vs Bear ───────────────────────────────────────────────────────
    with tab_bull_bear:
        with st.spinner("Generating narrative…"):
            narrative = generate_bull_bear_narrative(
                ticker,
                sentiment.get("bull_headlines", []),
                sentiment.get("bear_headlines", []),
            )

        bull_col, bear_col = st.columns(2, gap="medium")

        with bull_col:
            with st.container(border=True):
                st.badge("Bull case", color="green",
                         icon=":material/trending_up:")
                st.space("small")
                st.write(narrative["bull"])
                headlines = sentiment.get("bull_headlines", [])
                if headlines:
                    st.caption("Supporting headlines")
                    for h in headlines:
                        st.caption(f"• {h}")

        with bear_col:
            with st.container(border=True):
                st.badge("Bear case", color="red",
                         icon=":material/trending_down:")
                st.space("small")
                st.write(narrative["bear"])
                headlines = sentiment.get("bear_headlines", [])
                if headlines:
                    st.caption("Supporting headlines")
                    for h in headlines:
                        st.caption(f"• {h}")


render_analysis(ticker_input)
