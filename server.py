"""
Options P&L Calculator - Backend Server
----------------------------------------
Deployed on Render.com. Fetches live stock price
and implied volatility via yfinance.
"""

import os
from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf

app = Flask(__name__)
CORS(app, origins="*")  # Allow requests from any origin (phone, browser, etc.)


@app.route("/quote/<ticker>")
def get_quote(ticker):
    """
    Returns live stock price and nearest ATM implied volatility
    for a given ticker symbol.
    """
    try:
        ticker = ticker.upper().strip()
        stock = yf.Ticker(ticker)
        info = stock.info

        # --- Current price ---
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )

        if not price:
            return jsonify({"error": f"Could not find price for {ticker}"}), 404

        # --- Implied Volatility: nearest ATM option ---
        iv = None
        try:
            expirations = stock.options
            if expirations:
                # Use the nearest expiration date
                nearest_exp = expirations[0]
                chain = stock.option_chain(nearest_exp)

                calls = chain.calls
                if not calls.empty and "impliedVolatility" in calls.columns:
                    # Find the call closest to ATM (strike nearest to current price)
                    calls = calls.copy()
                    calls["distance"] = abs(calls["strike"] - price)
                    atm_call = calls.sort_values("distance").iloc[0]
                    iv_raw = atm_call["impliedVolatility"]
                    if iv_raw and iv_raw > 0:
                        iv = round(iv_raw * 100, 1)  # Convert to percentage
        except Exception:
            pass  # IV is optional — we'll return None if unavailable

        # --- Company name for display ---
        name = info.get("shortName") or info.get("longName") or ticker

        return jsonify({
            "ticker": ticker,
            "name": name,
            "price": round(float(price), 2),
            "iv": iv,  # percentage e.g. 28.5, or null if unavailable
            "currency": info.get("currency", "USD"),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
