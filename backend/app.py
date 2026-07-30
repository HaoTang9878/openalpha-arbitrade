"""
OpenAlpha 套利交易系统 - API 服务

提供 REST API 和 WebSocket 接口，支持：
- 启动/停止价格监控
- 启动/停止自动套利
- 获取实时价格数据
- 获取套利机会列表
- 获取交易历史
- 修改系统配置
- WebSocket 实时推送

后台任务：
- 价格扫描循环（每 scan_interval 秒执行一次）
- 套利检测循环（扫描完成后自动检测）
- 自动执行循环（检测到机会后自动执行）

启动方式：
    uvicorn backend.app:app --host 0.0.0.0 --port 8070
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from backend.auth import add_auth_middleware  # 鉴权中间件

from .arbitrage import ArbitrageDetector
from .config import (
    Config,
    SUPPORTED_EXCHANGES,
    SYMBOL_CATEGORIES,
    get_symbol_category,
)
from .database import Database
from .executor import TradeExecutor
from .models import ArbitrageOpportunity, OrderStatus, TradeResult
from .notifier import Notifier
from .risk_manager import RiskManager
from .scanner import PriceScanner, WebSocketScanner
from .backtest import HistoryCollector, BacktestEngine
from .user_auth import UserAuth
from .ai_advisor import AIAdvisor
from .strategies import (
    StrategyRegistry, StrategyOrchestrator,
    GridStrategy, DcaStrategy, TriangularStrategy,
)
from .tranche import StrategyConfig, Portfolio, GridArbitrageEngine
from .store import JsonlEventStore, RuntimeState

# ----------------------------------------------------------------------------
# 日志配置
# ----------------------------------------------------------------------------
# 日志目录（Docker 中挂载到 ./data/logs）
_LOG_DIR = Path(__file__).parent.parent / "data" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志格式
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 控制台处理器
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))

# 文件处理器（滚动：每个文件最大 5MB，保留 5 个备份）
_file_handler = RotatingFileHandler(
    filename=str(_LOG_DIR / "arbitrage.log"),
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))

# 配置根日志
logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
    handlers=[_console_handler, _file_handler],
)
logger = logging.getLogger("openalpha")

# ----------------------------------------------------------------------------
# 全局状态
# ----------------------------------------------------------------------------
# 自动加载 config.yaml（如果存在）
_config_path = str(Path(__file__).parent.parent / "config.yaml")
config = Config(config_path=_config_path)

scanner: Optional[PriceScanner] = None
detector: Optional[ArbitrageDetector] = None
executor: Optional[TradeExecutor] = None
risk_manager: Optional[RiskManager] = None
database: Optional[Database] = None
notifier: Optional[Notifier] = None

# 运行状态标志
scanner_running = False
arbitrage_running = False

# 最新数据缓存
latest_prices: Dict[str, Dict[str, Dict[str, Any]]] = {}
latest_opportunities: List[ArbitrageOpportunity] = []

# 后台任务引用
scanner_task: Optional[asyncio.Task] = None
arbitrage_task: Optional[asyncio.Task] = None

# AI 策略推荐器
ai_advisor: Optional[AIAdvisor] = None

# 用户认证
user_auth: Optional[UserAuth] = None

# 回测引擎
history_collector: Optional[HistoryCollector] = None
backtest_engine: Optional[BacktestEngine] = None

# 策略注册中心与调度器
strategy_registry: Optional[StrategyRegistry] = None
strategy_orchestrator: Optional[StrategyOrchestrator] = None

# 运行时状态（lifespan 初始化）
runtime_state: RuntimeState = None
event_store: JsonlEventStore = None

# WebSocket 连接管理
ws_connections: Set[WebSocket] = set()

# 系统启动时间
system_start_time = time.time()


# ----------------------------------------------------------------------------
# WebSocket 管理器
# ----------------------------------------------------------------------------
class ConnectionManager:
    """WebSocket 连接管理器，负责管理客户端连接和消息广播"""

    async def connect(self, websocket: WebSocket) -> None:
        """接受新的 WebSocket 连接并加入连接池"""
        await websocket.accept()
        ws_connections.add(websocket)
        logger.info("WebSocket 客户端已连接，当前连接数: %d", len(ws_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """从连接池中移除断开的连接"""
        ws_connections.discard(websocket)
        logger.info("WebSocket 客户端已断开，当前连接数: %d", len(ws_connections))

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """向所有已连接的客户端广播消息"""
        if not ws_connections:
            return

        text = json.dumps(message, ensure_ascii=False, default=str)
        disconnected = set()

        for ws in ws_connections:
            try:
                await ws.send_text(text)
            except Exception as e:
                logger.debug("发送 WebSocket 消息失败: %s", e)
                disconnected.add(ws)

        # 清理断开的连接
        ws_connections.difference_update(disconnected)


manager = ConnectionManager()

# 日志广播队列（桥接同步 logging 与异步 WebSocket）
log_queue: asyncio.Queue = asyncio.Queue()


class WebSocketLogHandler(logging.Handler):
    """将日志记录推入异步队列，由后台任务转发到 WebSocket 客户端"""

    def emit(self, record: logging.LogRecord) -> None:
        """将日志记录格式化后推入队列（非阻塞）"""
        try:
            log_queue.put_nowait({
                "level": record.levelname,
                "message": record.getMessage(),
                "timestamp": int(time.time() * 1000),
            })
        except asyncio.QueueFull:
            pass  # 队列满时丢弃日志，避免阻塞主线程


# 注册日志处理器（仅转发 WARNING 及以上级别，避免噪音）
_ws_log_handler = WebSocketLogHandler(level=logging.WARNING)
_ws_log_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_ws_log_handler)


async def log_broadcast_loop() -> None:
    """从日志队列取出记录并广播到所有 WebSocket 客户端"""
    while True:
        try:
            log_data = await log_queue.get()
            if ws_connections:
                await manager.broadcast({
                    "type": "logs",
                    "data": log_data,
                    "timestamp": int(time.time() * 1000),
                })
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("日志广播异常: %s", e)


# ----------------------------------------------------------------------------
# 后台任务
# ----------------------------------------------------------------------------
async def scanner_loop() -> None:
    """
    价格扫描循环

    WebSocket 模式：直接读缓存（无网络 I/O），每 scan_interval 秒广播一次
    REST 模式：每 scan_interval 秒发起网络请求获取全量数据
    扫描完成后自动触发套利检测。
    """
    global latest_prices, latest_opportunities

    # 判断扫描器模式
    use_websocket = hasattr(scanner, "get_prices")
    mode_name = "WebSocket" if use_websocket else "REST"
    logger.info("价格扫描循环已启动（%s 模式），间隔 %d 秒",
                mode_name, config.model.scan_interval)

    while scanner_running:
        try:
            if scanner:
                # WS 模式：读内存缓存；REST 模式：发网络请求
                if use_websocket:
                    prices = scanner.get_prices()
                else:
                    prices = await scanner.scan_all()

                if prices:
                    latest_prices = prices
                    logger.debug("价格数据已更新，%d 个交易所", len(prices))

                    # 自动检测套利机会
                    if detector:
                        # 传入 L2 订单簿缓存用于动态滑点计算
                        # （仅 WebSocketScanner 支持，REST 模式返回 None 回退固定滑点）
                        orderbooks = (
                            scanner.get_orderbooks()
                            if hasattr(scanner, "get_orderbooks")
                            else None
                        )
                        opportunities = detector.detect(
                            prices, orderbooks=orderbooks
                        )
                        latest_opportunities = opportunities

                        # 持久化套利机会快照（用于回测分析）
                        if opportunities and database:
                            database.save_opportunities(opportunities)

                        # 广播价格更新
                        await manager.broadcast({
                            "type": "prices",
                            "data": prices,
                            "timestamp": int(time.time() * 1000),
                        })

                        # 广播套利机会
                        if opportunities:
                            await manager.broadcast({
                                "type": "opportunities",
                                "data": [op.model_dump() for op in opportunities],
                                "timestamp": int(time.time() * 1000),
                            })

                            # Telegram 告警：只通知前 3 个最佳机会
                            # （Notifier 内部会做净利润率阈值和频率限制过滤）
                            if notifier:
                                for op in opportunities[:3]:
                                    try:
                                        notifier.notify_opportunity(op)
                                    except Exception as ne:  # noqa: BLE001
                                        logger.debug("机会告警通知失败: %s", ne)

        except Exception as e:
            logger.error("价格扫描循环异常: %s", e, exc_info=True)
            # 系统错误告警（通知失败不影响主流程）
            if notifier:
                try:
                    notifier.notify_error("价格扫描循环异常: %s" % e)
                except Exception as ne:  # noqa: BLE001
                    logger.debug("错误告警通知失败: %s", ne)

        # 等待下一次扫描
        await asyncio.sleep(config.model.scan_interval)

    logger.info("价格扫描循环已停止")


async def arbitrage_loop() -> None:
    """
    自动套利执行循环

    持续检查最新的套利机会，自动执行符合条件的交易。
    仅在 arbitrage_running 为 True 时执行。
    """
    logger.info("自动套利循环已启动")

    while arbitrage_running:
        try:
            if latest_opportunities and executor:
                best_op = latest_opportunities[0]

                # 风控检查
                if risk_manager and not risk_manager.check(best_op, latest_prices):
                    logger.warning("自动套利被风控拒绝，跳过本轮")
                else:
                    logger.info(
                        "自动执行套利: %s 净利润率=%.4f%%",
                        best_op.symbol, best_op.net_profit_rate * 100,
                    )

                    # 记录交易开始
                    if risk_manager:
                        risk_manager.record_trade_start(best_op)

                    result = await executor.execute(best_op)

                    # 记录交易结束
                    if risk_manager:
                        risk_manager.record_trade_end(result)

                    # 广播交易结果
                    await manager.broadcast({
                        "type": "trade",
                        "data": result.model_dump(),
                        "timestamp": int(time.time() * 1000),
                    })

                    # Telegram 告警：交易执行结果通知
                    if notifier:
                        try:
                            status = result.status.value if hasattr(
                                result.status, "value"
                            ) else str(result.status)
                            notifier.notify_status(
                                "套利交易执行完成\n"
                                "交易对: %s\n"
                                "买入: %s @ %.4f\n"
                                "卖出: %s @ %.4f\n"
                                "数量: %.4f\n"
                                "利润: %.4f USDT\n"
                                "状态: %s"
                                % (
                                    result.symbol,
                                    result.buy_exchange,
                                    result.buy_price,
                                    result.sell_exchange,
                                    result.sell_price,
                                    result.amount,
                                    result.profit,
                                    status,
                                )
                            )
                        except Exception as ne:  # noqa: BLE001
                            logger.debug("交易结果通知失败: %s", ne)

        except Exception as e:
            logger.error("自动套利循环异常: %s", e, exc_info=True)
            # 系统错误告警（通知失败不影响主流程）
            if notifier:
                try:
                    notifier.notify_error("自动套利循环异常: %s" % e)
                except Exception as ne:  # noqa: BLE001
                    logger.debug("错误告警通知失败: %s", ne)

        # 等待下一轮检查（使用较短的间隔以快速响应机会）
        await asyncio.sleep(config.model.scan_interval)

    logger.info("自动套利循环已停止")


# ----------------------------------------------------------------------------
# 生命周期管理
# ----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，负责初始化和清理资源"""
    global scanner, detector, executor, risk_manager, database, notifier
    global scanner_running, scanner_task
    global strategy_registry, strategy_orchestrator
    global history_collector, backtest_engine
    global user_auth
    global ai_advisor
    global runtime_state, event_store

    logger.info("OpenAlpha 套利系统启动中...")

    # 初始化 SQLite 持久化层（交易历史 + 套利机会记录）
    db_path = str(Path(__file__).parent.parent / "data" / "arbitrage.db")
    database = Database(db_path)

    # 初始化 Telegram 告警通知器（未配置时静默跳过，不影响主流程）
    notifier = Notifier()

    # 初始化套利检测器、交易执行器和风控管理器
    detector = ArbitrageDetector(config)
    executor = TradeExecutor(config, config.api_keys, database=database)
    risk_manager = RiskManager(config, notifier=notifier)

    # 初始化策略注册中心与调度器
    strategy_registry = StrategyRegistry()
    strategy_orchestrator = StrategyOrchestrator(strategy_registry)
    # 注入价格数据提供者（使用 latest_prices 全局变量）
    strategy_orchestrator.set_prices_provider(lambda: latest_prices)
    logger.info("策略注册中心已初始化")

    # 初始化回测引擎
    history_collector = HistoryCollector(database)
    backtest_engine = BacktestEngine(history_collector)
    logger.info("回测引擎已初始化")

    # 初始化用户认证
    user_auth = UserAuth(database)
    logger.info("用户认证已初始化")

    # 初始化 AI 策略推荐器
    ai_advisor = AIAdvisor()
    logger.info("AI 策略推荐器已初始化")

    # 初始化 JSONL 事件存储与运行时状态（Portfolio / StrategyConfig）
    event_store = JsonlEventStore()
    strategy_config = StrategyConfig()
    runtime_state = RuntimeState(strategy_config)
    logger.info("Portfolio + Event store initialized")

    # 优先使用 WebSocket 实时扫描器，失败则回退到 REST 轮询
    try:
        scanner = WebSocketScanner(
            config.model.exchanges, config.model.symbols, config
        )
        await scanner.start()
        logger.info("WebSocket 扫描器已启动")
    except Exception as e:
        logger.warning("WebSocket 初始化失败，回退到 REST: %s", e)
        scanner = PriceScanner(
            config.model.exchanges, config.model.symbols, config
        )

    logger.info("系统初始化完成，服务端口 8070")

    # 启动日志广播后台任务
    log_task = asyncio.create_task(log_broadcast_loop())

    # 自动启动价格扫描，用户无需手动点击
    scanner_running = True
    scanner_task = asyncio.create_task(scanner_loop())
    logger.info("价格扫描已自动启动")

    # 系统启动状态通知
    if notifier:
        try:
            notifier.notify_status(
                "OpenAlpha 套利系统已启动\n"
                "交易所: %s\n"
                "交易对: %d 个\n"
                "模拟交易: %s"
                % (
                    ", ".join(config.model.exchanges),
                    len(config.model.symbols),
                    "是" if config.model.paper_trade else "否",
                )
            )
        except Exception as ne:  # noqa: BLE001
            logger.debug("启动状态通知失败: %s", ne)

    yield

    # 清理资源
    scanner_running = False
    arbitrage_running = False

    # 取消日志广播任务
    log_task.cancel()
    try:
        await log_task
    except asyncio.CancelledError:
        pass

    if scanner:
        await scanner.close()
    if executor:
        await executor.close()
    if database:
        database.close()

    logger.info("OpenAlpha 套利系统已关闭")


# ----------------------------------------------------------------------------
# FastAPI 应用
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 限流中间件：IP 级请求限流（60 次/分钟，写操作 20 次/分钟）
# ---------------------------------------------------------------------------
import time as _time
from collections import defaultdict as _defaultdict

class RateLimitMiddleware:
    """简单的内存限流中间件，按 IP 地址限制请求频率"""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        self.app = app
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict = _defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP（支持 Cloudflare 和反向代理）"""
        # Cloudflare CF-Connecting-IP 头
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        # X-Forwarded-For 头
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        # 直连 IP
        return request.client.host if request.client else "unknown"

    def _cleanup_old(self, ip: str, now: float) -> None:
        """清理过期的时间戳"""
        cutoff = now - self.window
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        ip = self._get_client_ip(request)
        now = _time.time()
        self._cleanup_old(ip, now)

        if len(self._requests[ip]) >= self.max_requests:
            response = JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded",
                        "detail": f"请求过于频繁，每分钟最多 {self.max_requests} 次"},
            )
            await response(scope, receive, send)
            return

        self._requests[ip].append(now)
        await self.app(scope, receive, send)


app = FastAPI(
    title="OpenAlpha 套利交易系统",
    description="加密货币跨交易所套利交易系统 API",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- 鉴权中间件(写/执行操作需 Bearer token)----
add_auth_middleware(app)

# 限流：每 IP 每分钟最多 60 次请求
_rate_limit_store: dict = _defaultdict(list)
_RATE_LIMIT_MAX = 60
_RATE_LIMIT_WINDOW = 60  # 秒

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # 获取客户端 IP（支持 Cloudflare）
    cf_ip = request.headers.get("CF-Connecting-IP", "")
    xff = request.headers.get("X-Forwarded-For", "")
    client_ip = cf_ip.strip() or (xff.split(",")[0].strip() if xff else "") or (request.client.host if request.client else "unknown")

    now = _time.time()
    cutoff = now - _RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if t > cutoff]

    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "detail": f"请求过于频繁，每分钟最多 {_RATE_LIMIT_MAX} 次"},
        )

    _rate_limit_store[client_ip].append(now)
    response = await call_next(request)
    return response

# 挂载前端静态文件目录
# 优先使用 React 构建产物（frontend-react/dist），回退到旧版 HTML
frontend_react_path = Path(__file__).parent.parent / "frontend-react" / "dist"
frontend_legacy_path = Path(__file__).parent.parent / "frontend"

if frontend_react_path.exists():
    # React SPA 模式：挂载 dist 目录为静态文件
    app.mount("/assets", StaticFiles(directory=str(frontend_react_path / "assets")), name="assets")
elif frontend_legacy_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_legacy_path)), name="static")


# ----------------------------------------------------------------------------
# 页面路由
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """返回前端监控仪表盘页面（优先 React SPA，回退旧版 HTML）"""
    # React SPA 入口
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    # 旧版 HTML 回退
    legacy_index = frontend_legacy_path / "index.html"
    if legacy_index.exists():
        return HTMLResponse(content=legacy_index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


@app.get("/bots", response_class=HTMLResponse)
async def bots_page() -> HTMLResponse:
    """React SPA 路由：策略机器人页面"""
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


@app.get("/backtest", response_class=HTMLResponse)
async def backtest_page() -> HTMLResponse:
    """React SPA 路由：回测页面"""
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


@app.get("/heatmap", response_class=HTMLResponse)
async def heatmap_page() -> HTMLResponse:
    """React SPA 路由：热力图页面"""
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


@app.get("/reports", response_class=HTMLResponse)
async def reports_page() -> HTMLResponse:
    """React SPA 路由：每日报告页面"""
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page() -> HTMLResponse:
    """React SPA 路由：设置页面"""
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


# ----------------------------------------------------------------------------
# REST API 端点
# ----------------------------------------------------------------------------
@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 格式的监控指标端点"""
    lines = []
    lines.append("# HELP arbitrage_scanner_running Scanner running status")
    lines.append("# TYPE arbitrage_scanner_running gauge")
    lines.append(f"arbitrage_scanner_running {1 if scanner and hasattr(scanner, 'price_cache') else 0}")

    lines.append("# HELP arbitrage_opportunities_total Total opportunities detected")
    lines.append("# TYPE arbitrage_opportunities_total counter")
    lines.append(f"arbitrage_opportunities_total {len(latest_opportunities) if latest_opportunities else 0}")

    lines.append("# HELP arbitrage_trades_total Total trades executed")
    lines.append("# TYPE arbitrage_trades_total counter")
    trade_count = 0
    if executor:
        trade_count = len(executor.get_trade_history(10000))
    lines.append(f"arbitrage_trades_total {trade_count}")

    lines.append("# HELP arbitrage_uptime_seconds System uptime in seconds")
    lines.append("# TYPE arbitrage_uptime_seconds gauge")
    uptime = 0
    if scanner and hasattr(scanner, '_start_time'):
        import time as _t
        uptime = int(_t.time() - getattr(scanner, '_start_time', _t.time()))
    lines.append(f"arbitrage_uptime_seconds {uptime}")

    lines.append("# HELP arbitrage_exchanges_connected Number of connected exchanges")
    lines.append("# TYPE arbitrage_exchanges_connected gauge")
    connected = 0
    if scanner and hasattr(scanner, '_connected'):
        connected = sum(1 for v in scanner._connected.values() if v)
    lines.append(f"arbitrage_exchanges_connected {connected}")

    lines.append("# HELP arbitrage_risk_halted Risk management halted status")
    lines.append("# TYPE arbitrage_risk_halted gauge")
    halted = 0
    if risk_manager:
        halted = 1 if getattr(risk_manager, '_halted', False) else 0
    lines.append(f"arbitrage_risk_halted {halted}")

    lines.append("# HELP arbitrage_daily_pnl Daily PnL in USDT")
    lines.append("# TYPE arbitrage_daily_pnl gauge")
    pnl = 0.0
    if risk_manager:
        pnl = getattr(risk_manager, '_daily_pnl', 0.0)
    lines.append(f"arbitrage_daily_pnl {pnl}")

    return PlainTextResponse(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4",
    )


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    """获取系统整体运行状态"""
    uptime = int(time.time() - system_start_time)
    return {
        "scanner_running": scanner_running,
        "arbitrage_running": arbitrage_running,
        "exchanges_count": len(config.model.exchanges),
        "symbols_count": len(config.model.symbols),
        "opportunities_count": len(latest_opportunities),
        "trades_count": len(executor.trade_history) if executor else 0,
        "uptime_seconds": uptime,
        "paper_trade": config.model.paper_trade,
        "api_key_status": {
            ex: ex in config.api_keys for ex in config.model.exchanges
        },
        "risk_status": risk_manager.get_status() if risk_manager else None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/config")
async def get_config() -> Dict[str, Any]:
    """获取当前系统配置"""
    return config.to_dict()


@app.put("/api/config")
async def update_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """修改系统配置，支持部分更新"""
    old_exchanges = config.model.exchanges.copy()
    old_symbols = config.model.symbols.copy()

    config.update(data)

    # 如果交易所或交易对列表变化，需要重建扫描器
    if (
        config.model.exchanges != old_exchanges
        or config.model.symbols != old_symbols
    ) and scanner:
        await scanner.close()
        scanner.exchanges = config.model.exchanges
        scanner.symbols = config.model.symbols
        scanner._init_exchanges()

    logger.info("配置已通过 API 更新")
    return {"status": "ok", "config": config.to_dict()}


@app.post("/api/scanner/start")
async def start_scanner() -> Dict[str, Any]:
    """启动价格扫描"""
    global scanner_running, scanner_task

    if scanner_running:
        return {"status": "already_running"}

    scanner_running = True
    scanner_task = asyncio.create_task(scanner_loop())
    logger.info("价格扫描已启动")
    return {"status": "started"}


@app.post("/api/scanner/stop")
async def stop_scanner() -> Dict[str, Any]:
    """停止价格扫描"""
    global scanner_running

    if not scanner_running:
        return {"status": "already_stopped"}

    scanner_running = False
    if scanner_task:
        scanner_task.cancel()
    logger.info("价格扫描已停止")
    return {"status": "stopped"}


@app.get("/api/prices")
async def get_prices() -> Dict[str, Any]:
    """获取最新价格快照"""
    return {
        "prices": latest_prices,
        "timestamp": int(time.time() * 1000),
    }


@app.get("/api/opportunities")
async def get_opportunities() -> Dict[str, Any]:
    """获取当前检测到的套利机会列表"""
    return {
        "opportunities": [op.model_dump() for op in latest_opportunities],
        "count": len(latest_opportunities),
        "timestamp": int(time.time() * 1000),
    }


@app.post("/api/arbitrage/start")
async def start_arbitrage() -> Dict[str, Any]:
    """启动自动套利执行"""
    global arbitrage_running, arbitrage_task

    if arbitrage_running:
        return {"status": "already_running"}

    arbitrage_running = True
    arbitrage_task = asyncio.create_task(arbitrage_loop())
    logger.info("自动套利已启动")
    return {"status": "started"}


@app.post("/api/arbitrage/stop")
async def stop_arbitrage() -> Dict[str, Any]:
    """停止自动套利执行"""
    global arbitrage_running

    if not arbitrage_running:
        return {"status": "already_stopped"}

    arbitrage_running = False
    if arbitrage_task:
        arbitrage_task.cancel()
    logger.info("自动套利已停止")
    return {"status": "stopped"}


@app.get("/api/trades")
async def get_trades(limit: int = 50) -> Dict[str, Any]:
    """获取交易历史记录"""
    if not executor:
        return {"trades": [], "count": 0}

    history = executor.get_trade_history(limit)
    return {
        "trades": [t.model_dump() for t in history],
        "count": len(history),
    }


@app.post("/api/trades/execute")
async def execute_trade(opportunity_data: Dict[str, Any]) -> Dict[str, Any]:
    """手动执行单个套利机会（含风控检查）"""
    if not executor:
        return JSONResponse(
            status_code=500,
            content={"error": "执行器未初始化"},
        )

    try:
        # 从请求数据构建套利机会对象
        opportunity = ArbitrageOpportunity(**opportunity_data)

        # 风控检查
        if risk_manager and not risk_manager.check(opportunity, latest_prices):
            return JSONResponse(
                status_code=403,
                content={"error": "风控拒绝，请检查风控状态"},
            )

        # 记录交易开始
        if risk_manager:
            risk_manager.record_trade_start(opportunity)

        # 执行交易
        result = await executor.execute(opportunity)

        # 记录交易结束
        if risk_manager:
            risk_manager.record_trade_end(result)

        # 广播交易结果
        await manager.broadcast({
            "type": "trade",
            "data": result.model_dump(),
            "timestamp": int(time.time() * 1000),
        })

        return {"status": "ok", "result": result.model_dump()}
    except Exception as e:
        logger.error("手动执行交易失败: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.get("/api/exchanges")
async def get_exchanges() -> Dict[str, Any]:
    """获取交易所列表及其运行状态"""
    if scanner:
        statuses = scanner.get_exchange_status()
    else:
        statuses = {
            ex: {
                "name": ex,
                "enabled": ex in config.model.exchanges,
                "connected": False,
                "error_count": 0,
                "latency_ms": 0.0,
            }
            for ex in config.model.exchanges
        }

    return {
        "exchanges": list(statuses.values()),
        "supported": SUPPORTED_EXCHANGES,
    }


@app.get("/api/balances")
async def get_balances() -> Dict[str, Any]:
    """查询各交易所账户余额（需要配置 API Key）"""
    if not executor:
        return {"error": "执行器未初始化"}

    if not config.api_keys:
        return {
            "balances": {},
            "message": "未配置 API Key，请在 config.yaml 或环境变量中设置",
        }

    balances: Dict[str, Any] = {}
    for ex_name in config.model.exchanges:
        if ex_name not in config.api_keys:
            balances[ex_name] = {"error": "未配置 API Key"}
            continue

        try:
            exchange = executor._get_exchange(ex_name)
            if exchange is None:
                balances[ex_name] = {"error": "交易所实例创建失败"}
                continue

            balance = await exchange.fetch_balance()
            # 只保留有余额的资产
            free = balance.get("free", {})
            used = balance.get("used", {})
            total = balance.get("total", {})

            assets = {}
            for asset, amount in total.items():
                if isinstance(amount, (int, float)) and amount > 0:
                    assets[asset] = {
                        "free": free.get(asset, 0),
                        "used": used.get(asset, 0),
                        "total": amount,
                    }

            balances[ex_name] = {"assets": assets}
        except Exception as e:
            balances[ex_name] = {"error": str(e)}

    return {"balances": balances}


@app.post("/api/keys")
async def save_api_key(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    保存交易所 API 密钥到 config.yaml

    接收 {exchange, apiKey, secret} 并持久化到配置文件。
    """
    ex_name = data.get("exchange", "").strip().lower()
    api_key = data.get("apiKey", "").strip()
    secret = data.get("secret", "").strip()

    if not ex_name or not api_key or not secret:
        return JSONResponse(
            status_code=400,
            content={"error": "缺少必要参数: exchange, apiKey, secret"},
        )

    if ex_name not in SUPPORTED_EXCHANGES:
        return JSONResponse(
            status_code=400,
            content={"error": f"不支持的交易所: {ex_name}"},
        )

    try:
        # 更新内存中的 API Key
        config.api_keys[ex_name] = {"apiKey": api_key, "secret": secret}

        # 持久化到 config.yaml
        _save_keys_to_yaml(ex_name, {"apiKey": api_key, "secret": secret})

        # 更新执行器的交易所实例配置
        if executor and ex_name in executor._exchange_instances:
            await executor._exchange_instances[ex_name].close()
            del executor._exchange_instances[ex_name]

        logger.info("已保存 %s 的 API 密钥", ex_name)
        return {"status": "ok", "exchange": ex_name}
    except Exception as e:
        logger.error("保存 API 密钥失败: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.delete("/api/keys/{exchange}")
async def delete_api_key(exchange: str) -> Dict[str, Any]:
    """删除指定交易所的 API 密钥"""
    ex_name = exchange.strip().lower()

    if ex_name not in config.api_keys:
        return JSONResponse(
            status_code=404,
            content={"error": f"未找到 {ex_name} 的 API 密钥"},
        )

    try:
        # 从内存中删除
        del config.api_keys[ex_name]

        # 从 config.yaml 中删除
        _save_keys_to_yaml(ex_name, None)

        # 清除执行器中的旧实例
        if executor and ex_name in executor._exchange_instances:
            await executor._exchange_instances[ex_name].close()
            del executor._exchange_instances[ex_name]

        logger.info("已删除 %s 的 API 密钥", ex_name)
        return {"status": "ok", "exchange": ex_name}
    except Exception as e:
        logger.error("删除 API 密钥失败: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


def _save_keys_to_yaml(exchange: str, keys: Optional[Dict[str, str]]) -> None:
    """
    将 API 密钥保存到 config.yaml 文件

    Args:
        exchange: 交易所名称
        keys: 密钥字典，None 表示删除该交易所的密钥
    """
    import yaml as yaml_lib

    yaml_path = _config_path
    data: Dict[str, Any] = {}

    # 读取现有配置
    if os.path.exists(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml_lib.safe_load(f) or {}

    # 更新 api_keys 部分
    if "api_keys" not in data:
        data["api_keys"] = {}

    if keys is None:
        data["api_keys"].pop(exchange, None)
    else:
        data["api_keys"][exchange] = keys

    # 写回文件
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml_lib.dump(data, f, default_flow_style=False, allow_unicode=True)


@app.get("/api/risk/status")
async def get_risk_status() -> Dict[str, Any]:
    """获取风控管理器状态"""
    if not risk_manager:
        return {"error": "风控管理器未初始化"}
    return risk_manager.get_status()


@app.post("/api/risk/resume")
async def resume_risk() -> Dict[str, Any]:
    """恢复被风控暂停的交易"""
    if not risk_manager:
        return {"error": "风控管理器未初始化"}
    risk_manager.resume()
    return {"status": "ok", "message": "风控已恢复"}


# ----------------------------------------------------------------------------
# 每日报告 / 机会统计 / 热力图 / 币种管理 端点
# ----------------------------------------------------------------------------

@app.get("/api/daily-report")
async def get_daily_report(date: Optional[str] = None) -> Dict[str, Any]:
    """获取每日报告（汇总指定日期的机会检测与交易执行情况）"""
    if not database:
        return {"error": "数据库未初始化"}
    return database.get_daily_report(date)


@app.get("/api/opportunities/stats")
async def get_opportunity_stats() -> Dict[str, Any]:
    """获取当前套利机会的聚合统计（风险/交易对/交易所对/价差分布）"""
    opps = latest_opportunities
    if not opps:
        return {"total": 0, "by_risk": {}, "by_symbol": {},
                "by_exchange_pair": {}, "spread_distribution": {},
                "avg_net_profit_rate": 0.0, "max_net_profit_rate": 0.0}

    by_risk: Dict[str, int] = {}
    by_symbol: Dict[str, int] = {}
    by_pair: Dict[str, int] = {}
    spread_dist = {"<0.1%": 0, "0.1-0.5%": 0, "0.5-1%": 0, ">1%": 0}
    rates = []

    for op in opps:
        risk = op.risk_level.value if hasattr(op.risk_level, "value") else str(op.risk_level)
        by_risk[risk] = by_risk.get(risk, 0) + 1
        by_symbol[op.symbol] = by_symbol.get(op.symbol, 0) + 1
        pair_key = "%s→%s" % (op.buy_exchange, op.sell_exchange)
        by_pair[pair_key] = by_pair.get(pair_key, 0) + 1
        sp = op.spread_percent * 100
        if sp < 0.1:
            spread_dist["<0.1%"] += 1
        elif sp < 0.5:
            spread_dist["0.1-0.5%"] += 1
        elif sp < 1:
            spread_dist["0.5-1%"] += 1
        else:
            spread_dist[">1%"] += 1
        rates.append(op.net_profit_rate)

    avg_rate = sum(rates) / len(rates) if rates else 0.0
    max_rate = max(rates) if rates else 0.0
    return {"total": len(opps), "by_risk": by_risk, "by_symbol": by_symbol,
            "by_exchange_pair": by_pair, "spread_distribution": spread_dist,
            "avg_net_profit_rate": round(avg_rate, 6),
            "max_net_profit_rate": round(max_rate, 6)}


@app.get("/api/heatmap")
async def get_heatmap() -> Dict[str, Any]:
    """获取价差热力图数据（交易对 × 交易所对矩阵）"""
    if not latest_prices:
        return {"symbols": [], "exchange_pairs": [], "cells": []}

    exchanges = sorted(latest_prices.keys())
    exchange_pairs = ["%s→%s" % (b, s) for b in exchanges for s in exchanges if b != s]
    all_symbols = set()
    for ex_prices in latest_prices.values():
        all_symbols.update(ex_prices.keys())
    symbols = sorted(all_symbols)

    cells = []
    for symbol in symbols:
        ex_prices = {}
        for ex in exchanges:
            ticker = latest_prices.get(ex, {}).get(symbol)
            if ticker and ticker.get("ask", 0) > 0 and ticker.get("bid", 0) > 0:
                ex_prices[ex] = ticker
        if len(ex_prices) < 2:
            continue
        for buy_ex in ex_prices:
            for sell_ex in ex_prices:
                if buy_ex == sell_ex:
                    continue
                buy_ask = ex_prices[buy_ex]["ask"]
                sell_bid = ex_prices[sell_ex]["bid"]
                if buy_ask <= 0:
                    continue
                spread = (sell_bid - buy_ask) / buy_ask
                total_fee = config.get_exchange_fee(buy_ex) + config.get_exchange_fee(sell_ex)
                cells.append({"symbol": symbol, "buy_exchange": buy_ex,
                              "sell_exchange": sell_ex, "spread_percent": round(spread, 6),
                              "buy_price": buy_ask, "sell_price": sell_bid,
                              "net_profit_rate": round(spread - total_fee, 6)})
    return {"symbols": symbols, "exchange_pairs": exchange_pairs, "cells": cells}


@app.get("/api/symbols")
async def get_symbols() -> Dict[str, Any]:
    """获取当前监控的交易对列表及其分类信息"""
    symbols = config.model.symbols
    symbol_info = [{"symbol": s, "base": s.split("/")[0] if "/" in s else s,
                    "category": get_symbol_category(s)} for s in symbols]
    return {"symbols": symbols, "symbol_info": symbol_info,
            "categories": SYMBOL_CATEGORIES, "count": len(symbols)}


@app.put("/api/symbols")
async def update_symbols(data: Dict[str, Any]) -> Dict[str, Any]:
    """更新监控的交易对列表（覆盖或增量增删，修改后重建扫描器）"""
    old_symbols = config.model.symbols.copy()
    if "symbols" in data and isinstance(data["symbols"], list):
        config.model.symbols = [s.strip().upper() for s in data["symbols"] if s.strip()]
    else:
        current = set(config.model.symbols)
        for s in data.get("add", []):
            s = s.strip().upper()
            if s and s not in current:
                current.add(s)
        for s in data.get("remove", []):
            current.discard(s.strip().upper())
        config.model.symbols = sorted(current)

    if config.model.symbols != old_symbols and scanner:
        try:
            await scanner.close()
            scanner.exchanges = config.model.exchanges
            scanner.symbols = config.model.symbols
            scanner._init_exchanges()
            if hasattr(scanner, "start"):
                await scanner.start()
            logger.info("交易对列表已更新: %d → %d 个", len(old_symbols), len(config.model.symbols))
        except Exception as e:
            logger.error("重建扫描器失败: %s", e, exc_info=True)
    return {"status": "ok", "symbols": config.model.symbols, "count": len(config.model.symbols)}


@app.get("/api/symbols/categories")
async def get_symbol_categories() -> Dict[str, Any]:
    """获取币种分类映射表"""
    return {"categories": SYMBOL_CATEGORIES}


# ----------------------------------------------------------------------------
# 策略管理端点
# ----------------------------------------------------------------------------

@app.get("/api/strategies")
async def list_strategies() -> Dict[str, Any]:
    """获取所有已注册策略的状态"""
    if not strategy_orchestrator:
        return {"strategies": [], "orchestrator_running": False}
    return strategy_orchestrator.get_status()


@app.post("/api/strategies/create")
async def create_strategy(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    创建并注册策略实例

    接收 {type, name, config} 创建指定类型的策略。
    type: grid / dca / triangular
    """
    if not strategy_registry:
        return {"error": "策略注册中心未初始化"}

    strategy_type = data.get("type", "").strip().lower()
    name = data.get("name", "").strip()
    config = data.get("config", {})

    if not name:
        return JSONResponse(status_code=400, content={"error": "缺少策略名称"})
    if strategy_registry.get(name):
        return JSONResponse(status_code=409, content={"error": f"策略 {name} 已存在"})

    # 策略类型映射（按产品定位区分核心/实验性）
    strategy_map = {
        # 核心套利策略
        "triangular": (TriangularStrategy, False),
        # 实验性策略（非纯套利，仅供研究参考）
        "grid": (GridStrategy, True),
        "dca": (DcaStrategy, True),
    }
    if strategy_type not in strategy_map:
        return JSONResponse(status_code=400, content={
            "error": f"不支持的策略类型: {strategy_type}"
        })

    strategy_class, is_experimental = strategy_map[strategy_type]

    # 实验性策略需明确确认
    if is_experimental and not data.get("confirm_experimental", False):
        return JSONResponse(status_code=403, content={
            "error": "experimental",
            "detail": f"{strategy_type} 不属于纯套利策略（属于常规量化），需设置 confirm_experimental=true 明确启用",
        })

    try:
        strategy = strategy_class(name, config)
        strategy_registry.register(name, strategy)
        logger.info("已创建策略: %s (%s, experimental=%s)", name, strategy_type, is_experimental)
        return {
            "status": "ok",
            "name": name,
            "type": strategy_type,
            "experimental": is_experimental,
        }
    except Exception as e:
        logger.error("创建策略失败: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/strategies/{name}/start")
async def start_strategy(name: str) -> Dict[str, Any]:
    """启动指定策略"""
    if not strategy_registry:
        return {"error": "策略注册中心未初始化"}
    strategy = strategy_registry.get(name)
    if not strategy:
        return JSONResponse(status_code=404, content={"error": f"策略 {name} 不存在"})
    await strategy.start()
    return {"status": "ok", "name": name}


@app.post("/api/strategies/{name}/stop")
async def stop_strategy(name: str) -> Dict[str, Any]:
    """停止指定策略"""
    if not strategy_registry:
        return {"error": "策略注册中心未初始化"}
    strategy = strategy_registry.get(name)
    if not strategy:
        return JSONResponse(status_code=404, content={"error": f"策略 {name} 不存在"})
    await strategy.stop()
    return {"status": "ok", "name": name}


@app.delete("/api/strategies/{name}")
async def delete_strategy(name: str) -> Dict[str, Any]:
    """删除指定策略"""
    if not strategy_registry:
        return {"error": "策略注册中心未初始化"}
    strategy = strategy_registry.unregister(name)
    if not strategy:
        return JSONResponse(status_code=404, content={"error": f"策略 {name} 不存在"})
    await strategy.stop()
    return {"status": "ok", "name": name}


@app.post("/api/strategies/orchestrator/start")
async def start_orchestrator() -> Dict[str, Any]:
    """启动策略调度器"""
    if not strategy_orchestrator:
        return {"error": "策略调度器未初始化"}
    await strategy_orchestrator.start()
    return {"status": "ok"}


@app.post("/api/strategies/orchestrator/stop")
async def stop_orchestrator() -> Dict[str, Any]:
    """停止策略调度器"""
    if not strategy_orchestrator:
        return {"error": "策略调度器未初始化"}
    await strategy_orchestrator.stop()
    return {"status": "ok"}


# ----------------------------------------------------------------------------
# 回测引擎端点
# ----------------------------------------------------------------------------

@app.get("/api/backtest/klines")
async def get_klines(
    exchange: str, symbol: str, timeframe: str = "1h", limit: int = 500
) -> Dict[str, Any]:
    """查询已存储的 K 线数据"""
    if not history_collector:
        return {"error": "回测引擎未初始化"}
    klines = history_collector.get_klines(exchange, symbol, timeframe, limit)
    count = history_collector.get_kline_count(exchange, symbol, timeframe)
    return {"klines": klines, "count": len(klines), "total_stored": count}


@app.post("/api/backtest/download")
async def download_klines(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    下载历史 K 线数据

    接收 {exchange, symbol, timeframe, days} 下载指定天数的历史数据。
    """
    if not history_collector:
        return {"error": "回测引擎未初始化"}
    exchange = data.get("exchange", "binance")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "1h")
    days = int(data.get("days", 30))
    count = await history_collector.download_klines(exchange, symbol, timeframe, days)
    return {"status": "ok", "downloaded": count}


@app.post("/api/backtest/run")
async def run_backtest(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行回测

    接收 {strategy_type, config, exchange, symbol, timeframe, initial_capital}
    创建临时策略实例并回测。
    """
    if not backtest_engine or not history_collector:
        return {"error": "回测引擎未初始化"}

    strategy_type = data.get("strategy_type", "grid")
    config = data.get("config", {})
    exchange = data.get("exchange", "binance")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "1h")
    initial_capital = float(data.get("initial_capital", 10000))

    # 检查是否有足够的 K 线数据
    kline_count = history_collector.get_kline_count(exchange, symbol, timeframe)
    if kline_count < 10:
        return JSONResponse(status_code=400, content={
            "error": f"K线数据不足（{kline_count}条），请先下载历史数据"
        })

    # 策略类型映射（按产品定位区分核心/实验性）
    strategy_map = {
        "triangular": (TriangularStrategy, False),
        "grid": (GridStrategy, True),
        "dca": (DcaStrategy, True),
    }
    if strategy_type not in strategy_map:
        return JSONResponse(status_code=400, content={
            "error": f"不支持的策略类型: {strategy_type}"
        })

    try:
        strategy = strategy_class(f"backtest_{strategy_type}", config)
        result = await backtest_engine.run(
            strategy=strategy,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=initial_capital,
        )
        return result.to_dict()
    except Exception as e:
        logger.error("回测执行失败: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ----------------------------------------------------------------------------
# 用户认证端点
# ----------------------------------------------------------------------------

@app.post("/api/auth/register")
async def register(data: Dict[str, Any]) -> Dict[str, Any]:
    """用户注册（邮箱 + 密码）"""
    if not user_auth:
        return {"error": "用户认证未初始化"}
    email = data.get("email", "")
    password = data.get("password", "")
    return user_auth.register(email, password)


@app.post("/api/auth/login")
async def login(data: Dict[str, Any]) -> Dict[str, Any]:
    """用户登录（返回 JWT Token）"""
    if not user_auth:
        return {"error": "用户认证未初始化"}
    email = data.get("email", "")
    password = data.get("password", "")
    return user_auth.login(email, password)


@app.post("/api/auth/refresh")
async def refresh_token(data: Dict[str, Any]) -> Dict[str, Any]:
    """刷新 Token"""
    if not user_auth:
        return {"error": "用户认证未初始化"}
    refresh = data.get("refresh_token", "")
    return user_auth.refresh_token(refresh)


@app.get("/api/auth/me")
async def get_current_user(request: Request) -> Dict[str, Any]:
    """获取当前登录用户信息"""
    if not user_auth:
        return {"error": "用户认证未初始化"}
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return JSONResponse(status_code=401, content={"error": "未登录"})
    token = auth[7:].strip()
    payload = user_auth.verify_token(token)
    if not payload:
        return JSONResponse(status_code=401, content={"error": "Token 无效或已过期"})
    return {
        "user_id": payload.get("user_id"),
        "email": payload.get("email"),
        "role": payload.get("role"),
    }


# ----------------------------------------------------------------------------
# AI 策略推荐端点
# ----------------------------------------------------------------------------

@app.get("/api/ai/recommend")
async def ai_recommend(
    capital: float = 10000, risk_tolerance: str = "medium"
) -> Dict[str, Any]:
    """
    AI 策略推荐

    基于当前市场数据分析，推荐最优策略组合。
    GET 参数：capital（资金量）、risk_tolerance（风险偏好 low/medium/high）
    """
    if not ai_advisor:
        return {"error": "AI 推荐器未初始化"}
    if not latest_prices:
        return {"error": "暂无价格数据，请等待扫描器启动"}
    return ai_advisor.analyze(latest_prices, capital, risk_tolerance)


# ----------------------------------------------------------------------------
# WebSocket 端点
# ----------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 实时推送端点，向客户端推送价格、机会和交易更新"""
    await manager.connect(websocket)

    try:
        # 连接后立即发送当前状态
        await websocket.send_text(json.dumps({
            "type": "status",
            "data": await get_status(),
            "timestamp": int(time.time() * 1000),
        }, ensure_ascii=False, default=str))

        # 发送当前价格
        if latest_prices:
            await websocket.send_text(json.dumps({
                "type": "prices",
                "data": latest_prices,
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False, default=str))

        # 发送当前机会
        if latest_opportunities:
            await websocket.send_text(json.dumps({
                "type": "opportunities",
                "data": [op.model_dump() for op in latest_opportunities],
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False, default=str))

        # 持续监听客户端消息（心跳保活）
        while True:
            data = await websocket.receive_text()
            # 处理客户端心跳
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket 异常: %s", e, exc_info=True)
        manager.disconnect(websocket)


# ----------------------------------------------------------------------------
# Portfolio / Event store / Test-order 端点
# ----------------------------------------------------------------------------

@app.get("/api/portfolio")
async def get_portfolio():
    """查询当前投资组合状态"""
    if runtime_state is None:
        return {"error": "runtime_state not initialized"}
    return runtime_state.portfolio_dict()


@app.post("/api/portfolio/reset")
async def reset_portfolio():
    """重置 Portfolio 到初始状态"""
    # 鉴权：当前 app 未提供 require_write_token 工厂，仅记录 WARNING 日志
    if runtime_state is None:
        logger.warning("reset_portfolio called before runtime_state initialized")
    if runtime_state is not None:
        runtime_state.reset()
        if event_store is not None:
            event_store.append("portfolio_reset", {})
    return {
        "status": "reset",
        "portfolio": runtime_state.portfolio_dict() if runtime_state else {},
    }


@app.get("/api/events")
async def get_events(limit: int = 100):
    """查询 JSONL 事件日志"""
    if event_store is None:
        return []
    return event_store.tail(limit)


@app.post("/api/test-order")
async def create_test_order(payload: dict = Body(...)):
    """创建隔离测试限价单，验证交易所连通性，不影响策略状态"""
    # 鉴权：当前 app 未提供 require_write_token 工厂，仅记录 WARNING 日志
    logger.warning("test-order requested without write token check: %s", payload)
    exchange = payload.get("exchange", "binance")
    symbol = payload.get("symbol", "BTC/USDT")
    side = payload.get("side", "buy")
    amount = payload.get("amount", 0.001)
    if event_store:
        event_store.append("test_order_requested", payload)
    # 占位：实盘下单逻辑后续接入
    return {
        "status": "simulated",
        "exchange": exchange,
        "symbol": symbol,
        "side": side,
        "amount": amount,
    }


@app.post("/api/test-order/cancel")
async def cancel_test_order():
    """取消测试单（占位）"""
    # 鉴权：当前 app 未提供 require_write_token 工厂，仅记录 WARNING 日志
    logger.warning("test-order cancel requested without write token check")
    if event_store:
        event_store.append("test_order_cancelled", {})
    return {"status": "cancelled"}


# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8070,
        reload=False,
    )
