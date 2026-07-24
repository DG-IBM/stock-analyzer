"""Portfolio page — upload Excel, view holdings and sector allocation."""
import streamlit as st
import altair as alt
import pandas as pd

from modules.data import load_portfolio

st.header(":material/pie_chart: Portfolio")

# ── File upload ────────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "Upload your holdings file",
    type=["xlsx"],
    help="Excel file with columns: Ticker, Shares",
    label_visibility="collapsed",
)

if uploaded is not None:
    try:
        with st.spinner("Loading portfolio…"):
            df = load_portfolio(uploaded.read())
        st.session_state["portfolio"] = df

        # Surface any tickers that failed enrichment
        failed = getattr(df, "_failed_tickers", [])
        if failed:
            st.warning(f"Could not enrich the following tickers (skipped): {', '.join(failed)}")

    except ValueError as exc:
        st.error(str(exc))
        st.stop()

if st.session_state.get("portfolio") is None:
    st.info(
        "Upload an `.xlsx` file above. The file needs a **Ticker** column and a **Shares** column.",
        icon=":material/upload_file:",
    )
    st.stop()

df: pd.DataFrame = st.session_state["portfolio"]

# ── KPI strip ──────────────────────────────────────────────────────────────
total_value = df["Market Value"].sum()
num_holdings = len(df)
num_sectors = df["Sector"].nunique()
top_holding = df.loc[df["Market Value"].idxmax(), "Ticker"]

with st.container(horizontal=True):
    st.metric("Total Value", f"${total_value:,.0f}", border=True)
    st.metric("Holdings", str(num_holdings), border=True)
    st.metric("Sectors", str(num_sectors), border=True)
    st.metric("Top Holding", top_holding, border=True)

st.divider()

# ── Holdings table ─────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**Holdings**")
    display_df = df[
        ["Ticker", "Shares", "Sector", "Industry", "Current Price", "Market Value", "% of Portfolio"]
    ].copy()

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Current Price": st.column_config.NumberColumn(format="$%.2f"),
            "Market Value": st.column_config.NumberColumn(format="$%,.0f"),
            "% of Portfolio": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

st.divider()

# ── Sector allocation chart ────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**Sector Allocation**")

    sector_df = (
        df.groupby("Sector", as_index=False)["Market Value"]
        .sum()
        .rename(columns={"Market Value": "Value"})
        .sort_values("Value", ascending=False)
    )
    sector_df["Pct"] = sector_df["Value"] / sector_df["Value"].sum() * 100
    sector_df["Label"] = sector_df.apply(
        lambda r: f"{r['Sector']}\n{r['Pct']:.1f}%", axis=1
    )

    base = alt.Chart(sector_df).encode(
        theta=alt.Theta("Value:Q", stack=True),
        color=alt.Color(
            "Sector:N",
            scale=alt.Scale(
                scheme="tableau10",
            ),
            legend=alt.Legend(title="Sector", orient="right"),
        ),
        tooltip=[
            alt.Tooltip("Sector:N"),
            alt.Tooltip("Value:Q", format="$,.0f", title="Market Value"),
            alt.Tooltip("Pct:Q", format=".1f", title="% of Portfolio"),
        ],
    )

    pie = base.mark_arc(innerRadius=60, outerRadius=130)
    text = base.mark_text(radius=155, size=11).encode(
        text=alt.condition(
            alt.datum.Pct > 4,
            alt.value(""),   # hide tiny slice labels
            alt.value(""),
        )
    )

    chart = (pie + text).properties(height=320)
    st.altair_chart(chart, use_container_width=True)
