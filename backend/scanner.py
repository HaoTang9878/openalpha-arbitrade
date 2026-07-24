"""
多交易所价格扫描器模块

使用 CCXT 库并发获取多个交易所的 ticker 数据，
支持 WebSocket 实时更新和 REST 轮询两种模式。

核心功能：
- 并发获取 N 个交易所的 M 个交易对价格
- 计算每个交易对在各交易所的买一价/卖一价
- 返回统一格式的价格快照

返回格式：
    {
        "binance": {
            "BTC/USDT": {
                "bid": 50000.0,
                "ask": 50001.0,
                "last": 50000.5,
                "volume": 1234.56,
                "timestamp": 1700000000000
            },
            ...
        },
        ...
    }

使用方法：
    scanner = PriceScanner(["binance", "okx"], ["BTC/USDT", "ETH/USDT"])
    prices = await scanner.scan_all()
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
import ccxt.pro as ccxtpro

from .config import Config

logger = logging.getLogger(__name__)

# 单个交易所请求超时时间（秒）
REQUEST_TIMEOUT_MS = 5000

# WebSocket 重连等待时间（秒）
WS_RECONNECT_DELAY = 1


class PriceScanner:
    """
    多交易所价格扫描器

    使用 CCXT 的异步接口并发获取多个交易所的 ticker 数据，
    支持批量获取和单条获取两种模式。
    """

    def __init__(
        self,
        exchanges: List[str],
        symbols: List[str],
        config: Optional[Config] = None,
    ) -> None:
        """
        初始化价格扫描器，创建各交易所的 CCXT 异步实例

        Args:
            exchanges: 要扫描的交易所名称列表
            symbols: 要监控的交易对列表
            config: 配置管理器实例，用于获取 API 密钥等配置
        """
        self.exchanges = exchanges
        self.symbols = symbols
        self.config = config

        # 存储各交易所的 CCXT 实例
        self._exchange_instances: Dict[str, ccxt.Exchange] = {}

        # 记录各交易所的错误次数，用于监控连接状态
        self.error_counts: Dict[str, int] = {}

        # 记录各交易所的最近延迟（毫秒）
        self.latencies: Dict[str, float] = {}

        # 初始化所有交易所实例
        self._init_exchanges()

    def _init_exchanges(self) -> None:
        """初始化所有交易所的 CCXT 异步实例"""
        for ex_name in self.exchanges:
            try:
                # 获取交易所类（CCXT 支持的交易所）
                exchange_class = getattr(ccxt, ex_name, None)
                if exchange_class is None:
                    logger.warning("不支持的交易所: %s，跳过", ex_name)
                    continue

                # 构建交易所配置
                # fetchMarkets 限制只加载现货市场，避免 CCXT 尝试
                # 加载期货/期权/合约市场导致网络错误
                exchange_config: Dict[str, Any] = {
                    "enableRateLimit": True,
                    "timeout": REQUEST_TIMEOUT_MS,
                    "options": {
                        "defaultType": "spot",
                        "fetchMarkets": ["spot"],
                    },
                }

                # 如果有 API 密钥则注入配置
                if self.config and ex_name in self.config.api_keys:
                    exchange_config.update(self.config.api_keys[ex_name])

                self._exchange_instances[ex_name] = exchange_class(exchange_config)
                self.error_counts[ex_name] = 0
                self.latencies[ex_name] = 0.0
                logger.debug("已初始化交易所: %s", ex_name)

            except Exception as e:
                logger.error("初始化交易所 %s 失败: %s", ex_name, e, exc_info=True)
                self.error_counts[ex_name] = 1

        logger.info(
            "价格扫描器初始化完成，成功初始化 %d/%d 个交易所",
            len(self._exchange_instances),
            len(self.exchanges),
        )

    async def scan_all(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        并发扫描所有交易所的所有交易对

        使用 asyncio.gather 并发请求所有交易所，
        单个交易所失败不影响其他交易所的结果。

        Returns:
            价格快照字典，格式为 {exchange: {symbol: {bid, ask, last, volume, timestamp}}}
        """
        tasks = []
        exchange_names = []

        for ex_name in self._exchange_instances:
            task = self.scan_exchange(ex_name)
            tasks.append(task)
            exchange_names.append(ex_name)

        # 并发执行所有扫描任务
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 组装结果，跳过失败的交易所
        all_prices: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for ex_name, result in zip(exchange_names, results):
            if isinstance(result, Exception):
                logger.warning("扫描交易所 %s 失败: %s", ex_name, result)
                self.error_counts[ex_name] = self.error_counts.get(ex_name, 0) + 1
                continue
            if result:
                all_prices[ex_name] = result
                self.error_counts[ex_name] = 0

        return all_prices

    async def scan_exchange(self, exchange_name: str) -> Dict[str, Dict[str, Any]]:
        """
        扫描单个交易所的所有交易对

        优先使用 fetch_tickers 批量获取，若不支持则逐个获取。

        Args:
            exchange_name: 交易所名称

        Returns:
            该交易所的价格快照，格式为 {symbol: {bid, ask, last, volume, timestamp}}
        """
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            logger.warning("交易所 %s 未初始化", exchange_name)
            return {}

        start_time = time.time()

        try:
            # 尝试批量获取所有交易对的 ticker
            tickers = await exchange.fetch_tickers(self.symbols)
            result = self._parse_tickers(exchange_name, tickers)
            return result

        except ccxt.NotSupported:
            # 该交易所不支持批量获取，回退到逐个获取
            logger.debug("交易所 %s 不支持批量获取，回退到逐个获取", exchange_name)
            return await self._scan_exchange_individual(exchange_name)

        except ccxt.NetworkError as e:
            logger.warning("交易所 %s 网络错误: %s", exchange_name, e)
            self.error_counts[exchange_name] = (
                self.error_counts.get(exchange_name, 0) + 1
            )
            return {}

        except ccxt.ExchangeError as e:
            logger.warning("交易所 %s 交易所错误: %s", exchange_name, e)
            self.error_counts[exchange_name] = (
                self.error_counts.get(exchange_name, 0) + 1
            )
            return {}

        except Exception as e:
            logger.error("扫描交易所 %s 时发生未知错误: %s", exchange_name, e,
                         exc_info=True)
            self.error_counts[exchange_name] = (
                self.error_counts.get(exchange_name, 0) + 1
            )
            return {}

        finally:
            # 记录延迟
            elapsed_ms = (time.time() - start_time) * 1000
            self.latencies[exchange_name] = round(elapsed_ms, 2)

    async def _scan_exchange_individual(
        self, exchange_name: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        逐个获取交易对的 ticker（回退方案）

        当交易所不支持 fetch_tickers 批量获取时使用。

        Args:
            exchange_name: 交易所名称

        Returns:
            该交易所的价格快照
        """
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return {}

        result: Dict[str, Dict[str, Any]] = {}

        for symbol in self.symbols:
            try:
                ticker = await exchange.fetch_ticker(symbol)
                parsed = self._parse_single_ticker(ticker)
                if parsed:
                    result[symbol] = parsed
            except Exception as e:
                logger.debug("获取 %s 的 %s ticker 失败: %s",
                             exchange_name, symbol, e)

        return result

    def _parse_tickers(
        self, exchange_name: str, tickers: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        解析批量获取的 ticker 数据

        Args:
            exchange_name: 交易所名称
            tickers: CCXT 返回的 ticker 字典

        Returns:
            统一格式的价格快照
        """
        result: Dict[str, Dict[str, Any]] = {}

        for symbol, ticker in tickers.items():
            parsed = self._parse_single_ticker(ticker)
            if parsed:
                result[symbol] = parsed

        return result

    def _parse_single_ticker(self, ticker: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解析单个 ticker 数据，提取关键价格信息

        Args:
            ticker: CCXT 返回的单个 ticker 字典

        Returns:
            包含 bid, ask, last, volume, timestamp 的字典，无效数据返回 None
        """
        try:
            bid = ticker.get("bid")
            ask = ticker.get("ask")

            # bid 和 ask 必须同时有效才有套利意义
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                return None

            return {
                "bid": float(bid),
                "ask": float(ask),
                "last": float(ticker.get("last", 0) or 0),
                "volume": float(ticker.get("quoteVolume", 0) or 0),
                "timestamp": int(ticker.get("timestamp", 0) or 0),
            }
        except (ValueError, TypeError) as e:
            logger.debug("解析 ticker 数据失败: %s", e)
            return None

    async def get_ticker(
        self, exchange_name: str, symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取单个交易所的单个交易对 ticker

        Args:
            exchange_name: 交易所名称
            symbol: 交易对

        Returns:
            价格快照字典，失败返回 None
        """
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            logger.warning("交易所 %s 未初始化", exchange_name)
            return None

        try:
            ticker = await exchange.fetch_ticker(symbol)
            return self._parse_single_ticker(ticker)
        except Exception as e:
            logger.error("获取 %s 的 %s ticker 失败: %s",
                         exchange_name, symbol, e, exc_info=True)
            return None

    def get_exchange_status(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有交易所的运行状态

        Returns:
            各交易所的状态字典，包含错误次数和延迟信息
        """
        status: Dict[str, Dict[str, Any]] = {}
        for ex_name in self.exchanges:
            status[ex_name] = {
                "name": ex_name,
                "enabled": ex_name in self._exchange_instances,
                "connected": self.error_counts.get(ex_name, 0) == 0,
                "error_count": self.error_counts.get(ex_name, 0),
                "latency_ms": self.latencies.get(ex_name, 0.0),
            }
        return status

    async def close(self) -> None:
        """关闭所有交易所连接，释放资源"""
        for ex_name, exchange in self._exchange_instances.items():
            try:
                await exchange.close()
                logger.debug("已关闭交易所连接: %s", ex_name)
            except Exception as e:
                logger.warning("关闭交易所 %s 连接失败: %s", ex_name, e)

        self._exchange_instances.clear()
        logger.info("价格扫描器已关闭")


def _parse_ticker(ticker: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    解析单个 ticker 数据，提取关键价格信息（模块级共享函数）

    Args:
        ticker: CCXT 返回的单个 ticker 字典

    Returns:
        包含 bid, ask, last, volume, timestamp 的字典，无效数据返回 None
    """
    try:
        bid = ticker.get("bid")
        ask = ticker.get("ask")

        # bid 和 ask 必须同时有效才有套利意义
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None

        return {
            "bid": float(bid),
            "ask": float(ask),
            "last": float(ticker.get("last", 0) or 0),
            "volume": float(ticker.get("quoteVolume", 0) or 0),
            "timestamp": int(ticker.get("timestamp", 0) or 0),
        }
    except (ValueError, TypeError) as e:
        logger.debug("解析 ticker 数据失败: %s", e)
        return None


class WebSocketScanner:
    """
    WebSocket 实时价格扫描器

    使用 ccxt.pro 建立 WebSocket 长连接，实时接收交易所推送的 ticker 数据。
    维护内存缓存，get_prices() 即时返回缓存数据，无网络 I/O。

    与 PriceScanner 接口兼容，可作为替代品使用。
    """

    def __init__(
        self,
        exchanges: List[str],
        symbols: List[str],
        config: Optional[Config] = None,
    ) -> None:
        """
        初始化 WebSocket 扫描器

        Args:
            exchanges: 要扫描的交易所名称列表
            symbols: 要监控的交易对列表
            config: 配置管理器实例，用于获取 API 密钥等配置
        """
        self.exchanges = exchanges
        self.symbols = symbols
        self.config = config

        # ccxt.pro 交易所实例
        self._exchange_instances: Dict[str, Any] = {}

        # 后台 WS 监听任务
        self._ws_tasks: List[asyncio.Task] = []

        # 内存价格缓存（实时更新）
        self.price_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # 错误计数和延迟（与 PriceScanner 兼容）
        self.error_counts: Dict[str, int] = {}
        self.latencies: Dict[str, float] = {}

        # 连接状态标记
        self._connected: Dict[str, bool] = {}

        # 初始化交易所实例
        self._init_exchanges()

    def _init_exchanges(self) -> None:
        """初始化所有交易所的 ccxt.pro 实例"""
        for ex_name in self.exchanges:
            try:
                exchange_class = getattr(ccxtpro, ex_name, None)
                if exchange_class is None:
                    logger.warning("ccxt.pro 不支持的交易所: %s，跳过", ex_name)
                    continue

                # 构建交易所配置（与 PriceScanner 一致）
                exchange_config: Dict[str, Any] = {
                    "enableRateLimit": True,
                    "timeout": REQUEST_TIMEOUT_MS,
                    "options": {
                        "defaultType": "spot",
                        "fetchMarkets": ["spot"],
                    },
                }

                # 注入 API 密钥（如有）
                if self.config and ex_name in self.config.api_keys:
                    exchange_config.update(self.config.api_keys[ex_name])

                self._exchange_instances[ex_name] = exchange_class(exchange_config)
                self.error_counts[ex_name] = 0
                self.latencies[ex_name] = 0.0
                self._connected[ex_name] = False
                self.price_cache[ex_name] = {}
                logger.debug("已初始化 WS 交易所: %s", ex_name)

            except Exception as e:
                logger.error("初始化 WS 交易所 %s 失败: %s", ex_name, e)
                self.error_counts[ex_name] = 1

        logger.info(
            "WebSocket 扫描器初始化完成，成功初始化 %d/%d 个交易所",
            len(self._exchange_instances),
            len(self.exchanges),
        )

    async def start(self) -> None:
        """为每个交易所启动 watch_tickers 后台监听任务"""
        for ex_name in self._exchange_instances:
            task = asyncio.create_task(self._watch_exchange(ex_name))
            self._ws_tasks.append(task)
            logger.info("已启动 %s 的 WebSocket 监听", ex_name)

    async def _watch_exchange(self, exchange_name: str) -> None:
        """
        监听单个交易所的 ticker 更新，实时更新内存缓存

        该方法在后台持续运行，断线后自动重试。
        ccxt.pro 内置自动重连机制，外层 while 提供额外保障。
        """
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return

        logger.info("开始监听 %s 的 WebSocket ticker 流", exchange_name)

        while True:
            try:
                # watch_tickers 阻塞直到收到新数据
                tickers = await exchange.watch_tickers(self.symbols)

                # 解析并更新缓存
                updated = 0
                for symbol, ticker in tickers.items():
                    parsed = _parse_ticker(ticker)
                    if parsed:
                        self.price_cache[exchange_name][symbol] = parsed
                        updated += 1

                # 更新状态
                if updated > 0:
                    self._connected[exchange_name] = True
                    self.error_counts[exchange_name] = 0

                    # 计算延迟：用最新 ticker 的 timestamp 与当前时间差
                    latest_ts = max(
                        (t.get("timestamp") or 0 for t in tickers.values() if t),
                        default=0,
                    )
                    if latest_ts > 0:
                        self.latencies[exchange_name] = round(
                            max(0, time.time() * 1000 - latest_ts), 2
                        )

            except asyncio.CancelledError:
                # 任务被取消（关闭时），正常退出
                logger.info("%s 的 WebSocket 监听已停止", exchange_name)
                break

            except Exception as e:
                # 记录错误，等待后重试
                logger.warning("%s WebSocket 异常: %s，%d秒后重试",
                               exchange_name, e, WS_RECONNECT_DELAY)
                self.error_counts[exchange_name] = (
                    self.error_counts.get(exchange_name, 0) + 1
                )
                self._connected[exchange_name] = False
                await asyncio.sleep(WS_RECONNECT_DELAY)

    def get_prices(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        返回当前缓存的价格数据（无网络 I/O，即时返回）

        Returns:
            价格快照字典，格式为 {exchange: {symbol: {bid, ask, last, volume, timestamp}}}
        """
        # 只返回有数据的交易所
        return {
            ex: prices for ex, prices in self.price_cache.items() if prices
        }

    def get_exchange_status(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有交易所的运行状态（与 PriceScanner 接口兼容）

        Returns:
            各交易所的状态字典，包含连接状态、错误次数和延迟信息
        """
        status: Dict[str, Dict[str, Any]] = {}
        for ex_name in self.exchanges:
            status[ex_name] = {
                "name": ex_name,
                "enabled": ex_name in self._exchange_instances,
                "connected": self._connected.get(ex_name, False),
                "error_count": self.error_counts.get(ex_name, 0),
                "latency_ms": self.latencies.get(ex_name, 0.0),
            }
        return status

    async def close(self) -> None:
        """关闭所有 WS 连接和后台任务，释放资源"""
        # 取消所有后台监听任务
        for task in self._ws_tasks:
            task.cancel()

        # 等待任务完成取消
        if self._ws_tasks:
            await asyncio.gather(*self._ws_tasks, return_exceptions=True)
        self._ws_tasks.clear()

        # 关闭所有交易所连接
        for ex_name, exchange in self._exchange_instances.items():
            try:
                await exchange.close()
                logger.debug("已关闭 WS 交易所连接: %s", ex_name)
            except Exception as e:
                logger.warning("关闭 WS 交易所 %s 连接失败: %s", ex_name, e)

        self._exchange_instances.clear()
        logger.info("WebSocket 扫描器已关闭")
