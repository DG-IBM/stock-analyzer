"""Recommendations page — filters form → Generate button → results."""
import streamlit as st
import pandas as pd
import altair as alt

from modules.recommendations import get_recommendations, apply_filters, RISK_LEVELS

st.header(":material/recommend: Recommendations")

# ── Guard — portfolio must be loaded ─────────────────────────────────────
if st.session_state.get("portfolio") is None:
    st.info(
        "No portfolio loaded yet. Go to the **Portfolio** page and upload your holdings file first.",
        icon=":material/info:",
    )
    st.stop()

portfolio_df: pd.DataFrame = st.session_state["portfolio"]

# ── Filters form ──────────────────────────────────────────────────────────
with st.form("rec_filters"):
    st.markdown("**:material/tune: Configure filters, then generate recommendations**")

    f1, f2, f3 = st.columns(3)

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
        min_score = st.slider(
            "Min sentiment score",
            min_value=-1.0,
            max_value=1.0,
            value=0.0,
            step=0.05,
            format="%.2f",
            help="-1 = show all · 0 = neutral or better · 0.5+ = strongly bullish only",
        )

    with f3:
        selected_risk = st.pills(
            "Risk level",
            options=RISK_LEVELS,
            selection_mode="multi",
            default=RISK_LEVELS,
            help="Based on beta: Low <0.8 · Medium 0.8–1.2 · High 1.2–1.8 · Extreme >1.8",
        )

    generate = st.form_submit_button(
        ":material/bolt: Generate Recommendations",
        type="primary",
        use_container_width=True,
    )

# ── Nothing shown until the button is clicked ─────────────────────────────
if not generate and "rec_has_results" not in st.session_state:
    st.info(
        "Set your filters above and click **Generate Recommendations** to run the analysis.",
        icon=":material/info:",
    )
    st.stop()

# ── On submit: snapshot filter values into session state ─────────────────
# Use a different key ("rec_saved_filters") — never the same as the form key.
if generate:
    st.session_state["rec_has_results"] = True
    st.session_state["rec_saved_filters"] = {
        "max_price": float(max_price),
        "min_score": float(min_score),
        "selected_risk": list(selected_risk) if selected_risk else RISK_LEVELS,
    }

saved_filters = st.session_state.get("rec_saved_filters", {})
_max_price = saved_filters.get("max_price", 500.0)
_min_score = saved_filters.get("min_score", 0.1)
_risk = saved_filters.get("selected_risk", RISK_LEVELS)

# ── Generate (cached by portfolio tickers) ────────────────────────────────
prog_slot = st.empty()
with prog_slot:
    with st.spinner("Fetching news and scoring sentiment… this runs ~5–6 Claude calls instead of 80."):
        similar_df_raw, diversify_df_raw = get_recommendations(portfolio_df)
prog_slot.empty()

# ── Apply filters ─────────────────────────────────────────────────────────
filter_kwargs = dict(
    max_price=_max_price,
    risk_levels=_risk,
    min_score=_min_score,
    sectors=None,
)
similar_df = apply_filters(similar_df_raw, **filter_kwargs)
diversify_df = apply_filters(diversify_df_raw, **filter_kwargs)

# ── Summary KPI strip ─────────────────────────────────────────────────────
total_picks = len(similar_df) + len(diversify_df)
all_picks_combined = pd.concat([similar_df, diversify_df], ignore_index=True)
avg_score = all_picks_combined["Score"].mean() if total_picks > 0 else 0.0
avg_upside_s = all_picks_combined["% to Target"].dropna()
avg_upside = avg_upside_s.mean() if not avg_upside_s.empty else None

with st.container(horizontal=True):
    st.metric("Total picks", str(total_picks), border=True)
    st.metric("Avg sentiment", f"{avg_score:+.2f}" if total_picks else "—", border=True)
    st.metric(
        "Avg upside to target",
        f"{avg_upside:+.1f}%" if avg_upside is not None else "—",
        border=True,
    )
    st.metric("Similar", str(len(similar_df)), border=True)
    st.metric("Diversify", str(len(diversify_df)), border=True)

st.divider()

# ── Column config & order shared across both panels ───────────────────────
_COL_CONFIG = {
    "Score": st.column_config.NumberColumn("Sentiment", format="%.2f", min_value=-1.0, max_value=1.0),
    "Price": st.column_config.NumberColumn(format="$%.2f"),
    "Beta": st.column_config.NumberColumn(format="%.2f"),
    "% to Target": st.column_config.NumberColumn("↑ Target %", format="%.1f%%"),
    "Why": st.column_config.TextColumn("Why", width="large"),
    "Label": st.column_config.TextColumn("Signal"),
    "Risk": st.column_config.TextColumn("Risk"),
}
_COL_ORDER = ["Ticker", "Sector", "Industry", "Price", "Beta", "Risk", "Score", "Label", "% to Target", "Why"]


def _render_panel(title: str, icon: str, df: pd.DataFrame) -> None:
    with st.container(border=True):
        st.markdown(f"**{icon} {title}** — {len(df)} picks")
        if df.empty:
            st.info("No picks match the current filters.")
            return
        st.dataframe(
            df,
            hide_index=True,
            use_container_width=True,
            column_config=_COL_CONFIG,
            column_order=_COL_ORDER,
        )


left, right = st.columns(2, gap="medium")
with left:
    _render_panel("Similar Picks", ":material/join_inner:", similar_df)
with right:
    _render_panel("Diversify Picks", ":material/device_hub:", diversify_df)

st.divider()

# ── Sentiment distribution chart ──────────────────────────────────────────
all_picks = pd.concat([
    similar_df.assign(Type="Similar"),
    diversify_df.assign(Type="Diversify"),
], ignore_index=True)

if not all_picks.empty:
    with st.container(border=True):
        st.markdown("**Sentiment distribution across picks**")
        hist = (
            alt.Chart(all_picks)
            .mark_bar(opacity=0.8, binSpacing=2)
            .encode(
                x=alt.X("Score:Q", bin=alt.Bin(maxbins=20), title="Sentiment score"),
                y=alt.Y("count():Q", title="# picks"),
                color=alt.Color("Type:N", scale=alt.Scale(range=["#60A5FA", "#34D399"])),
                tooltip=["Type:N", "count():Q"],
            )
            .properties(height=200)
        )
        st.altair_chart(hist, use_container_width=True)

# ── Risk breakdown chart ──────────────────────────────────────────────────
if not all_picks.empty and "Risk" in all_picks.columns:
    risk_counts = (
        all_picks.groupby(["Risk", "Type"])
        .size()
        .reset_index(name="Count")
    )
    with st.container(border=True):
        st.markdown("**Risk breakdown**")
        risk_chart = (
            alt.Chart(risk_counts)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
            .encode(
                y=alt.Y("Risk:N", sort=RISK_LEVELS, title=None),
                x=alt.X("Count:Q", title="# picks"),
                color=alt.Color(
                    "Risk:N",
                    scale=alt.Scale(
                        domain=RISK_LEVELS,
                        range=["#34D399", "#FBBF24", "#FB923C", "#F87171"],
                    ),
                    legend=None,
                ),
                column=alt.Column("Type:N", title=None),
                tooltip=["Risk:N", "Type:N", "Count:Q"],
            )
            .properties(height=150)
        )
        st.altair_chart(risk_chart)

# ── Portfolio context expander ────────────────────────────────────────────
with st.expander("Portfolio context used for these recommendations", expanded=False):
    sector_summary = (
        portfolio_df.groupby("Sector")["Market Value"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"Market Value": "Total Value"})
    )
    st.markdown("**Your sector exposure:**")
    st.dataframe(
        sector_summary,
        hide_index=True,
        use_container_width=True,
        column_config={"Total Value": st.column_config.NumberColumn(format="$%,.0f")},
    )
