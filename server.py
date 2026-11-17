"""
TradingView MCP Server untuk Claude
-----------------------------------
Tools:
  - tv_analysis      : Rating teknikal TradingView (BUY/SELL/NEUTRAL) + indikator
  - tv_multi_timeframe: Rating TradingView di beberapa timeframe sekaligus
  - get_quote        : Harga terkini (via Yahoo Finance)
  - get_candles      : Data OHLCV / candle (via Yahoo Finance)
  - calc_indicators  : Hitung RSI, MACD, SMA, EMA, Bollinger dari data candle

Catatan: TradingView tidak punya API publik resmi. Rating diambil lewat
library `tradingview-ta` (endpoint scanner TradingView, tidak resmi).
"""
import os
from typing import Optional

import pandas as pd
import yfinance as yf
from mcp.server.fastmcp import FastMCP
from tradingview_ta import TA_Handler, Interval, get_multiple_analysis

PORT = int(os.environ.get("PORT", "8000"))
mcp = FastMCP("TradingView", host="0.0.0.0", port=PORT, stateless_http=True)

INTERVALS = {
    "1m": Interval.INTERVAL_1_MINUTE, "5m": Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES, "30m": Interval.INTERVAL_30_MINUTES,
    "1h": Interval.INTERVAL_1_HOUR, "2h": Interval.INTERVAL_2_HOURS,
    "4h": Interval.INTERVAL_4_HOURS, "1d": Interval.INTERVAL_1_DAY,
    "1W": Interval.INTERVAL_1_WEEK, "1M": Interval.INTERVAL_1_MONTH,
}

# Default screener per exchange (agar user cukup isi symbol + exchange)
SCREENERS = {
    "IDX": "indonesia", "NASDAQ": "america", "NYSE": "america", "AMEX": "america",
    "BINANCE": "crypto", "BYBIT": "crypto", "COINBASE": "crypto", "OKX": "crypto",
    "BITSTAMP": "crypto", "KUCOIN": "crypto", "FX_IDC": "forex", "OANDA": "forex",
    "FX": "forex", "FOREXCOM": "forex", "TVC": "cfd", "COMEX": "cfd", "NYMEX": "cfd",
}


def _screener(exchange: str, screener: Optional[str]) -> str:
    return screener or SCREENERS.get(exchange.upper(), "america")


def _yahoo_symbol(symbol: str, exchange: Optional[str]) -> str:
    """Ubah simbol gaya TradingView ke Yahoo: BBCA+IDX -> BBCA.JK, BTCUSDT -> BTC-USD."""
    s = symbol.upper()
    ex = (exchange or "").upper()
    if ex == "IDX" and not s.endswith(".JK"):
        return f"{s}.JK"
    if ex in ("BINANCE", "BYBIT", "OKX", "KUCOIN") and s.endswith("USDT"):
        return f"{s[:-4]}-USD"
    if ex in ("FX_IDC", "OANDA", "FX", "FOREXCOM") and len(s) == 6:
        return f"{s}=X"
    return s


@mcp.tool()
def tv_analysis(symbol: str, exchange: str, interval: str = "1d",
                screener: Optional[str] = None) -> dict:
    """Rating teknikal TradingView untuk satu simbol.

    Args:
        symbol: Kode simbol, mis. "BBCA", "AAPL", "BTCUSDT", "EURUSD".
        exchange: Bursa TradingView, mis. "IDX", "NASDAQ", "BINANCE", "FX_IDC".
        interval: 1m,5m,15m,30m,1h,2h,4h,1d,1W,1M (default 1d).
        screener: Opsional: indonesia, america, crypto, forex, cfd. Otomatis dari exchange.
    """
    if interval not in INTERVALS:
        return {"error": f"interval harus salah satu dari {list(INTERVALS)}"}
    h = TA_Handler(symbol=symbol.upper(), exchange=exchange.upper(),
                   screener=_screener(exchange, screener), interval=INTERVALS[interval])
    a = h.get_analysis()
    ind = a.indicators
    keys = ["close", "open", "high", "low", "volume", "change", "RSI", "MACD.macd",
            "MACD.signal", "Stoch.K", "Stoch.D", "ADX", "CCI20", "AO", "Mom",
            "EMA10", "EMA20", "EMA50", "EMA200", "SMA20", "SMA50", "SMA200",
            "BB.upper", "BB.lower", "Pivot.M.Classic.S1", "Pivot.M.Classic.R1"]
    return {
        "symbol": a.symbol, "exchange": a.exchange, "interval": interval,
        "time": str(a.time),
        "summary": a.summary,
        "oscillators": a.oscillators["RECOMMENDATION"],
        "moving_averages": a.moving_averages["RECOMMENDATION"],
        "indicators": {k: ind.get(k) for k in keys if k in ind},
    }


@mcp.tool()
def tv_multi_timeframe(symbol: str, exchange: str,
                       intervals: list[str] = ["15m", "1h", "4h", "1d", "1W"],
                       screener: Optional[str] = None) -> dict:
    """Rating TradingView (BUY/SELL/NEUTRAL) untuk satu simbol di beberapa timeframe."""
    out = {}
    for iv in intervals:
        if iv not in INTERVALS:
            out[iv] = "interval tidak valid"
            continue
        try:
            a = TA_Handler(symbol=symbol.upper(), exchange=exchange.upper(),
                           screener=_screener(exchange, screener),
                           interval=INTERVALS[iv]).get_analysis()
            out[iv] = {"rekomendasi": a.summary["RECOMMENDATION"],
                       "buy": a.summary["BUY"], "sell": a.summary["SELL"],
                       "neutral": a.summary["NEUTRAL"],
                       "close": a.indicators.get("close")}
        except Exception as e:  # noqa: BLE001
            out[iv] = f"error: {e}"
    return {"symbol": symbol.upper(), "exchange": exchange.upper(), "timeframes": out}


@mcp.tool()
def tv_scan(symbols: list[str], screener: str = "indonesia", interval: str = "1d") -> dict:
    """Rating TradingView untuk banyak simbol sekaligus (watchlist).

    Args:
        symbols: Format "EXCHANGE:SYMBOL", mis. ["IDX:BBCA", "IDX:TLKM", "IDX:BBRI"].
        screener: indonesia, america, crypto, forex, cfd.
        interval: 1m..1M (default 1d).
    """
    res = get_multiple_analysis(screener=screener, interval=INTERVALS[interval],
                                symbols=[s.upper() for s in symbols])
    return {k: (None if v is None else {
        "rekomendasi": v.summary["RECOMMENDATION"],
        "close": v.indicators.get("close"),
        "change_%": v.indicators.get("change"),
        "RSI": v.indicators.get("RSI"),
    }) for k, v in res.items()}


@mcp.tool()
def get_quote(symbol: str, exchange: Optional[str] = None) -> dict:
    """Harga terkini sebuah simbol (Yahoo Finance).

    Args:
        symbol: mis. "BBCA" (+exchange "IDX"), "AAPL", "BTCUSDT" (+ "BINANCE"), atau langsung "BBCA.JK".
        exchange: Opsional, exchange gaya TradingView untuk konversi otomatis.
    """
    ys = _yahoo_symbol(symbol, exchange)
    fi = yf.Ticker(ys).fast_info
    return {
        "symbol": ys, "last_price": fi.get("lastPrice"),
        "previous_close": fi.get("previousClose"), "open": fi.get("open"),
        "day_high": fi.get("dayHigh"), "day_low": fi.get("dayLow"),
        "volume": fi.get("lastVolume"), "currency": fi.get("currency"),
        "year_high": fi.get("yearHigh"), "year_low": fi.get("yearLow"),
    }


def _history(symbol: str, exchange: Optional[str], interval: str, period: str) -> pd.DataFrame:
    df = yf.Ticker(_yahoo_symbol(symbol, exchange)).history(period=period, interval=interval)
    if df.empty:
        raise ValueError("Data kosong. Cek simbol/exchange/interval.")
    return df[["Open", "High", "Low", "Close", "Volume"]]


@mcp.tool()
def get_candles(symbol: str, exchange: Optional[str] = None, interval: str = "1d",
                period: str = "3mo", limit: int = 100) -> dict:
    """Data candle OHLCV (Yahoo Finance).

    Args:
        interval: 1m,5m,15m,30m,1h,1d,1wk,1mo
        period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,max
        limit: jumlah candle terakhir yang dikembalikan (maks 500)
    """
    df = _history(symbol, exchange, interval, period).tail(min(limit, 500)).round(4)
    df.index = df.index.astype(str)
    return {"symbol": _yahoo_symbol(symbol, exchange), "interval": interval,
            "candles": df.reset_index().rename(columns={"index": "time", "Date": "time",
                                                        "Datetime": "time"}).to_dict("records")}


@mcp.tool()
def calc_indicators(symbol: str, exchange: Optional[str] = None,
                    interval: str = "1d", period: str = "1y") -> dict:
    """Hitung indikator dari data candle: SMA/EMA, RSI14, MACD, Bollinger, ATR14."""
    df = _history(symbol, exchange, interval, period)
    c = df["Close"]
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    sma20, std20 = c.rolling(20).mean(), c.rolling(20).std()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - c.shift()).abs(),
                    (df["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    last = lambda s: None if pd.isna(s.iloc[-1]) else round(float(s.iloc[-1]), 4)  # noqa: E731
    return {
        "symbol": _yahoo_symbol(symbol, exchange), "interval": interval,
        "time": str(df.index[-1]), "close": last(c),
        "SMA20": last(sma20), "SMA50": last(c.rolling(50).mean()),
        "SMA200": last(c.rolling(200).mean()),
        "EMA20": last(c.ewm(span=20, adjust=False).mean()),
        "RSI14": last(rsi), "MACD": last(macd), "MACD_signal": last(signal),
        "MACD_hist": last(macd - signal),
        "BB_upper": last(sma20 + 2 * std20), "BB_lower": last(sma20 - 2 * std20),
        "ATR14": last(tr.ewm(alpha=1 / 14, adjust=False).mean()),
    }


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)
