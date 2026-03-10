"""
Options P&L Calculator - Backend Server
----------------------------------------
Deployed on Render.com. Fetches live stock price,
implied volatility, and options premium via yfinance.
"""

import os
import math
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf

app = Flask(__name__)
CORS(app, origins="*")


def safe_float(val):
    """Convert to float, return None if NaN, None, or invalid."""
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def safe_int(val):
    """Convert to int safely."""
    try:
        f = float(val)
        return None if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/quote/<ticker>")
def get_quote(ticker):
    """
    Returns live stock price and nearest ATM implied volatility.
    """
    try:
        ticker = ticker.upper().strip()
        stock = yf.Ticker(ticker)
        info = stock.info

        price = safe_float(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )

        if not price:
            return jsonify({"error": f"Could not find price for {ticker}"}), 404

        iv = None
        try:
            expirations = stock.options
            if expirations:
                chain = stock.option_chain(expirations[0])
                calls = chain.calls.copy()
                if not calls.empty and "impliedVolatility" in calls.columns:
                    calls["distance"] = abs(calls["strike"] - price)
                    atm = calls.sort_values("distance").iloc[0]
                    iv_raw = safe_float(atm["impliedVolatility"])
                    if iv_raw and iv_raw > 0:
                        iv = round(iv_raw * 100, 1)
        except Exception:
            pass

        name = info.get("shortName") or info.get("longName") or ticker

        return jsonify({
            "ticker": ticker,
            "name": name,
            "price": round(price, 2),
            "iv": iv,
            "currency": info.get("currency", "USD"),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/premium/<ticker>/<option_type>/<expiration>/<strike>")
def get_premium(ticker, option_type, expiration, strike):
    """
    Returns live bid/ask/mid premium for a specific contract.
    Snaps to nearest available expiration and strike automatically.
    """
    try:
        ticker = ticker.upper().strip()
        strike_requested = float(strike)
        stock = yf.Ticker(ticker)

        # --- Available expirations ---
        expirations = stock.options
        if not expirations:
            return jsonify({"error": f"No options data found for {ticker}"}), 404

        # Snap to nearest available expiration
        try:
            req_date = datetime.strptime(expiration, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": f"Invalid date format: {expiration}"}), 400

        exp_dates = []
        for e in expirations:
            try:
                exp_dates.append(datetime.strptime(e, "%Y-%m-%d"))
            except ValueError:
                continue

        if not exp_dates:
            return jsonify({"error": "Could not parse any expiration dates"}), 500

        nearest = min(exp_dates, key=lambda d: abs((d - req_date).days))
        nearest_str = nearest.strftime("%Y-%m-%d")
        days_diff = abs((nearest - req_date).days)

        # --- Fetch chain ---
        chain = stock.option_chain(nearest_str)
        df = chain.calls if option_type.lower() == "call" else chain.puts

        if df is None or df.empty:
            return jsonify({
                "error": f"No {option_type} contracts found for {ticker} expiring {nearest_str}"
            }), 404

        df = df.copy()
        df["distance"] = abs(df["strike"] - strike_requested)
        row = df.sort_values("distance").iloc[0]

        actual_strike = safe_float(row["strike"])
        bid = safe_float(row.get("bid"))
        ask = safe_float(row.get("ask"))
        last = safe_float(row.get("lastPrice"))
        iv_raw = safe_float(row.get("impliedVolatility"))
        iv = round(iv_raw * 100, 1) if iv_raw and iv_raw > 0 else None
        volume = safe_int(row.get("volume")) or 0
        open_interest = safe_int(row.get("openInterest")) or 0

        # Determine best mid price
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            mid = round((bid + ask) / 2, 2)
        elif last is not None and last > 0:
            mid = round(last, 2)
            bid = None
            ask = None
        else:
            return jsonify({
                "error": f"No valid price for {ticker} {option_type} ${actual_strike} exp {nearest_str} — contract may be illiquid or expired"
            }), 404

        return jsonify({
            "ticker": ticker,
            "option_type": option_type,
            "expiration": nearest_str,
            "expiration_requested": expiration,
            "days_diff": days_diff,
            "strike": actual_strike,
            "strike_requested": strike_requested,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "last": last,
            "iv": iv,
            "volume": volume,
            "open_interest": open_interest,
        })

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
