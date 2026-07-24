# Stock Analyzer

A Streamlit app that turns your holdings spreadsheet into a live portfolio dashboard, generates AI-powered stock recommendations, and delivers deep single-ticker analysis — all powered by **yfinance**, **Yahoo Finance RSS**, and **Claude claude-sonnet-4-5** via the IBM ICA gateway.

---

## Features

### Portfolio
- Upload an Excel file (`Ticker`, `Shares` columns) and instantly see your holdings enriched with live prices, sectors, and industries from yfinance.
- KPI strip: total portfolio value, number of holdings, number of sectors, top holding.
- Holdings table with market value and portfolio weight per position.
- Sector allocation donut chart with a breakdown table.
- Persistent sidebar snapshot (total value, top 5 positions) visible on every page.

### Recommendations
- Configure a max price and risk level filter, then click **Generate recommendations**.
- The engine scores ~80 liquid tickers across all 11 GICS sectors against live news sentiment via Claude.
- **Similar picks** — bullish stocks in the same sectors/industries as your holdings.
- **Diversify picks** — bullish stocks in sectors you are underweight or absent from.
- Each pick includes: price, beta, risk label (Low / Medium / High / Extreme), sentiment score, analyst upside to target, and a Claude-written one-sentence rationale that considers your portfolio context.
- Sentiment distribution histogram and risk breakdown chart across all picks.

### Stock Analysis
- Enter any ticker to get a full breakdown across four tabs:
  - **Price** — area chart with period selector (1mo / 3mo / 6mo / 1y / 2y).
  - **Sentiment** — Claude-scored sentiment (-1 to +1), label badge, and one-sentence reasoning.
  - **Analysts** — recommendation count metrics (Strong Buy → Strong Sell) and a horizontal bar chart.
  - **Bull vs Bear** — Claude-written 2–3 sentence bull case and bear case with supporting headlines.

### Compare
- Enter 2–3 tickers side by side.
- Normalised price chart (indexed to 100 at the start of the period).
- Per-ticker sentiment breakdown with expandable headline lists.
- Per-ticker analyst bar charts.
- **Claude's verdict** — a 3–4 sentence prose recommendation for which stock is the best buy right now, with full awareness of your current portfolio if one is loaded.

---

## Tech stack

| Layer | Library / Service |
|-------|------------------|
| UI | [Streamlit](https://streamlit.io) |
| Price & fundamental data | [yfinance](https://github.com/ranaroussi/yfinance) |
| News headlines | Yahoo Finance RSS (no API key required) |
| Sentiment & narrative | Claude claude-sonnet-4-5 via IBM ICA gateway |
| Charts | [Altair](https://altair-viz.github.io) ≥ 5.5 |
| Data wrangling | pandas, openpyxl |
| LLM client | openai SDK (OpenAI-compatible, pointed at ICA) |

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd stock-analyzer
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your ICA credentials:

```bash
cp .env.example .env
```

```env
ICA_BASE_URL=https://api.nextgen-beta.ica.ibm.com/ica/v1/chat-models
ICA_API_KEY=your-ica-api-key-here
ICA_MODEL=claude-sonnet-4-5
```

> `.env` is listed in `.gitignore` and will never be committed.

### 3. Run the app

```bash
streamlit run streamlit_app.py
```

The app opens at `http://localhost:8501`.

---

## Excel file format

The Portfolio page expects an `.xlsx` file with at minimum these two columns (names are case-insensitive):

| Ticker | Shares |
|--------|--------|
| AAPL   | 10     |
| MSFT   | 5      |
| NVDA   | 3      |

Additional columns are ignored. Tickers that yfinance cannot resolve are skipped with a warning.

---

## Project structure

```
stock-analyzer/
├── streamlit_app.py          # Entry point — navigation, sidebar portfolio snapshot
├── requirements.txt
├── .env.example              # ICA credentials template
├── .gitignore
├── .streamlit/
│   └── config.toml           # Financial dashboard dark theme (Inter font)
├── app_pages/
│   ├── portfolio.py          # Portfolio upload, KPIs, holdings table, sector chart
│   ├── recommendations.py    # Filters form, similar/diversify panels, charts
│   ├── stock_analysis.py     # Single-ticker deep-dive (price, sentiment, analysts, bull/bear)
│   └── compare.py            # Side-by-side ticker comparison with Claude verdict
└── modules/
    ├── __init__.py
    ├── llm.py                # OpenAI-compatible client → IBM ICA gateway
    ├── data.py               # yfinance + RSS fetching, all cached with st.cache_data
    ├── sentiment.py          # Claude sentiment scoring, bull/bear narrative, comparison verdict
    └── recommendations.py    # Similar/Diversify engine, risk classification, apply_filters()
```

---

## Architecture

```
Excel upload
    → modules/data.load_portfolio          (yfinance enrichment, parallel)
    → session_state["portfolio"]
    → modules/recommendations.get_recommendations
        → data.get_universe_df             (80 tickers, parallel yfinance calls)
        → sentiment.score_tickers_bulk
            → data.fetch_news_headlines    (Yahoo Finance RSS, parallel)
            → Claude: batch sentiment JSON ← ~6 API calls for 80 tickers
        → recommendations.generate_why    (Claude: one-sentence rationale per pick)
    → app_pages/recommendations

Ticker input (Stock Analysis / Compare)
    → data.get_ticker_info + get_analyst_data + get_price_history   (parallel)
    → sentiment.score_ticker              (Claude: score + label + reasoning)
    → sentiment.generate_bull_bear_narrative  (Claude: bull/bear paragraphs)
    → app_pages/stock_analysis or compare
```

### Claude API calls summary

| Call | Where | Input | Max tokens |
|------|-------|-------|-----------|
| Batch sentiment scoring | `sentiment._score_batch` | Up to 8 tickers × 10 headlines each | 200 × batch size |
| Single-ticker sentiment | `sentiment.score_ticker` | Up to 20 headlines | 512 |
| Bull / Bear narrative | `sentiment.generate_bull_bear_narrative` | Top bull + bear headlines | 400 |
| Recommendation rationale | `recommendations.generate_why` | Ticker metadata + portfolio sectors | 80 |
| Comparison verdict | `sentiment.generate_comparison_verdict` | 2–3 tickers' full data + portfolio context | 350 |

### Caching strategy

| Data | TTL | Notes |
|------|-----|-------|
| Portfolio enrichment | 1 hour | Per uploaded file bytes |
| Universe (80 tickers) | 1 hour | Invalidates on app restart |
| Single-ticker info / analyst / history | 5 min | `max_entries=50` |
| News headlines | 15 min | `max_entries=100` |
| Claude sentiment | 15 min | `max_entries=100` |
| Claude bull/bear narrative | 15 min | `max_entries=50` |
| Claude recommendation rationale | 1 hour | `max_entries=200` |
| Claude comparison verdict | 15 min | `max_entries=50` |

---

## Risk classification

Beta values from yfinance are mapped to four risk labels:

| Label   | Beta range |
|---------|-----------|
| Low     | < 0.8     |
| Medium  | 0.8 – 1.2 |
| High    | 1.2 – 1.8 |
| Extreme | > 1.8     |

---

## Candidate universe

The recommendation engine scores a curated list of ~80 large-cap liquid tickers across all 11 GICS sectors. Sector and industry metadata is fetched live from yfinance at runtime — nothing is hard-coded. The list covers:

Technology · Financials · Healthcare · Consumer Discretionary · Consumer Staples · Energy · Industrials · Utilities · Real Estate · Materials · Communication Services

---

## Notes

- **No market scan** — recommendations are drawn from the ~80 curated candidate tickers, not the full market. The list is defined in `modules/data.py` as `CANDIDATE_TICKERS` and can be extended.
- **Not financial advice** — all output is for informational purposes only.
- **ICA gateway** — the app uses the IBM ICA OpenAI-compatible endpoint. Any endpoint that accepts the standard `/chat/completions` format and `Authorization: Bearer` header will work; update `ICA_BASE_URL`, `ICA_API_KEY`, and `ICA_MODEL` in `.env`.
