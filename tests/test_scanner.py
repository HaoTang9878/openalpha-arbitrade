"""
价格扫描器单元测试

覆盖 backend/scanner.py 的核心方法：
- PriceScanner._init_exchanges() — 交易所实例初始化
- _parse_single_ticker() / _parse_ticker() — ticker 解析
- _parse_tickers() — 批量 ticker 解析
- scan_exchange() / scan_all() — 扫描（mock CCXT）
- get_exchange_status() — 状态查询
- WebSocketScanner.get_prices() / get_orderbooks() / get_exchange_status()
- _get_valid_symbols() — 交易对过滤
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ccxt
from backend.scanner import (
    PriceScanner,
    WebSocketScanner,
    WS_BLACKLIST,
    _parse_ticker,
)


# ----------------------------------------------------------------------------
# _parse_single_ticker() / _parse_ticker() 解析测试
# ----------------------------------------------------------------------------
class TestParseTicker:
    """ticker 解析测试"""

    def test_parse_valid_ticker(self):
        """解析有效 ticker"""
        scanner = PriceScanner([], [])
        ticker = {
            "bid": 95000.0, "ask": 95001.0,
            "last": 95000.5, "quoteVolume": 1000000.0,
            "timestamp": 1700000000000,
        }
        result = scanner._parse_single_ticker(ticker)
        assert result is not None
        assert result["bid"] == 95000.0
        assert result["ask"] == 95001.0
        assert result["last"] == 95000.5
        assert result["volume"] == 1000000.0
        assert result["timestamp"] == 1700000000000

    def test_parse_ticker_missing_bid(self):
        """缺少 bid 返回 None"""
        scanner = PriceScanner([], [])
        ticker = {"ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0}
        assert scanner._parse_single_ticker(ticker) is None

    def test_parse_ticker_missing_ask(self):
        """缺少 ask 返回 None"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 95000.0, "last": 95000.5, "quoteVolume": 1000.0}
        assert scanner._parse_single_ticker(ticker) is None

    def test_parse_ticker_zero_bid(self):
        """bid=0 返回 None"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 0, "ask": 95001.0, "last": 95000.5}
        assert scanner._parse_single_ticker(ticker) is None

    def test_parse_ticker_zero_ask(self):
        """ask=0 返回 None"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 95000.0, "ask": 0, "last": 95000.5}
        assert scanner._parse_single_ticker(ticker) is None

    def test_parse_ticker_none_values(self):
        """bid/ask 为 None 返回 None"""
        scanner = PriceScanner([], [])
        ticker = {"bid": None, "ask": None, "last": 95000.5}
        assert scanner._parse_single_ticker(ticker) is None

    def test_parse_ticker_missing_last_defaults_zero(self):
        """缺少 last 时默认为 0"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 95000.0, "ask": 95001.0, "quoteVolume": 1000.0}
        result = scanner._parse_single_ticker(ticker)
        assert result["last"] == 0.0

    def test_parse_ticker_missing_volume_defaults_zero(self):
        """缺少 quoteVolume 时默认为 0"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 95000.0, "ask": 95001.0, "last": 95000.5}
        result = scanner._parse_single_ticker(ticker)
        assert result["volume"] == 0.0

    def test_parse_ticker_missing_timestamp_defaults_zero(self):
        """缺少 timestamp 时默认为 0"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 95000.0, "ask": 95001.0, "last": 95000.5}
        result = scanner._parse_single_ticker(ticker)
        assert result["timestamp"] == 0

    def test_parse_ticker_invalid_types_returns_none(self):
        """无效类型返回 None"""
        scanner = PriceScanner([], [])
        ticker = {"bid": "invalid", "ask": 95001.0}
        assert scanner._parse_single_ticker(ticker) is None

    def test_parse_ticker_none_last(self):
        """last 为 None 时转为 0"""
        scanner = PriceScanner([], [])
        ticker = {"bid": 95000.0, "ask": 95001.0, "last": None}
        result = scanner._parse_single_ticker(ticker)
        assert result is not None
        assert result["last"] == 0.0


class TestModuleLevelParseTicker:
    """模块级 _parse_ticker() 函数测试"""

    def test_module_parse_valid(self):
        """模块级函数解析有效 ticker"""
        ticker = {
            "bid": 100.0, "ask": 101.0,
            "last": 100.5, "quoteVolume": 500.0,
            "timestamp": 1700000000000,
        }
        result = _parse_ticker(ticker)
        assert result is not None
        assert result["bid"] == 100.0

    def test_module_parse_invalid(self):
        """模块级函数解析无效 ticker"""
        assert _parse_ticker({"bid": None, "ask": 101.0}) is None


# ----------------------------------------------------------------------------
# _parse_tickers() 批量解析测试
# ----------------------------------------------------------------------------
class TestParseTickers:
    """_parse_tickers() 批量解析测试"""

    def test_parse_multiple_tickers(self):
        """批量解析多个 ticker"""
        scanner = PriceScanner([], [])
        tickers = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
            "ETH/USDT": {"bid": 3200.0, "ask": 3201.0, "last": 3200.5, "quoteVolume": 500.0},
        }
        result = scanner._parse_tickers("binance", tickers)
        assert len(result) == 2
        assert "BTC/USDT" in result
        assert "ETH/USDT" in result

    def test_parse_tickers_filters_invalid(self):
        """批量解析过滤无效 ticker"""
        scanner = PriceScanner([], [])
        tickers = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5},
            "BAD/USDT": {"bid": None, "ask": None},  # 无效
        }
        result = scanner._parse_tickers("binance", tickers)
        assert len(result) == 1
        assert "BTC/USDT" in result
        assert "BAD/USDT" not in result

    def test_parse_tickers_empty(self):
        """空 ticker 字典返回空"""
        scanner = PriceScanner([], [])
        assert scanner._parse_tickers("binance", {}) == {}


# ----------------------------------------------------------------------------
# PriceScanner._init_exchanges() 初始化测试
# ----------------------------------------------------------------------------
class TestScannerInit:
    """PriceScanner 初始化测试"""

    def test_init_supported_exchanges(self):
        """初始化支持的交易所"""
        scanner = PriceScanner(["binance", "okx"], ["BTC/USDT"])
        assert "binance" in scanner._exchange_instances
        assert "okx" in scanner._exchange_instances
        assert scanner.error_counts["binance"] == 0
        assert scanner.error_counts["okx"] == 0

    def test_init_unsupported_exchange_skipped(self):
        """不支持的交易所被跳过"""
        scanner = PriceScanner(["binance", "fake_exchange"], ["BTC/USDT"])
        assert "binance" in scanner._exchange_instances
        assert "fake_exchange" not in scanner._exchange_instances

    def test_init_with_config_api_keys(self, test_config):
        """传入 config 时注入 API 密钥"""
        test_config.api_keys["binance"] = {"apiKey": "key", "secret": "secret"}
        scanner = PriceScanner(["binance"], ["BTC/USDT"], config=test_config)
        assert "binance" in scanner._exchange_instances

    def test_init_empty_exchanges(self):
        """空交易所列表初始化"""
        scanner = PriceScanner([], ["BTC/USDT"])
        assert scanner._exchange_instances == {}


# ----------------------------------------------------------------------------
# scan_exchange() / scan_all() 扫描测试（mock CCXT）
# ----------------------------------------------------------------------------
class TestScanExchange:
    """scan_exchange() 扫描测试"""

    @pytest.mark.asyncio
    async def test_scan_exchange_success(self):
        """成功扫描交易所"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {
                "bid": 95000.0, "ask": 95001.0,
                "last": 95000.5, "quoteVolume": 1000.0,
                "timestamp": 1700000000000,
            },
        }
        scanner._exchange_instances["binance"] = mock_exchange

        # mock _get_valid_symbols 返回全部交易对
        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_exchange("binance")
        assert "BTC/USDT" in result
        assert result["BTC/USDT"]["bid"] == 95000.0

    @pytest.mark.asyncio
    async def test_scan_exchange_not_supported_fallback(self):
        """交易所不支持批量获取时回退到逐个获取"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.side_effect = ccxt.NotSupported("not supported")
        mock_exchange.fetch_ticker.return_value = {
            "bid": 95000.0, "ask": 95001.0,
            "last": 95000.5, "quoteVolume": 1000.0,
            "timestamp": 1700000000000,
        }
        scanner._exchange_instances["binance"] = mock_exchange
        scanner._valid_symbols["binance"] = ["BTC/USDT"]

        result = await scanner.scan_exchange("binance")
        assert "BTC/USDT" in result

    @pytest.mark.asyncio
    async def test_scan_exchange_network_error(self):
        """网络错误时返回空字典并增加错误计数"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.side_effect = ccxt.NetworkError("timeout")
        scanner._exchange_instances["binance"] = mock_exchange
        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_exchange("binance")
        assert result == {}
        assert scanner.error_counts["binance"] >= 1

    @pytest.mark.asyncio
    async def test_scan_exchange_exchange_error(self):
        """交易所错误时返回空字典"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.side_effect = ccxt.ExchangeError("rate limit")
        scanner._exchange_instances["binance"] = mock_exchange
        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_exchange("binance")
        assert result == {}

    @pytest.mark.asyncio
    async def test_scan_exchange_unknown_error(self):
        """未知错误时返回空字典"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.side_effect = RuntimeError("unknown")
        scanner._exchange_instances["binance"] = mock_exchange
        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_exchange("binance")
        assert result == {}

    @pytest.mark.asyncio
    async def test_scan_exchange_not_initialized(self):
        """未初始化的交易所返回空字典"""
        scanner = PriceScanner([], ["BTC/USDT"])
        result = await scanner.scan_exchange("binance")
        assert result == {}

    @pytest.mark.asyncio
    async def test_scan_exchange_records_latency(self):
        """扫描后记录延迟"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
        }
        scanner._exchange_instances["binance"] = mock_exchange
        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        await scanner.scan_exchange("binance")
        assert scanner.latencies["binance"] >= 0


class TestScanAll:
    """scan_all() 并发扫描测试"""

    @pytest.mark.asyncio
    async def test_scan_all_multiple_exchanges(self):
        """并发扫描多个交易所"""
        scanner = PriceScanner(["binance", "okx"], ["BTC/USDT"])

        for ex_name in ["binance", "okx"]:
            mock_exchange = AsyncMock()
            mock_exchange.fetch_tickers.return_value = {
                "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
            }
            scanner._exchange_instances[ex_name] = mock_exchange

        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_all()
        assert "binance" in result
        assert "okx" in result

    @pytest.mark.asyncio
    async def test_scan_all_skips_failed_exchanges(self):
        """失败的交易所被跳过"""
        scanner = PriceScanner(["binance", "okx"], ["BTC/USDT"])

        # binance 成功
        mock_binance = AsyncMock()
        mock_binance.fetch_tickers.return_value = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
        }
        scanner._exchange_instances["binance"] = mock_binance

        # okx 抛异常
        mock_okx = AsyncMock()
        mock_okx.fetch_tickers.side_effect = RuntimeError("fail")
        scanner._exchange_instances["okx"] = mock_okx

        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_all()
        assert "binance" in result
        assert "okx" not in result

    @pytest.mark.asyncio
    async def test_scan_all_empty_result_skipped(self):
        """返回空结果的交易所被跳过"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.return_value = {}
        scanner._exchange_instances["binance"] = mock_exchange
        scanner._get_valid_symbols = AsyncMock(return_value=["BTC/USDT"])

        result = await scanner.scan_all()
        assert "binance" not in result


# ----------------------------------------------------------------------------
# _get_valid_symbols() 交易对过滤测试
# ----------------------------------------------------------------------------
class TestGetValidSymbols:
    """_get_valid_symbols() 交易对过滤测试"""

    @pytest.mark.asyncio
    async def test_get_valid_symbols_caches(self):
        """结果被缓存"""
        scanner = PriceScanner(["binance"], ["BTC/USDT", "ETH/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.markets = {"BTC/USDT": {}, "ETH/USDT": {}}
        scanner._exchange_instances["binance"] = mock_exchange

        result1 = await scanner._get_valid_symbols("binance", mock_exchange)
        result2 = await scanner._get_valid_symbols("binance", mock_exchange)
        # 第二次应命中缓存，不再次调用 load_markets
        assert result1 == result2
        assert mock_exchange.load_markets.call_count == 1

    @pytest.mark.asyncio
    async def test_get_valid_symbols_filters_unsupported(self):
        """过滤交易所不支持的交易对"""
        scanner = PriceScanner(["binance"], ["BTC/USDT", "ARB/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.markets = {"BTC/USDT": {}}  # 不支持 ARB/USDT
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner._get_valid_symbols("binance", mock_exchange)
        assert "BTC/USDT" in result
        assert "ARB/USDT" not in result

    @pytest.mark.asyncio
    async def test_get_valid_symbols_load_fails_returns_all(self):
        """load_markets 失败时返回全部交易对"""
        scanner = PriceScanner(["binance"], ["BTC/USDT", "ETH/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.load_markets.side_effect = RuntimeError("load failed")
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner._get_valid_symbols("binance", mock_exchange)
        assert result == ["BTC/USDT", "ETH/USDT"]

    @pytest.mark.asyncio
    async def test_get_valid_symbols_none_supported_returns_all(self):
        """所有交易对都不支持时返回全部"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.markets = {}  # 空市场
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner._get_valid_symbols("binance", mock_exchange)
        assert result == ["BTC/USDT"]


# ----------------------------------------------------------------------------
# _scan_exchange_individual() 逐个获取测试
# ----------------------------------------------------------------------------
class TestScanIndividual:
    """_scan_exchange_individual() 逐个获取测试"""

    @pytest.mark.asyncio
    async def test_scan_individual_success(self):
        """逐个获取成功"""
        scanner = PriceScanner(["binance"], ["BTC/USDT", "ETH/USDT"])
        scanner._valid_symbols["binance"] = ["BTC/USDT", "ETH/USDT"]

        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.side_effect = [
            {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
            {"bid": 3200.0, "ask": 3201.0, "last": 3200.5, "quoteVolume": 500.0},
        ]
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner._scan_exchange_individual("binance")
        assert "BTC/USDT" in result
        assert "ETH/USDT" in result

    @pytest.mark.asyncio
    async def test_scan_individual_skips_failed_symbols(self):
        """逐个获取时单个交易对失败不影响其他"""
        scanner = PriceScanner(["binance"], ["BTC/USDT", "BAD/USDT"])
        scanner._valid_symbols["binance"] = ["BTC/USDT", "BAD/USDT"]

        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.side_effect = [
            {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
            RuntimeError("not found"),
        ]
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner._scan_exchange_individual("binance")
        assert "BTC/USDT" in result
        assert "BAD/USDT" not in result

    @pytest.mark.asyncio
    async def test_scan_individual_not_initialized(self):
        """未初始化交易所返回空"""
        scanner = PriceScanner([], ["BTC/USDT"])
        result = await scanner._scan_exchange_individual("binance")
        assert result == {}


# ----------------------------------------------------------------------------
# get_ticker() 单交易对查询测试
# ----------------------------------------------------------------------------
class TestGetTicker:
    """get_ticker() 单交易对查询测试"""

    @pytest.mark.asyncio
    async def test_get_ticker_success(self):
        """成功获取单个 ticker"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.return_value = {
            "bid": 95000.0, "ask": 95001.0,
            "last": 95000.5, "quoteVolume": 1000.0,
            "timestamp": 1700000000000,
        }
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner.get_ticker("binance", "BTC/USDT")
        assert result is not None
        assert result["bid"] == 95000.0

    @pytest.mark.asyncio
    async def test_get_ticker_not_initialized(self):
        """未初始化交易所返回 None"""
        scanner = PriceScanner([], ["BTC/USDT"])
        result = await scanner.get_ticker("binance", "BTC/USDT")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_ticker_error_returns_none(self):
        """获取失败返回 None"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])

        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.side_effect = RuntimeError("error")
        scanner._exchange_instances["binance"] = mock_exchange

        result = await scanner.get_ticker("binance", "BTC/USDT")
        assert result is None


# ----------------------------------------------------------------------------
# get_exchange_status() 状态查询测试
# ----------------------------------------------------------------------------
class TestExchangeStatus:
    """get_exchange_status() 状态查询测试"""

    def test_get_status_initialized(self):
        """已初始化交易所状态正确"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])
        status = scanner.get_exchange_status()
        assert "binance" in status
        assert status["binance"]["enabled"] is True
        assert status["binance"]["connected"] is True
        assert status["binance"]["error_count"] == 0

    def test_get_status_not_initialized(self):
        """未初始化交易所状态正确"""
        scanner = PriceScanner(["binance", "fake"], ["BTC/USDT"])
        status = scanner.get_exchange_status()
        assert status["fake"]["enabled"] is False
        assert status["fake"]["connected"] is False

    def test_get_status_with_errors(self):
        """有错误的交易所状态正确"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])
        scanner.error_counts["binance"] = 3
        status = scanner.get_exchange_status()
        assert status["binance"]["error_count"] == 3
        assert status["binance"]["connected"] is False


# ----------------------------------------------------------------------------
# close() 关闭测试
# ----------------------------------------------------------------------------
class TestScannerClose:
    """close() 关闭测试"""

    @pytest.mark.asyncio
    async def test_close_clears_instances(self):
        """close 清空交易所实例"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])
        mock_exchange = AsyncMock()
        scanner._exchange_instances["binance"] = mock_exchange
        await scanner.close()
        assert scanner._exchange_instances == {}

    @pytest.mark.asyncio
    async def test_close_handles_errors(self):
        """close 时单个交易所关闭失败不影响其他"""
        scanner = PriceScanner(["binance"], ["BTC/USDT"])
        mock_exchange = AsyncMock()
        mock_exchange.close.side_effect = RuntimeError("close failed")
        scanner._exchange_instances["binance"] = mock_exchange
        # 不应抛异常
        await scanner.close()
        assert scanner._exchange_instances == {}


# ----------------------------------------------------------------------------
# WebSocketScanner 测试
# ----------------------------------------------------------------------------
class TestWebSocketScanner:
    """WebSocketScanner 测试"""

    def test_ws_init_supported_exchanges(self):
        """初始化支持的交易所"""
        scanner = WebSocketScanner(["binance", "okx"], ["BTC/USDT"])
        assert "binance" in scanner._exchange_instances
        assert "okx" in scanner._exchange_instances

    def test_ws_init_blacklist_uses_rest(self):
        """黑名单交易所使用 REST 模式"""
        scanner = WebSocketScanner(["bybit"], ["BTC/USDT"])
        assert scanner._rest_mode["bybit"] is True

    def test_ws_init_non_blacklist_uses_ws(self):
        """非黑名单交易所使用 WebSocket 模式"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        assert scanner._rest_mode["binance"] is False

    def test_ws_init_unsupported_skipped(self):
        """不支持的交易所被跳过"""
        scanner = WebSocketScanner(["binance", "fake_ex"], ["BTC/USDT"])
        assert "binance" in scanner._exchange_instances
        assert "fake_ex" not in scanner._exchange_instances

    def test_ws_get_prices_returns_cache(self):
        """get_prices 返回缓存数据"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        scanner.price_cache["binance"] = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "volume": 1000.0, "timestamp": 0},
        }
        prices = scanner.get_prices()
        assert "binance" in prices
        assert "BTC/USDT" in prices["binance"]

    def test_ws_get_prices_filters_empty(self):
        """get_prices 过滤空缓存"""
        scanner = WebSocketScanner(["binance", "okx"], ["BTC/USDT"])
        scanner.price_cache["binance"] = {}
        scanner.price_cache["okx"] = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "volume": 1000.0, "timestamp": 0},
        }
        prices = scanner.get_prices()
        assert "binance" not in prices
        assert "okx" in prices

    def test_ws_get_orderbooks_returns_cache(self):
        """get_orderbooks 返回订单簿缓存"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        scanner.orderbook_cache["binance"] = {
            "BTC/USDT": {"bids": [[95000.0, 0.5]], "asks": [[95001.0, 0.3]]},
        }
        obs = scanner.get_orderbooks()
        assert "binance" in obs

    def test_ws_get_orderbooks_filters_empty(self):
        """get_orderbooks 过滤空缓存"""
        scanner = WebSocketScanner(["binance", "okx"], ["BTC/USDT"])
        scanner.orderbook_cache["binance"] = {}
        scanner.orderbook_cache["okx"] = {
            "BTC/USDT": {"bids": [[95000.0, 0.5]], "asks": [[95001.0, 0.3]]},
        }
        obs = scanner.get_orderbooks()
        assert "binance" not in obs
        assert "okx" in obs

    def test_ws_get_exchange_status(self):
        """get_exchange_status 返回状态"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        status = scanner.get_exchange_status()
        assert "binance" in status
        assert status["binance"]["enabled"] is True
        assert status["binance"]["mode"] == "WebSocket"

    def test_ws_get_exchange_status_blacklist_rest(self):
        """黑名单交易所状态显示 REST 模式"""
        scanner = WebSocketScanner(["bybit"], ["BTC/USDT"])
        status = scanner.get_exchange_status()
        assert status["bybit"]["mode"] == "REST"

    @pytest.mark.asyncio
    async def test_ws_close_clears_instances(self):
        """close 清空实例"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        mock_exchange = AsyncMock()
        scanner._exchange_instances["binance"] = mock_exchange
        await scanner.close()
        assert scanner._exchange_instances == {}

    @pytest.mark.asyncio
    async def test_ws_close_handles_errors(self):
        """close 时单个交易所关闭失败不影响其他"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        mock_exchange = AsyncMock()
        mock_exchange.close.side_effect = RuntimeError("fail")
        scanner._exchange_instances["binance"] = mock_exchange
        await scanner.close()  # 不应抛异常
        assert scanner._exchange_instances == {}

    @pytest.mark.asyncio
    async def test_ws_get_valid_symbols_filters(self):
        """_get_valid_symbols 过滤不支持的交易对"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT", "ARB/USDT"])
        mock_exchange = AsyncMock()
        mock_exchange.markets = {"BTC/USDT": {}}
        result = await scanner._get_valid_symbols("binance", mock_exchange)
        assert "BTC/USDT" in result
        assert "ARB/USDT" not in result

    @pytest.mark.asyncio
    async def test_ws_get_valid_symbols_load_fails(self):
        """load_markets 失败时返回全部交易对"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT", "ETH/USDT"])
        mock_exchange = AsyncMock()
        mock_exchange.load_markets.side_effect = RuntimeError("fail")
        result = await scanner._get_valid_symbols("binance", mock_exchange)
        assert result == ["BTC/USDT", "ETH/USDT"]

    @pytest.mark.asyncio
    async def test_ws_rest_poll_loop_success(self):
        """REST 轮询成功更新缓存"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        scanner._valid_symbols["binance"] = ["BTC/USDT"]

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
        }
        scanner._exchange_instances["binance"] = mock_exchange

        # 黑名单交易所不尝试恢复 WS，避免触发恢复逻辑
        with patch.dict("backend.scanner.WS_BLACKLIST", {"binance"}):
            await scanner._rest_poll_loop("binance", ["BTC/USDT"])

        assert "BTC/USDT" in scanner.price_cache["binance"]
        assert scanner._connected["binance"] is True

    @pytest.mark.asyncio
    async def test_ws_rest_poll_loop_error(self):
        """REST 轮询失败时增加错误计数"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        scanner._valid_symbols["binance"] = ["BTC/USDT"]

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.side_effect = RuntimeError("fail")
        scanner._exchange_instances["binance"] = mock_exchange

        with patch.dict("backend.scanner.WS_BLACKLIST", {"binance"}):
            await scanner._rest_poll_loop("binance", ["BTC/USDT"])

        assert scanner.error_counts["binance"] >= 1

    @pytest.mark.asyncio
    async def test_ws_reconnect_with_recovery_success(self):
        """重连数据补偿成功"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        scanner._valid_symbols["binance"] = ["BTC/USDT"]

        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "quoteVolume": 1000.0},
        }
        scanner._exchange_instances["binance"] = mock_exchange

        await scanner._reconnect_with_recovery("binance")
        assert "BTC/USDT" in scanner.price_cache["binance"]
        assert scanner._connected["binance"] is True

    @pytest.mark.asyncio
    async def test_ws_reconnect_with_recovery_failure(self):
        """重连数据补偿失败不抛异常"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        mock_exchange = AsyncMock()
        mock_exchange.fetch_tickers.side_effect = RuntimeError("fail")
        scanner._exchange_instances["binance"] = mock_exchange

        # 不应抛异常
        await scanner._reconnect_with_recovery("binance")

    @pytest.mark.asyncio
    async def test_ws_reconnect_no_exchange(self):
        """无交易所实例时重连补偿直接返回"""
        scanner = WebSocketScanner([], ["BTC/USDT"])
        # 不应抛异常
        await scanner._reconnect_with_recovery("binance")

    @pytest.mark.asyncio
    async def test_ws_watch_single_orderbook_invalid_symbol(self):
        """无效 symbol 时订单簿监听跳过"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        # None symbol 应被跳过
        await scanner._watch_single_orderbook("binance", None)  # type: ignore[arg-type]
        # 不应抛异常

    @pytest.mark.asyncio
    async def test_ws_watch_single_orderbook_no_exchange(self):
        """无交易所实例时订单簿监听直接返回"""
        scanner = WebSocketScanner([], ["BTC/USDT"])
        await scanner._watch_single_orderbook("binance", "BTC/USDT")
        # 不应抛异常

    @pytest.mark.asyncio
    async def test_ws_watch_orderbook_loop_no_valid_symbols(self):
        """无有效 symbol 时订单簿循环跳过"""
        scanner = WebSocketScanner(["binance"], ["BTC/USDT"])
        # 全部无效
        await scanner._watch_orderbook_loop("binance", [None, ""])  # type: ignore[list-item]
        # 不应抛异常

    @pytest.mark.asyncio
    async def test_ws_watch_orderbook_loop_no_exchange(self):
        """无交易所实例时订单簿循环直接返回"""
        scanner = WebSocketScanner([], ["BTC/USDT"])
        await scanner._watch_orderbook_loop("binance", ["BTC/USDT"])
        # 不应抛异常
