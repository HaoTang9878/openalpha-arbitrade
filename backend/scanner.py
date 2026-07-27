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

# WS 连续失败多少次后降级为 REST 轮询
WS_FALLBACK_THRESHOLD = 3

# REST 轮询间隔（秒）
REST_POLL_INTERVAL = 8

# REST 降级后多久尝试恢复 WS（秒）
WS_RECOVERY_INTERVAL = 60

# watch_tickers 超时时间（秒），超时视为失败
WS_WATCH_TIMEOUT = 15

# 已知 WebSocket 不稳定的交易所，强制使用 REST 轮询
WS_BLACKLIST: set = {"bybit", "gate", "kraken", "kucoin"}


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

        # 后台 L2 订单簿监听任务
        self._orderbook_tasks: List[asyncio.Task] = []

        # 内存价格缓存（实时更新）
        self.price_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # L2 订单簿缓存 {exchange: {symbol: {"bids": [[price, qty],...], "asks": [[price, qty],...]}}}
        self.orderbook_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # 错误计数和延迟（与 PriceScanner 兼容）
        self.error_counts: Dict[str, int] = {}
        self.latencies: Dict[str, float] = {}

        # 连接状态标记
        self._connected: Dict[str, bool] = {}

        # WS 连续失败计数（用于决定是否降级为 REST）
        self._ws_failures: Dict[str, int] = {}

        # 是否正在使用 REST 降级模式
        self._rest_mode: Dict[str, bool] = {}

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

                # okx 专用：禁用 L2 订单簿 checksum 校验。
                # ccxt.pro okx 的 handle_order_book_message 在 market 未加载完成
                # 或 instId 不在 markets 中时，safe_symbol 返回 None，随后
                # orderbook_checksum_message(None) 执行 `None + '  = False'`
                # 抛出 TypeError: NoneType + str。该异常发生在 ccxt 内部
                # message handler 的 Future 中，无法被外层 try/except 捕获，
                # 导致 `Future exception was never retrieved` 刷屏。
                # 禁用 checksum 后 ccxt 不再调用 orderbook_checksum_message，
                # 从根源上消除该 TypeError。
                if ex_name == "okx":
                    exchange_config["options"]["watchOrderBook"] = {
                        "checksum": False,
                    }

                # 注入 API 密钥（如有）
                if self.config and ex_name in self.config.api_keys:
                    exchange_config.update(self.config.api_keys[ex_name])

                self._exchange_instances[ex_name] = exchange_class(exchange_config)
                self.error_counts[ex_name] = 0
                self.latencies[ex_name] = 0.0
                self._connected[ex_name] = False
                self._ws_failures[ex_name] = 0
                # 黑名单交易所直接使用 REST 模式
                self._rest_mode[ex_name] = ex_name in WS_BLACKLIST
                self.price_cache[ex_name] = {}
                mode = "REST" if ex_name in WS_BLACKLIST else "WebSocket"
                logger.debug("已初始化 WS 交易所: %s (模式: %s)", ex_name, mode)

            except Exception as e:
                logger.error("初始化 WS 交易所 %s 失败: %s", ex_name, e)
                self.error_counts[ex_name] = 1

        logger.info(
            "WebSocket 扫描器初始化完成，成功初始化 %d/%d 个交易所",
            len(self._exchange_instances),
            len(self.exchanges),
        )

    async def start(self) -> None:
        """为每个交易所启动 watch_tickers 后台监听任务，并为非黑名单交易所启动 L2 订单簿监听"""
        for ex_name in self._exchange_instances:
            task = asyncio.create_task(self._watch_exchange(ex_name))
            self._ws_tasks.append(task)
            logger.info("已启动 %s 的 WebSocket 监听", ex_name)

        # 为非黑名单交易所启动 L2 订单簿监听（仅前 5 个交易对，控制连接数）
        # watch_order_book 每次只能订阅一个 symbol，仅对主流币订阅以避免过多连接
        # 防御性过滤：剔除 None / 空字符串 / 非字符串 symbol，避免 ccxt 内部
        # `symbol + '  = False'` 抛出 TypeError: NoneType + str
        ob_symbols = [
            s for s in self.symbols[:5] if s and isinstance(s, str)
        ]
        if ob_symbols:
            for ex_name in self._exchange_instances:
                if ex_name in WS_BLACKLIST:
                    continue
                ob_task = asyncio.create_task(
                    self._watch_orderbook_loop(ex_name, ob_symbols)
                )
                self._orderbook_tasks.append(ob_task)
                logger.info(
                    "已启动 %s 的 L2 订单簿监听（%d 个交易对: %s）",
                    ex_name, len(ob_symbols), ob_symbols,
                )

    async def _watch_orderbook_loop(
        self, exchange_name: str, symbols: List[str]
    ) -> None:
        """
        监听单个交易所多个交易对的 L2 订单簿，实时更新订单簿缓存

        ccxt.pro 的 watch_order_book 每次只能订阅一个 symbol，因此为每个
        symbol 启动独立的并发监听任务以降低延迟。

        Args:
            exchange_name: 交易所名称
            symbols: 要监听 L2 订单簿的交易对列表
        """
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return

        # 防御性过滤：剔除 None / 空字符串 / 非字符串的 symbol，
        # 避免传递给 _watch_single_orderbook 后触发 ccxt 内部
        # `symbol + '  = False'` 的 TypeError: NoneType + str
        valid_symbols = [
            s for s in symbols if s and isinstance(s, str)
        ]
        if len(valid_symbols) < len(symbols):
            skipped = [
                repr(s) for s in symbols if not (s and isinstance(s, str))
            ]
            logger.warning(
                "%s 订单簿监听过滤掉无效 symbol: %s",
                exchange_name, skipped,
            )

        if not valid_symbols:
            logger.warning(
                "%s 订单簿监听无有效 symbol，跳过启动", exchange_name,
            )
            return

        # 为每个 symbol 启动独立的订单簿监听任务
        ob_tasks = [
            asyncio.create_task(
                self._watch_single_orderbook(exchange_name, symbol)
            )
            for symbol in valid_symbols
        ]

        try:
            await asyncio.gather(*ob_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for t in ob_tasks:
                t.cancel()
            await asyncio.gather(*ob_tasks, return_exceptions=True)
            raise

    async def _watch_single_orderbook(
        self, exchange_name: str, symbol: str
    ) -> None:
        """
        监听单个交易对的 L2 订单簿更新，仅缓存前 10 档买卖盘

        Args:
            exchange_name: 交易所名称
            symbol: 交易对
        """
        # 防御性检查：symbol 为 None 时直接退出，避免后续日志拼接和
        # ccxt 内部 `symbol + '  = False'` 抛出 TypeError: NoneType + str
        if not symbol or not isinstance(symbol, str):
            logger.warning(
                "%s 订单簿监听收到无效 symbol（None 或非字符串），跳过该交易对",
                exchange_name,
            )
            return

        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return

        # 确保该交易所在订单簿缓存中有条目
        if exchange_name not in self.orderbook_cache:
            self.orderbook_cache[exchange_name] = {}

        while True:
            try:
                orderbook = await exchange.watch_order_book(symbol)

                # 防御性检查：orderbook 为 None 或缺少 bids/asks 时跳过缓存
                # （ccxt 某些异常路径可能返回不完整数据）
                if not orderbook or not isinstance(orderbook, dict):
                    await asyncio.sleep(WS_RECONNECT_DELAY)
                    continue

                bids = orderbook.get("bids") or []
                asks = orderbook.get("asks") or []
                if not bids or not asks:
                    await asyncio.sleep(WS_RECONNECT_DELAY)
                    continue

                # 只缓存前 10 档买卖盘，控制内存占用
                self.orderbook_cache[exchange_name][symbol] = {
                    "bids": bids[:10],
                    "asks": asks[:10],
                    "timestamp": orderbook.get(
                        "timestamp", int(time.time() * 1000)
                    ),
                }
            except asyncio.CancelledError:
                logger.info(
                    "%s 的 %s 订单簿监听已停止", exchange_name, symbol
                )
                raise
            except TypeError as e:
                # 单独捕获 TypeError：ccxt.pro okx 内部 orderbook_checksum_message
                # 在 symbol 为 None 时会执行 `symbol + '  = False'` 抛出
                # TypeError: NoneType + str。这是 ccxt 库的已知 bug，
                # 不计入 WS 失败计数（避免误降级 REST），仅去重告警后重试。
                error_key = f"ob_typeerr:{exchange_name}:{symbol}:{str(e)[:50]}"
                now = time.time()
                if not hasattr(self, "_last_warn_time"):
                    self._last_warn_time = {}
                last_warn = self._last_warn_time.get(error_key, 0)
                if now - last_warn > 300:  # 5 分钟
                    logger.warning(
                        "%s 监听 %s 订单簿遇到 ccxt 内部 TypeError（已知 bug，已忽略）: %s",
                        exchange_name, symbol, e,
                    )
                    self._last_warn_time[error_key] = now
                # 失败后短暂等待再重试，不影响主流程
                await asyncio.sleep(WS_RECONNECT_DELAY)
            except Exception as e:
                # 去重告警：同一错误 5 分钟内只告警一次，避免刷屏
                error_key = f"ob:{exchange_name}:{symbol}:{str(e)[:50]}"
                now = time.time()
                if not hasattr(self, "_last_warn_time"):
                    self._last_warn_time = {}
                last_warn = self._last_warn_time.get(error_key, 0)
                if now - last_warn > 300:  # 5 分钟
                    logger.warning(
                        "%s 监听 %s 订单簿失败: %s",
                        exchange_name, symbol, e,
                    )
                    self._last_warn_time[error_key] = now
                # 失败后短暂等待再重试，不影响主流程
                await asyncio.sleep(WS_RECONNECT_DELAY)

    async def _watch_exchange(self, exchange_name: str) -> None:
        """
        监听单个交易所的 ticker 更新，实时更新内存缓存

        优先使用 WebSocket，连续失败超过阈值后自动降级为 REST 轮询。
        REST 模式下定期尝试恢复 WebSocket 连接。
        """
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return

        # 获取该交易所实际支持的交易对（过滤掉不支持的）
        valid_symbols = await self._get_valid_symbols(exchange_name, exchange)
        logger.info("开始监听 %s 的行情数据（%d/%d 交易对）",
                    exchange_name, len(valid_symbols), len(self.symbols))

        while True:
            # 判断当前模式
            if self._rest_mode.get(exchange_name, False):
                # REST 降级模式：轮询获取数据
                await self._rest_poll_loop(exchange_name, valid_symbols)
            else:
                # WebSocket 模式
                await self._ws_watch_loop(exchange_name, valid_symbols)

    async def _get_valid_symbols(self, exchange_name: str, exchange: Any) -> list:
        """
        获取该交易所实际支持的自选交易对

        通过 load_markets 加载交易所市场数据，过滤出支持的交易对。
        如果加载失败，返回全部交易对（让后续请求自行报错）。
        """
        try:
            await exchange.load_markets()
            valid = [s for s in self.symbols if s in exchange.markets]
            if len(valid) < len(self.symbols):
                skipped = set(self.symbols) - set(valid)
                logger.info("%s 不支持的交易对: %s", exchange_name, skipped)
            return valid if valid else self.symbols
        except Exception as e:
            logger.warning("%s 加载市场数据失败: %s，使用全部交易对", exchange_name, e)
            return self.symbols

    async def _ws_watch_loop(self, exchange_name: str, symbols: list = None) -> None:
        """WebSocket 监听循环（单次尝试，失败后由外层决定是否降级）"""
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return

        try:
            # watch_tickers 阻塞直到收到新数据，加超时防止无限阻塞
            watch_list = symbols if symbols else self.symbols
            tickers = await asyncio.wait_for(
                exchange.watch_tickers(watch_list),
                timeout=WS_WATCH_TIMEOUT,
            )

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
                self._ws_failures[exchange_name] = 0

                # 计算延迟：优先用 ticker 的 timestamp
                latest_ts = max(
                    (t.get("timestamp") or 0 for t in tickers.values() if t),
                    default=0,
                )
                if latest_ts > 0:
                    self.latencies[exchange_name] = round(
                        max(0, time.time() * 1000 - latest_ts), 2
                    )
                else:
                    # 交易所不推送 timestamp（如 gate），用轮询间隔估算
                    interval = self.config.model.scan_interval if self.config else 3
                    self.latencies[exchange_name] = round(
                        max(1, interval * 1000 * 0.5), 2
                    )

        except asyncio.CancelledError:
            logger.info("%s 的监听已停止", exchange_name)
            raise

        except TypeError as e:
            # 单独捕获 TypeError：ccxt.pro okx 共享单一 WS 连接，
            # orderbook 消息处理在 symbol 为 None 时会执行
            # `symbol + '  = False'` 抛出 TypeError: NoneType + str，
            # 该异常会传播到 watch_tickers 的 Future。这是 ccxt 库的已知 bug，
            # 不应计入 WS 失败计数（避免误降级 REST），仅去重告警后重试。
            error_key = f"ws_typeerr:{exchange_name}:{str(e)[:50]}"
            now = time.time()
            if not hasattr(self, "_last_warn_time"):
                self._last_warn_time = {}
            last_warn = self._last_warn_time.get(error_key, 0)
            if now - last_warn > 300:  # 5 分钟
                logger.warning(
                    "%s WebSocket 遇到 ccxt 内部 TypeError（已知 bug，已忽略）: %s",
                    exchange_name, e,
                )
                self._last_warn_time[error_key] = now
            # 不增加 _ws_failures / error_counts，避免误降级 REST
            await asyncio.sleep(WS_RECONNECT_DELAY)

        except Exception as e:
            self._ws_failures[exchange_name] = (
                self._ws_failures.get(exchange_name, 0) + 1
            )
            self.error_counts[exchange_name] = (
                self.error_counts.get(exchange_name, 0) + 1
            )
            self._connected[exchange_name] = False

            failures = self._ws_failures[exchange_name]

            # 连续失败超过阈值，降级为 REST
            if failures >= WS_FALLBACK_THRESHOLD:
                logger.warning(
                    "%s WebSocket 连续失败 %d 次，降级为 REST 轮询",
                    exchange_name, failures,
                )
                self._rest_mode[exchange_name] = True
            else:
                logger.warning(
                    "%s WebSocket 异常: %s（第 %d 次），%d秒后重试",
                    exchange_name, e, failures, WS_RECONNECT_DELAY,
                )
                await asyncio.sleep(WS_RECONNECT_DELAY)

    async def _rest_poll_loop(self, exchange_name: str, symbols: list = None) -> None:
        """REST 轮询循环（降级模式，黑名单交易所不恢复 WS）"""
        exchange = self._exchange_instances.get(exchange_name)
        if exchange is None:
            return

        start_time = time.time()

        try:
            # 用 REST 方式获取 tickers（ccxt.pro 实例继承 REST 方法）
            poll_list = symbols if symbols else self.symbols
            tickers = await exchange.fetch_tickers(poll_list)

            # 解析并更新缓存
            updated = 0
            for symbol, ticker in tickers.items():
                parsed = _parse_ticker(ticker)
                if parsed:
                    self.price_cache[exchange_name][symbol] = parsed
                    updated += 1

            if updated > 0:
                self._connected[exchange_name] = True
                self.error_counts[exchange_name] = 0

                # 计算延迟（REST 请求耗时）
                elapsed_ms = (time.time() - start_time) * 1000
                self.latencies[exchange_name] = round(elapsed_ms, 2)

        except asyncio.CancelledError:
            logger.info("%s 的 REST 轮询已停止", exchange_name)
            raise

        except Exception as e:
            # 去重：同一交易所同一错误 5 分钟内只告警一次
            error_key = f"{exchange_name}:{str(e)[:50]}"
            now = time.time()
            last_warn = getattr(self, "_last_warn_time", {}).get(error_key, 0)
            if now - last_warn > 300:  # 5 分钟
                logger.warning("%s REST 轮询失败: %s", exchange_name, e)
                if not hasattr(self, "_last_warn_time"):
                    self._last_warn_time = {}
                self._last_warn_time[error_key] = now
            self.error_counts[exchange_name] = (
                self.error_counts.get(exchange_name, 0) + 1
            )

        # 黑名单交易所不尝试恢复 WS
        if exchange_name not in WS_BLACKLIST:
            # 累计 REST 时间，超过阈值后尝试恢复 WS
            if not hasattr(self, "_rest_start_times"):
                self._rest_start_times: Dict[str, float] = {}
            if exchange_name not in self._rest_start_times:
                self._rest_start_times[exchange_name] = time.time()

            rest_total = time.time() - self._rest_start_times.get(exchange_name, time.time())
            if rest_total > WS_RECOVERY_INTERVAL:
                logger.info("%s 尝试恢复 WebSocket 连接", exchange_name)
                self._rest_mode[exchange_name] = False
                self._ws_failures[exchange_name] = 0
                self._rest_start_times.pop(exchange_name, None)

        await asyncio.sleep(REST_POLL_INTERVAL)

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

    def get_orderbooks(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        返回当前 L2 订单簿缓存（无网络 I/O，即时返回）

        Returns:
            订单簿缓存字典，格式为
            {exchange: {symbol: {"bids": [[price, qty],...], "asks": [[price, qty],...]}}}
        """
        # 只返回有数据的交易所
        return {
            ex: obs for ex, obs in self.orderbook_cache.items() if obs
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
                "mode": "REST" if self._rest_mode.get(ex_name, False) else "WebSocket",
            }
        return status

    async def close(self) -> None:
        """关闭所有 WS 连接和后台任务，释放资源"""
        # 取消所有后台监听任务（ticker + orderbook）
        for task in self._ws_tasks:
            task.cancel()
        for task in self._orderbook_tasks:
            task.cancel()

        # 等待任务完成取消
        all_tasks = self._ws_tasks + self._orderbook_tasks
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._ws_tasks.clear()
        self._orderbook_tasks.clear()

        # 关闭所有交易所连接
        for ex_name, exchange in self._exchange_instances.items():
            try:
                await exchange.close()
                logger.debug("已关闭 WS 交易所连接: %s", ex_name)
            except Exception as e:
                logger.warning("关闭 WS 交易所 %s 连接失败: %s", ex_name, e)

        self._exchange_instances.clear()
        logger.info("WebSocket 扫描器已关闭")
