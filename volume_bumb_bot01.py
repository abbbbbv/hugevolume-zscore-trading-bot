import time
import math
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from binance.um_futures import UMFutures
from binance.error import ClientError

SYMBOL = "SUIUSDT"
INTERVAL = "15m"
VOLUME_THRESHOLD = 1
STOP_LOSS_PCT = 3.41
TAKE_PROFIT_PCT = 3.5
LEVERAGE = 11
API_KEY = ""
API_SECRET = ""


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')

client = UMFutures(key=API_KEY, secret=API_SECRET)

try:
    client.change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
    logging.info(f"Leverage for {SYMBOL} set to {LEVERAGE}x.")
except ClientError as error:
    logging.error(f"Failed to set leverage: {error}")

def get_precision(symbol):
    try:
        exchange_info = client.exchange_info()
        for s in exchange_info['symbols']:
            if s['symbol'] == symbol:
                qty_precision = s['quantityPrecision']
                price_precision = s['pricePrecision']
                return qty_precision, price_precision
    except ClientError as error:
        logging.error(f"Error fetching precision: {error}")
    return None, None

def fetch_historical_data(symbol, interval, lookback):
    try:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=lookback)
        klines = client.klines(symbol=symbol, interval=interval, startTime=int(start_time.timestamp() * 1000), endTime=int(end_time.timestamp() * 1000))
        df = pd.DataFrame(klines, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_time', 'Quote_asset_volume', 'Number_of_trades', 'Taker_buy_base_asset_volume', 'Taker_buy_quote_asset_volume', 'Ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        float_columns = ['Open', 'High', 'Low', 'Close', 'Volume', 'Taker_buy_base_asset_volume']
        df[float_columns] = df[float_columns].astype(float)
        return df
    except ClientError as error:
        logging.error(f"Error fetching historical data: {error}")
        return pd.DataFrame()

def detect_large_orders(df, volume_threshold):
    df['Volume_mean'] = df['Volume'].rolling(window=20).mean()
    df['Volume_std'] = df['Volume'].rolling(window=20).std()
    df['Volume_z_score'] = (df['Volume'] - df['Volume_mean']) / df['Volume_std']
    df.dropna(inplace=True)
    significant_volume = df[df['Volume_z_score'] > 2]
    large_orders = significant_volume[significant_volume['Volume'] > volume_threshold]
    large_orders['Buy_ratio'] = large_orders['Taker_buy_base_asset_volume'] / large_orders['Volume']
    large_orders['Order_type'] = large_orders['Buy_ratio'].apply(lambda x: 'BUY' if x > 0.6 else ('SELL' if x < 0.4 else 'MIXED'))
    return large_orders

def position_open():
    try:
        positions = client.account()['positions']
        for position in positions:
            if position['symbol'] == SYMBOL and float(position['positionAmt']) != 0:
                return True
    except ClientError as error:
        logging.error(f"Error checking position: {error}")
    return False

def cancel_open_orders():
    try:
        client.cancel_open_orders(symbol=SYMBOL)
    except ClientError as error:
        logging.error(f"Error canceling open orders: {error}")

def place_with_retry(order_params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.new_order(**order_params)
        except Exception as e:
            backoff = 2 ** attempt
            logging.warning(f"Attempt {attempt+1} failed: {e}. Retrying in {backoff} seconds...")
            time.sleep(backoff)
    logging.error(f"All {max_retries} attempts failed for order: {order_params}")

def place_trade(order_type):
    if position_open():
        logging.info("Position already open. Skipping.")
        return

    logging.info("Position closed. Canceling any remaining open orders...")
    cancel_open_orders()
    logging.info("Position closed and no open orders remain.")

    qty_precision, price_precision = get_precision(SYMBOL)
    if qty_precision is None or price_precision is None:
        logging.error("Could not retrieve precision information.")
        return

    try:
        balance = float(client.account()['totalWalletBalance'])
        mark_price = float(client.mark_price(symbol=SYMBOL)['markPrice'])

        qty = round((balance * LEVERAGE * 0.98) / mark_price, qty_precision)
        side = 'BUY' if order_type == 'BUY' else 'SELL'
        opposite_side = 'SELL' if side == 'BUY' else 'BUY'

        sl_price = round(mark_price * (1 - STOP_LOSS_PCT / 100), price_precision) if side == 'BUY' else round(mark_price * (1 + STOP_LOSS_PCT / 100), price_precision)
        tp_price = round(mark_price * (1 + TAKE_PROFIT_PCT / 100), price_precision) if side == 'BUY' else round(mark_price * (1 - TAKE_PROFIT_PCT / 100), price_precision)

        logging.info(f"Placing {side} order for {qty} {SYMBOL} at market...")
        place_with_retry({
            'symbol': SYMBOL,
            'side': side,
            'type': 'MARKET',
            'quantity': qty
        })

        logging.info("Placing stop-loss order...")
        place_with_retry({
            'symbol': SYMBOL,
            'side': opposite_side,
            'type': 'STOP_MARKET',
            'stopPrice': sl_price,
            'closePosition': True
        })

        logging.info("Placing take-profit order...")
        place_with_retry({
            'symbol': SYMBOL,
            'side': opposite_side,
            'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': tp_price,
            'closePosition': True
        })

        while position_open():
            time.sleep(5)

        logging.info("Position closed. Canceling any remaining open orders...")
        cancel_open_orders()
        logging.info("Position closed and no open orders remain.")

    except ClientError as error:
        logging.error(f"Trade execution failed: {error}")
    except Exception as e:
        logging.error(f"Unexpected error in place_trade: {e}")

def run_bot():
    while True:
        try:
            df = fetch_historical_data(SYMBOL, INTERVAL, lookback=1)
            if df.empty:
                logging.error("No data fetched. Retrying...")
            else:
                large_orders = detect_large_orders(df, VOLUME_THRESHOLD)

                if not large_orders.empty:
                    latest_order = large_orders.iloc[-1]
                    logging.info(f"Detected significant {latest_order['Order_type']} order at {latest_order.name}")
                    if latest_order['Order_type'] in ['BUY', 'SELL']:
                        place_trade(latest_order['Order_type'])
                    else:
                        logging.info("Mixed signal. No clear direction. Skipping.")
                else:
                    logging.info("No significant large orders found. Waiting for next check...")

        except Exception as e:
            logging.error(f"Error in run_bot: {e}")

        now = datetime.now(timezone.utc)
        next_run = now + timedelta(minutes=15 - (now.minute % 15), seconds=-now.second, microseconds=-now.microsecond)
        sleep_seconds = (next_run - now).total_seconds()
        logging.info(f"Sleeping for {int(sleep_seconds)} seconds until next 15m candle...")
        time.sleep(sleep_seconds)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
