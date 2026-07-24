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
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .arbitrage import ArbitrageDetector
from .config import Config, SUPPORTED_EXCHANGES
from .executor import TradeExecutor
from .models import ArbitrageOpportunity, OrderStatus, TradeResult
from .scanner import PriceScanner

# ----------------------------------------------------------------------------
# 日志配置
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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


# ----------------------------------------------------------------------------
# 后台任务
# ----------------------------------------------------------------------------
async def scanner_loop() -> None:
    """
    价格扫描循环

    每隔 scan_interval 秒执行一次全量价格扫描，
    扫描完成后自动触发套利检测。
    """
    global latest_prices, latest_opportunities

    logger.info("价格扫描循环已启动，间隔 %d 秒", config.model.scan_interval)

    while scanner_running:
        try:
            if scanner:
                # 执行全量扫描
                prices = await scanner.scan_all()
                if prices:
                    latest_prices = prices
                    logger.debug("价格扫描完成，获取 %d 个交易所数据", len(prices))

                    # 扫描完成后自动检测套利机会
                    if detector:
                        opportunities = detector.detect(prices)
                        latest_opportunities = opportunities

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
                # 执行利润最高的机会
                best_op = latest_opportunities[0]
                logger.info(
                    "自动执行套利: %s 净利润率=%.4f%%",
                    best_op.symbol, best_op.net_profit_rate * 100,
                )
                result = await executor.execute(best_op)

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
    global scanner, detector, executor

    logger.info("OpenAlpha 套利系统启动中...")

    # 初始化核心组件
    scanner = PriceScanner(
        config.model.exchanges, config.model.symbols, config
    )
    detector = ArbitrageDetector(config)
    executor = TradeExecutor(config, config.api_keys)

    logger.info("系统初始化完成，服务端口 8070")

    yield

    # 清理资源
    global scanner_running, arbitrage_running
    scanner_running = False
    arbitrage_running = False

    if scanner:
        await scanner.close()
    if executor:
        await executor.close()

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
    """手动执行单个套利机会"""
    if not executor:
        return JSONResponse(
            status_code=500,
            content={"error": "执行器未初始化"},
        )

    try:
        # 从请求数据构建套利机会对象
        opportunity = ArbitrageOpportunity(**opportunity_data)
        result = await executor.execute(opportunity)

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
