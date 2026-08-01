"""Tests for src/symbols.py's ticker format resolution."""

from src.symbols import resolve_symbol


def test_bare_crypto_base():
    s = resolve_symbol("BTC")
    assert s.yfinance == "BTC-USD"
    assert s.alpaca == "BTC/USD"
    assert s.is_crypto is True


def test_alpaca_format_input():
    s = resolve_symbol("DOGE/USD")
    assert s.yfinance == "DOGE-USD"
    assert s.alpaca == "DOGE/USD"
    assert s.is_crypto is True


def test_yfinance_format_input():
    s = resolve_symbol("SOL-USD")
    assert s.yfinance == "SOL-USD"
    assert s.alpaca == "SOL/USD"
    assert s.is_crypto is True


def test_stock_ticker():
    s = resolve_symbol("AAPL")
    assert s.yfinance == "AAPL"
    assert s.alpaca == "AAPL"
    assert s.is_crypto is False


def test_whitespace_and_case_normalized():
    s = resolve_symbol("  btc ")
    assert s.yfinance == "BTC-USD"
    assert s.is_crypto is True


def test_unknown_crypto_looking_ticker_falls_back_to_stock():
    s = resolve_symbol("ZZZZ")
    assert s.yfinance == "ZZZZ"
    assert s.alpaca == "ZZZZ"
    assert s.is_crypto is False
