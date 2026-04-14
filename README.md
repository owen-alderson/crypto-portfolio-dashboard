# crypto-portfolio-dashboard

A live crypto portfolio tracker built with Streamlit. Track your XRP, RLUSD, BTC, ETH and more — see real-time prices, 24h changes, price history charts, and portfolio allocation. No API key required.

![Dashboard preview](https://img.shields.io/badge/built%20with-Streamlit-FF4B4B) ![CoinGecko](https://img.shields.io/badge/data-CoinGecko-8DC63F)

## Features

- **Live prices** — pulls from CoinGecko's free public API, refreshes every 60s
- **Portfolio overview** — total value and 24h change in dollars and percent
- **Asset cards** — price, 24h change, and holding value per asset
- **Price history chart** — 7, 30, or 90 day view with fill chart
- **Allocation pie chart** — see how your portfolio is distributed
- **Editable holdings** — update amounts directly in the sidebar, saved to `portfolio.json`

## Supported assets

| Symbol | Name |
|---|---|
| BTC | Bitcoin |
| XRP | XRP |
| ETH | Ethereum |
| RLUSD | Ripple USD |
| SOL | Solana |
| ADA | Cardano |

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/owen-alderson/crypto-portfolio-dashboard.git
cd crypto-portfolio-dashboard
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Run the app**
```bash
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

## Customizing your holdings

Edit the amounts in the sidebar and click **Save Holdings** — your portfolio is stored in `portfolio.json`. Default values are set as placeholders; change them to your actual holdings.

You can also edit `portfolio.json` directly:
```json
{
  "holdings": {
    "bitcoin": 0.5,
    "ripple": 5000,
    "ethereum": 2.0,
    "ripple-usd": 1000
  }
}
```

## Requirements

- Python 3.8+
- Internet connection (for live CoinGecko data)
