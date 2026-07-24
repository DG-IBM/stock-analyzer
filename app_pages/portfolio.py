"""Portfolio page — upload holdings, view enriched table and sector allocation."""
import streamlit as st
import altair as alt
import pandas as pd

from modules.data import load_portfolio

st.title(":material/pie_chart: Portfolio")
st.caption("Upload your holdings file to see a live enriched breakdown.")

# ── File upload ────────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "Upload holdings",
    type=["xlsx"],
    help="Excel file with columns: Ticker, Shares",
    label_visibility="collapsed",
)

if uploaded is not None:
    try:
        with st.spinner("Enriching portfolio with live market data…"):
            df = load_portfolio(uploaded.read())
        st.session_state["portfolio"] = df
        st.toast("Portfolio loaded!", icon=":material/check_circle:")

        failed = getattr(df, "_failed_tickers", [])
        if failed:
            st.warning(
                f"Could not enrich: {', '.join(failed)}. These tickers were skipped.",
                icon=":material/warning:",
            )
    except ValueError as exc:
        st.error(str(exc), icon=":material/error:")
        st.stop()

if st.session_state.get("portfolio") is None:
    st.space("medium")
    with st.container(border=True):
        st.markdown(
            ":material/upload_file: **Get started** — upload an `.xlsx` file with a "
            "**Ticker** column and a **Shares** column."
        )
    st.stop()

df: pd.DataFrame = st.session_state["portfolio"]

# ── KPI strip ──────────────────────────────────────────────────────────────
total_value  = df["Market Value"].sum()
num_holdings = len(df)
num_sectors  = df["Sector"].nunique()
top_holding  = df.loc[df["Market Value"].idxmax(), "Ticker"]
top_pct      = df.loc[df["Market Value"].idxmax(), "% of Portfolio"]

with st.container(horizontal=True):
    st.metric("Total value",    f"${total_value:,.0f}", border=True)
    st.metric("Holdings",       str(num_holdings),       border=True)
    st.metric("Sectors",        str(num_sectors),        border=True)
    st.metric("Top holding",    top_holding,             border=True,
              help=f"{top_pct:.1f}% of portfolio")

st.space("small")

# ── Two-column layout: table left, chart right ─────────────────────────────
tbl_col, chart_col = st.columns([3, 2], gap="large")

with tbl_col:
    with st.container(border=True):
        st.subheader("Holdings", divider=False)
        display_df = df[[
            "Ticker", "Shares", "Sector", "Industry",
            "Current Price", "Market Value", "% of Portfolio",
        ]].copy()
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Current Price":  st.column_config.NumberColumn(format="$%.2f"),
                "Market Value":   st.column_config.NumberColumn(format="$%,.0f"),
                "% of Portfolio": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

with chart_col:
    with st.container(border=True):
        st.subheader("Sector allocation", divider=False)

        sector_df = (
            df.groupby("Sector", as_index=False)["Market Value"]
            .sum()
            .rename(columns={"Market Value": "Value"})
            .sort_values("Value", ascending=False)
        )
        sector_df["Pct"] = sector_df["Value"] / sector_df["Value"].sum() * 100

        base = alt.Chart(sector_df).encode(
            theta=alt.Theta("Value:Q", stack=True),
            color=alt.Color(
                "Sector:N",
                scale=alt.Scale(scheme="tableau10"),
                legend=None,   # legend replaced by the table below — no overflow risk
            ),
            tooltip=[
                alt.Tooltip("Sector:N"),
                alt.Tooltip("Value:Q",  format="$,.0f", title="Market value"),
                alt.Tooltip("Pct:Q",    format=".1f",   title="% of portfolio"),
            ],
        )

        pie = base.mark_arc(innerRadius=55, outerRadius=110)
        chart = pie.properties(height=260)
        st.altair_chart(chart, use_container_width=True)

        # Sector breakdown table below chart
        sector_tbl = sector_df[["Sector", "Value", "Pct"]].rename(
            columns={"Value": "Market value", "Pct": "%"}
        )
        st.dataframe(
            sector_tbl,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Market value": st.column_config.NumberColumn(format="$%,.0f"),
                "%":            st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
