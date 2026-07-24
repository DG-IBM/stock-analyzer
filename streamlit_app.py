import streamlit as st

st.set_page_config(
    page_title="Stock Analyzer",
    page_icon=":material/candlestick_chart:",
    layout="wide",
)

# ── Shared session state ───────────────────────────────────────────────────
if "portfolio" not in st.session_state:
    st.session_state["portfolio"] = None

# ── Sidebar — persistent portfolio snapshot ───────────────────────────────
with st.sidebar:
    st.markdown("### :material/candlestick_chart: Stock Analyzer")
    st.caption("Powered by yfinance · Claude claude-sonnet-4-5")
    st.divider()

    portfolio = st.session_state.get("portfolio")
    if portfolio is not None:
        total_val  = portfolio["Market Value"].sum()
        n_holdings = len(portfolio)
        n_sectors  = portfolio["Sector"].nunique()
        top        = portfolio.loc[portfolio["Market Value"].idxmax(), "Ticker"]

        st.caption("YOUR PORTFOLIO")
        st.metric("Total value",  f"${total_val:,.0f}")
        st.metric("Holdings",     str(n_holdings))
        st.metric("Sectors",      str(n_sectors))
        st.metric("Top holding",  top)
        st.space("small")
        st.caption("Top 5 positions")
        top5 = (
            portfolio.nlargest(5, "Market Value")[["Ticker", "% of Portfolio"]]
            .reset_index(drop=True)
        )
        for _, row in top5.iterrows():
            st.caption(f"**{row['Ticker']}** — {row['% of Portfolio']:.1f}%")
    else:
        st.caption("No portfolio loaded.")
        st.caption("Go to **Portfolio** to upload your holdings.")

page = st.navigation(
    [
        st.Page("app_pages/portfolio.py",       title="Portfolio",      icon=":material/pie_chart:"),
        st.Page("app_pages/recommendations.py", title="Recommendations", icon=":material/recommend:"),
        st.Page("app_pages/stock_analysis.py",  title="Stock analysis",  icon=":material/candlestick_chart:"),
        st.Page("app_pages/compare.py",         title="Compare",         icon=":material/compare_arrows:"),
    ],
    position="top",
)

page.run()
