"""Recommendations page — filters form → Generate button → results."""
import streamlit as st
import pandas as pd
import altair as alt

from modules.recommendations import get_recommendations, apply_filters, RISK_LEVELS

st.title(":material/recommend: Recommendations")
st.caption("Generate personalised stock picks based on your portfolio and live news sentiment.")

# ── Guard ─────────────────────────────────────────────────────────────────
if st.session_state.get("portfolio") is None:
    st.space("medium")
    with st.container(border=True):
        st.markdown(
            ":material/info: No portfolio loaded yet. Go to **Portfolio** and upload "
            "your holdings file first."
        )
    st.stop()

portfolio_df: pd.DataFrame = st.session_state["portfolio"]

# ── Filters form ──────────────────────────────────────────────────────────
with st.form("rec_filters"):
    st.caption("FILTERS")
    f1, f2 = st.columns(2)

    with f1:
        max_price = st.number_input(
            "Max price ($)",
            min_value=1.0,
            max_value=10_000.0,
            value=500.0,
            step=50.0,
            help="Only show stocks at or below this price",
        )
    with f2:
        selected_risk = st.pills(
            "Risk level",
            options=RISK_LEVELS,
            selection_mode="multi",
            default=RISK_LEVELS,
            help="Based on beta: Low <0.8 · Medium 0.8–1.2 · High 1.2–1.8 · Extreme >1.8",
        )

    generate = st.form_submit_button(
        ":material/bolt: Generate recommendations",
        type="primary",
        use_container_width=True,
    )

# ── Gate ──────────────────────────────────────────────────────────────────
if not generate and "rec_has_results" not in st.session_state:
    st.space("small")
    st.caption(":material/info: Set your filters above and click **Generate recommendations**.")
    st.stop()

if generate:
    st.session_state["rec_has_results"] = True
    st.session_state["rec_saved_filters"] = {
        "max_price":     float(max_price),
        "selected_risk": list(selected_risk) if selected_risk else RISK_LEVELS,
    }

saved  = st.session_state.get("rec_saved_filters", {})
_price = saved.get("max_price", 500.0)
_risk  = saved.get("selected_risk", RISK_LEVELS)

# ── Generate ──────────────────────────────────────────────────────────────
with st.spinner("Scoring sentiment across the market universe…"):
    similar_raw, diversify_raw = get_recommendations(portfolio_df)

similar_df   = apply_filters(similar_raw,   max_price=_price, risk_levels=_risk, min_score=-1.0, sectors=None)
diversify_df = apply_filters(diversify_raw, max_price=_price, risk_levels=_risk, min_score=-1.0, sectors=None)

# ── KPI strip ─────────────────────────────────────────────────────────────
total_picks  = len(similar_df) + len(diversify_df)
combined_all = pd.concat([similar_df, diversify_df], ignore_index=True)
avg_score    = combined_all["Score"].mean() if total_picks else 0.0
upside_s     = combined_all["% to Target"].dropna()
avg_upside   = upside_s.mean() if not upside_s.empty else None

with st.container(horizontal=True):
    st.metric("Total picks",         str(total_picks),                                 border=True)
    st.metric("Avg sentiment",       f"{avg_score:+.2f}" if total_picks else "—",      border=True)
    st.metric("Avg upside to target",f"{avg_upside:+.1f}%" if avg_upside else "—",     border=True)
    st.metric("Similar picks",       str(len(similar_df)),                             border=True)
    st.metric("Diversify picks",     str(len(diversify_df)),                           border=True)

st.space("small")

# ── Column config shared across both panels ───────────────────────────────
_COL_CFG = {
    "Score":        st.column_config.NumberColumn("Sentiment", format="%.2f",
                                                   min_value=-1.0, max_value=1.0),
    "Price":        st.column_config.NumberColumn(format="$%.2f"),
    "Beta":         st.column_config.NumberColumn(format="%.2f"),
    "% to Target":  st.column_config.NumberColumn("↑ Target %", format="%.1f%%"),
    "Why":          st.column_config.TextColumn("Why", width="large"),
    "Label":        st.column_config.TextColumn("Signal"),
    "Risk":         st.column_config.TextColumn("Risk"),
}
_COL_ORDER = ["Ticker", "Sector", "Industry", "Price", "Beta", "Risk",
              "Score", "Label", "% to Target", "Why"]


def _panel(title: str, icon: str, df: pd.DataFrame) -> None:
    with st.container(border=True):
        h_col, badge = st.columns([5, 1], vertical_alignment="center")
        with h_col:
            st.subheader(f"{icon} {title}", divider=False)
        with badge:
            st.badge(f"{len(df)} picks", color="blue" if len(df) else "gray")
        if df.empty:
            st.caption("No picks match the current filters.")
            return
        st.dataframe(
            df, hide_index=True, use_container_width=True,
            column_config=_COL_CFG, column_order=_COL_ORDER,
        )


left, right = st.columns(2, gap="medium")
with left:
    _panel("Similar picks",  ":material/join_inner:", similar_df)
with right:
    _panel("Diversify picks", ":material/device_hub:", diversify_df)

st.space("small")

# ── Charts row ────────────────────────────────────────────────────────────
all_picks = pd.concat([
    similar_df.assign(Type="Similar"),
    diversify_df.assign(Type="Diversify"),
], ignore_index=True)

if not all_picks.empty:
    c1, c2 = st.columns(2, gap="medium")

    with c1:
        with st.container(border=True):
            st.subheader("Sentiment distribution", divider=False)
            hist_chart = (
                alt.Chart(all_picks)
                .mark_bar(opacity=0.85, binSpacing=1)
                .encode(
                    x=alt.X("Score:Q", bin=alt.Bin(maxbins=20), title="Sentiment score"),
                    y=alt.Y("count():Q", title="# picks"),
                    color=alt.Color("Type:N",
                                    scale=alt.Scale(range=["#60A5FA", "#34D399"]),
                                    legend=alt.Legend(title=None, orient="top")),
                    tooltip=["Type:N", "count():Q"],
                )
                .properties(height=200)
            )
            st.altair_chart(hist_chart, use_container_width=True)

    with c2:
        if "Risk" in all_picks.columns:
            with st.container(border=True):
                st.subheader("Risk breakdown", divider=False)
                risk_counts = (
                    all_picks.groupby(["Risk", "Type"]).size()
                    .reset_index(name="Count")
                )
                # Use xOffset for grouped bars — avoids facet overflow
                risk_chart = (
                    alt.Chart(risk_counts)
                    .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                    .encode(
                        y=alt.Y("Risk:N", sort=RISK_LEVELS, title=None),
                        x=alt.X("Count:Q", title="# picks"),
                        color=alt.Color(
                            "Type:N",
                            scale=alt.Scale(range=["#60A5FA", "#34D399"]),
                            legend=alt.Legend(title=None, orient="top"),
                        ),
                        yOffset=alt.YOffset("Type:N"),
                        tooltip=["Risk:N", "Type:N", "Count:Q"],
                    )
                    .properties(height=200)
                )
                st.altair_chart(risk_chart, use_container_width=True)

# ── Portfolio context expander ────────────────────────────────────────────
with st.expander("Portfolio context", icon=":material/pie_chart:", expanded=False):
    sector_summary = (
        portfolio_df.groupby("Sector")["Market Value"]
        .sum().sort_values(ascending=False).reset_index()
        .rename(columns={"Market Value": "Total value"})
    )
    st.dataframe(
        sector_summary, hide_index=True, use_container_width=True,
        column_config={"Total value": st.column_config.NumberColumn(format="$%,.0f")},
    )
