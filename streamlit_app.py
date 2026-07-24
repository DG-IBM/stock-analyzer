import streamlit as st

st.set_page_config(
    page_title="Stock Analyzer",
    page_icon=":material/candlestick_chart:",
    layout="wide",
)

# Shared session state initialised once, before any page runs
if "portfolio" not in st.session_state:
    st.session_state["portfolio"] = None

page = st.navigation(
    [
        st.Page("app_pages/portfolio.py", title="Portfolio", icon=":material/pie_chart:"),
        st.Page("app_pages/recommendations.py", title="Recommendations", icon=":material/recommend:"),
        st.Page("app_pages/stock_analysis.py", title="Stock Analysis", icon=":material/candlestick_chart:"),
    ],
    position="top",
)

page.run()
