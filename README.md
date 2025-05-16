# Volume Bump Z-Score Trading Bot

Automated Binance Futures trading bot implementing a custom volume spike Z-score strategy. This bot detects significant volume spikes in 15-minute candles to identify buy or sell signals and executes trades with fixed take-profit and stop-loss orders. It manages positions and orders in real-time using Binance’s API.

---

## Features

- Fetches historical market data and calculates volume Z-scores to detect large orders.
- Automatically places market orders based on detected volume spikes (BUY or SELL signals).
- Implements fixed percentage-based stop-loss and take-profit orders immediately after trade execution.
- Uses symbol-specific precision for accurate order sizing and pricing.
- Manages open positions and cancels any conflicting orders to prevent overlap.
- Includes retry logic for order placement to handle temporary API failures.
- Runs continuously, executing trades on every 15-minute interval.

---

## Requirements

- Python 3.8+
- Binance Futures API key and secret with trading permissions.
- Required Python packages: `pandas`, `numpy`, `binance-connector`, `logging`

Install dependencies via pip:

```bash
pip install pandas numpy binance-connector
