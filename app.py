import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

SUPPORTED_COINS = {
    "bitcoin":    {"name": "Bitcoin",  "symbol": "BTC",   "color": "#F7931A"},
    "ripple":     {"name": "XRP",      "symbol": "XRP",   "color": "#346AA9"},
    "ethereum":   {"name": "Ethereum", "symbol": "ETH",   "color": "#627EEA"},
    "ripple-usd": {"name": "RLUSD",    "symbol": "RLUSD", "color": "#00C49F"},
    "solana":     {"name": "Solana",   "symbol": "SOL",   "color": "#9945FF"},
    "cardano":    {"name": "Cardano",  "symbol": "ADA",   "color": "#0033AD"},
}

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

# ── Data loading ──────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text())
    return {"holdings": {}}


def save_portfolio(holdings: dict):
    data = {"holdings": holdings}
    PORTFOLIO_FILE.write_text(json.dumps(data, indent=2))


@st.cache_data(ttl=60)
def fetch_prices(coin_ids: list[str]) -> dict:
    ids = ",".join(coin_ids)
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=300)
def fetch_history(coin_id: str, days: int) -> pd.DataFrame:
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=10,
        )
        resp.raise_for_status()
        prices = resp.json().get("prices", [])
        df = pd.DataFrame(prices, columns=["timestamp", "price"])
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df[["date", "price"]]
    except Exception:
        return pd.DataFrame(columns=["date", "price"])


# ── UI helpers ────────────────────────────────────────────────────────────────

def fmt_usd(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value:,.2f}"
    return f"${value:.4f}"


def hex_to_rgba(hex_color: str, alpha: float = 0.08) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def change_color(pct: float) -> str:
    return "#00C49F" if pct >= 0 else "#FF4B4B"


def change_arrow(pct: float) -> str:
    return "▲" if pct >= 0 else "▼"


# ── Main app ──────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Crypto Portfolio", page_icon="📈", layout="wide")

st.markdown("""
<style>
    .asset-card {
        background: #1a1a2e;
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 12px;
    }
    .asset-name { font-size: 1.1rem; font-weight: 600; color: #e0e0e0; }
    .asset-price { font-size: 1.6rem; font-weight: 700; color: #ffffff; }
    .asset-change { font-size: 0.95rem; font-weight: 500; }
    .asset-value { font-size: 0.9rem; color: #a0a0b0; margin-top: 4px; }
    .total-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #346AA9;
        border-radius: 16px;
        padding: 28px;
        margin-bottom: 24px;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar: portfolio editor ─────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Holdings")
    st.caption("Edit your holdings below and click Save.")

    portfolio = load_portfolio()
    holdings = portfolio.get("holdings", {})

    updated_holdings = {}
    for coin_id, meta in SUPPORTED_COINS.items():
        current = holdings.get(coin_id, 0.0)
        val = st.number_input(
            f"{meta['symbol']} ({meta['name']})",
            min_value=0.0,
            value=float(current),
            step=0.0001,
            format="%.4f",
            key=coin_id,
        )
        if val > 0:
            updated_holdings[coin_id] = val

    if st.button("💾 Save Holdings", use_container_width=True):
        save_portfolio(updated_holdings)
        st.success("Saved!")
        st.cache_data.clear()
        holdings = updated_holdings

    st.divider()
    timeframe = st.selectbox("Price history", ["7 days", "30 days", "90 days"], index=0)
    days_map = {"7 days": 7, "30 days": 30, "90 days": 90}
    days = days_map[timeframe]

    st.caption(f"Prices refresh every 60s · Last updated {datetime.now().strftime('%H:%M:%S')}")

# ── Fetch live data ────────────────────────────────────────────────────────────

active_coins = [c for c in holdings if c in SUPPORTED_COINS and holdings[c] > 0]

if not active_coins:
    st.info("Add holdings in the sidebar to get started.")
    st.stop()

prices_data = fetch_prices(active_coins)

# ── Portfolio summary ─────────────────────────────────────────────────────────

total_value = 0.0
total_value_yesterday = 0.0
rows = []

for coin_id in active_coins:
    meta = SUPPORTED_COINS[coin_id]
    amount = holdings[coin_id]
    price_info = prices_data.get(coin_id, {})
    price = price_info.get("usd", 0)
    change_24h = price_info.get("usd_24h_change", 0) or 0
    value = price * amount
    price_yesterday = price / (1 + change_24h / 100) if change_24h != -100 else price
    value_yesterday = price_yesterday * amount

    total_value += value
    total_value_yesterday += value_yesterday
    rows.append({
        "coin_id": coin_id,
        "name": meta["name"],
        "symbol": meta["symbol"],
        "color": meta["color"],
        "price": price,
        "change_24h": change_24h,
        "amount": amount,
        "value": value,
    })

portfolio_change_pct = ((total_value - total_value_yesterday) / total_value_yesterday * 100
                        if total_value_yesterday > 0 else 0)
portfolio_change_abs = total_value - total_value_yesterday

# ── Header ────────────────────────────────────────────────────────────────────

st.title("📈 Crypto Portfolio")

col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    change_sign = "+" if portfolio_change_abs >= 0 else ""
    color = change_color(portfolio_change_pct)
    st.markdown(f"""
    <div class="total-card">
        <div style="color:#a0a0b0; font-size:0.9rem; margin-bottom:6px;">TOTAL PORTFOLIO VALUE</div>
        <div style="font-size:2.8rem; font-weight:700; color:#ffffff;">${total_value:,.2f}</div>
        <div style="font-size:1rem; color:{color}; margin-top:4px;">
            {change_arrow(portfolio_change_pct)} {change_sign}{portfolio_change_abs:,.2f} ({change_sign}{portfolio_change_pct:.2f}%) 24h
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.metric("Assets tracked", len(active_coins))

with col3:
    best = max(rows, key=lambda r: r["change_24h"]) if rows else None
    if best:
        st.metric("Best 24h", best["symbol"], f"{best['change_24h']:+.2f}%")

st.divider()

# ── Asset cards ───────────────────────────────────────────────────────────────

st.subheader("Assets")
cols = st.columns(min(len(rows), 4))

for i, row in enumerate(rows):
    with cols[i % 4]:
        color = change_color(row["change_24h"])
        arrow = change_arrow(row["change_24h"])
        st.markdown(f"""
        <div class="asset-card">
            <div class="asset-name" style="color:{row['color']}">{row['symbol']} · {row['name']}</div>
            <div class="asset-price">{fmt_usd(row['price'])}</div>
            <div class="asset-change" style="color:{color}">{arrow} {row['change_24h']:+.2f}% (24h)</div>
            <div class="asset-value">{row['amount']:,.4f} {row['symbol']} · <b>${row['value']:,.2f}</b></div>
        </div>
        """, unsafe_allow_html=True)

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────

chart_col, pie_col = st.columns([3, 2])

with chart_col:
    st.subheader(f"Price history · {timeframe}")
    selected_coin = st.selectbox(
        "Select asset",
        options=active_coins,
        format_func=lambda c: SUPPORTED_COINS[c]["symbol"],
        label_visibility="collapsed",
    )
    hist_df = fetch_history(selected_coin, days)
    if not hist_df.empty:
        coin_color = SUPPORTED_COINS[selected_coin]["color"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist_df["date"],
            y=hist_df["price"],
            mode="lines",
            line=dict(color=coin_color, width=2),
            fill="tozeroy",
            fillcolor=hex_to_rgba(coin_color),
            name=SUPPORTED_COINS[selected_coin]["symbol"],
        ))
        fig.update_layout(
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
            font_color="#e0e0e0",
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="#1e1e2e", zeroline=False),
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Could not load price history.")

with pie_col:
    st.subheader("Allocation")
    pie_df = pd.DataFrame(rows)
    if not pie_df.empty and pie_df["value"].sum() > 0:
        fig2 = px.pie(
            pie_df,
            values="value",
            names="symbol",
            color_discrete_sequence=[r["color"] for r in rows],
            hole=0.5,
        )
        fig2.update_traces(textposition="outside", textinfo="percent+label")
        fig2.update_layout(
            paper_bgcolor="#0e1117",
            font_color="#e0e0e0",
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False,
            height=300,
        )
        st.plotly_chart(fig2, use_container_width=True)
