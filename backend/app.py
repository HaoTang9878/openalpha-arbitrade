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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.auth import add_auth_middleware  # 鉴权中间件

from .arbitrage import ArbitrageDetector
from .config import Config, SUPPORTED_EXCHANGES
from .database import Database
from .executor import TradeExecutor
from .models import ArbitrageOpportunity, OrderStatus, TradeResult
from .risk_manager import RiskManager
from .scanner import PriceScanner, WebSocketScanner

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

# 运行状态标志
scanner_running = False
arbitrage_running = False

# 最新数据缓存
latest_prices: Dict[str, Dict[str, Dict[str, Any]]] = {}
latest_opportunities: List[ArbitrageOpportunity] = []

# 后台任务引用
scanner_task: Optional[asyncio.Task] = None
arbitrage_task: Optional[asyncio.Task] = None

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

        except Exception as e:
            logger.error("价格扫描循环异常: %s", e, exc_info=True)

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

        except Exception as e:
            logger.error("自动套利循环异常: %s", e, exc_info=True)

        # 等待下一轮检查（使用较短的间隔以快速响应机会）
        await asyncio.sleep(config.model.scan_interval)

    logger.info("自动套利循环已停止")


# ----------------------------------------------------------------------------
# 生命周期管理
# ----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，负责初始化和清理资源"""
    global scanner, detector, executor, risk_manager, database
    global scanner_running, scanner_task

    logger.info("OpenAlpha 套利系统启动中...")

    # 初始化 SQLite 持久化层（交易历史 + 套利机会记录）
    db_path = str(Path(__file__).parent.parent / "data" / "arbitrage.db")
    database = Database(db_path)

    # 初始化套利检测器、交易执行器和风控管理器
    detector = ArbitrageDetector(config)
    executor = TradeExecutor(config, config.api_keys, database=database)
    risk_manager = RiskManager(config)

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
app = FastAPI(
    title="OpenAlpha 套利交易系统",
    description="加密货币跨交易所套利交易系统 API",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- 鉴权中间件(写/执行操作需 Bearer token)----
add_auth_middleware(app)

# 挂载静态文件目录（前端）
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


# ----------------------------------------------------------------------------
# 页面路由
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """返回前端监控仪表盘页面"""
    index_file = frontend_path / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)


# ----------------------------------------------------------------------------
# REST API 端点
# ----------------------------------------------------------------------------
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
