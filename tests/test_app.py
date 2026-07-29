"""
API 服务端点单元测试

覆盖 backend/app.py 的核心端点与组件：
- GET /api/status — 系统状态
- GET /api/config — 配置查询
- PUT /api/config — 配置更新
- POST /api/scanner/start|stop — 扫描器控制
- GET /api/prices — 价格快照
- GET /api/opportunities — 套利机会
- POST /api/arbitrage/start|stop — 套利控制
- GET /api/trades — 交易历史
- POST /api/trades/execute — 手动执行交易
- GET /api/exchanges — 交易所状态
- GET /api/balances — 余额查询
- POST /api/keys / DELETE /api/keys/{exchange} — API 密钥管理
- GET /api/risk/status — 风控状态
- POST /api/risk/resume — 恢复风控
- ConnectionManager — WebSocket 连接管理
- WebSocketLogHandler — 日志广播
- scanner_loop / arbitrage_loop — 后台循环
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from backend.models import (
    ArbitrageOpportunity,
    OrderStatus,
    RiskLevel,
    TradeResult,
)


# ----------------------------------------------------------------------------
# 测试 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture
def app_client(monkeypatch, tmp_path):
    """创建测试客户端，mock 掉网络依赖（scanner/executor 的 CCXT 实例）"""
    # 隔离环境变量，避免读取真实 token
    monkeypatch.delenv("ARBITRAGE_API_TOKEN", raising=False)

    # 使用临时数据库路径，避免污染真实数据
    import backend.app as app_module

    # 保存原始全局状态
    original_state = {
        "scanner": app_module.scanner,
        "detector": app_module.detector,
        "executor": app_module.executor,
        "risk_manager": app_module.risk_manager,
        "database": app_module.database,
        "notifier": app_module.notifier,
        "scanner_running": app_module.scanner_running,
        "arbitrage_running": app_module.arbitrage_running,
        "latest_prices": app_module.latest_prices,
        "latest_opportunities": app_module.latest_opportunities,
        "config": app_module.config,
    }

    # 重置全局状态为可控的 mock 对象
    app_module.scanner = None
    app_module.detector = None
    app_module.executor = MagicMock()
    app_module.executor.trade_history = []
    app_module.executor.get_trade_history = MagicMock(return_value=[])
    app_module.risk_manager = MagicMock()
    app_module.risk_manager.get_status = MagicMock(return_value={
        "halted": False, "halt_reason": "", "open_positions": 0,
        "max_open_positions": 3, "daily_pnl": 0.0, "max_daily_loss": 50.0,
        "daily_trade_count": 0, "max_daily_trades": 100,
        "exchange_exposure": {}, "max_exposure_per_exchange": 500.0,
    })
    app_module.risk_manager.check = MagicMock(return_value=True)
    app_module.risk_manager.record_trade_start = MagicMock()
    app_module.risk_manager.record_trade_end = MagicMock()
    app_module.risk_manager.resume = MagicMock()
    app_module.database = None
    app_module.notifier = None
    app_module.scanner_running = False
    app_module.arbitrage_running = False
    app_module.latest_prices = {}
    app_module.latest_opportunities = []

    # 使用临时 config（避免读 config.yaml）
    from backend.config import Config
    app_module.config = Config()
    app_module.config.model.exchanges = ["binance", "okx"]
    app_module.config.model.symbols = ["BTC/USDT"]

    client = TestClient(app_module.app)
    yield client, app_module

    # 恢复原始全局状态
    for key, value in original_state.items():
        setattr(app_module, key, value)


# ----------------------------------------------------------------------------
# 只读端点测试
# ----------------------------------------------------------------------------
class TestReadOnlyEndpoints:
    """只读 GET 端点测试"""

    def test_get_status(self, app_client):
        """GET /api/status 返回系统状态"""
        client, _ = app_client
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "scanner_running" in data
        assert "arbitrage_running" in data
        assert "exchanges_count" in data
        assert "symbols_count" in data
        assert "uptime_seconds" in data
        assert "paper_trade" in data
        assert "risk_status" in data
        assert "timestamp" in data

    def test_get_config(self, app_client):
        """GET /api/config 返回当前配置"""
        client, _ = app_client
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "exchanges" in data
        assert "symbols" in data
        assert "min_profitability" in data

    def test_get_prices(self, app_client):
        """GET /api/prices 返回价格快照"""
        client, app_module = app_client
        app_module.latest_prices = {
            "binance": {"BTC/USDT": {"bid": 95000.0, "ask": 95001.0}},
        }
        resp = client.get("/api/prices")
        assert resp.status_code == 200
        data = resp.json()
        assert "prices" in data
        assert "timestamp" in data
        assert "binance" in data["prices"]

    def test_get_prices_empty(self, app_client):
        """无价格数据时返回空字典"""
        client, _ = app_client
        resp = client.get("/api/prices")
        assert resp.status_code == 200
        assert resp.json()["prices"] == {}

    def test_get_opportunities(self, app_client):
        """GET /api/opportunities 返回套利机会列表"""
        client, app_module = app_client
        app_module.latest_opportunities = [
            ArbitrageOpportunity(
                symbol="BTC/USDT", buy_exchange="binance", sell_exchange="okx",
                buy_price=95000.0, sell_price=95100.0,
                spread_percent=0.00105, net_profit_rate=0.00085,
                estimated_profit=0.8, risk_level=RiskLevel.LOW,
                timestamp=1700000000000,
            ),
        ]
        resp = client.get("/api/opportunities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["opportunities"]) == 1

    def test_get_opportunities_empty(self, app_client):
        """无套利机会时返回空列表"""
        client, _ = app_client
        resp = client.get("/api/opportunities")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_get_trades(self, app_client):
        """GET /api/trades 返回交易历史"""
        client, app_module = app_client
        app_module.executor.get_trade_history = MagicMock(return_value=[
            TradeResult(
                id="t1", symbol="BTC/USDT", buy_exchange="binance",
                sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
                amount=0.01, status=OrderStatus.FILLED, profit=0.5,
                paper_trade=True, timestamp="2026-07-28 01:00:00",
            ),
        ])
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["trades"]) == 1

    def test_get_trades_empty(self, app_client):
        """无交易历史时返回空列表"""
        client, _ = app_client
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_get_exchanges_without_scanner(self, app_client):
        """无 scanner 时 GET /api/exchanges 返回默认状态"""
        client, _ = app_client
        resp = client.get("/api/exchanges")
        assert resp.status_code == 200
        data = resp.json()
        assert "exchanges" in data
        assert "supported" in data
        assert len(data["exchanges"]) > 0

    def test_get_exchanges_with_scanner(self, app_client):
        """有 scanner 时 GET /api/exchanges 返回扫描器状态"""
        client, app_module = app_client
        mock_scanner = MagicMock()
        mock_scanner.get_exchange_status = MagicMock(return_value={
            "binance": {"name": "binance", "enabled": True, "connected": True,
                        "error_count": 0, "latency_ms": 10.0},
        })
        app_module.scanner = mock_scanner
        resp = client.get("/api/exchanges")
        assert resp.status_code == 200
        data = resp.json()
        assert any(e["name"] == "binance" for e in data["exchanges"])

    def test_get_balances_no_api_keys(self, app_client):
        """无 API Key 时 GET /api/balances 返回提示"""
        client, _ = app_client
        resp = client.get("/api/balances")
        assert resp.status_code == 200
        data = resp.json()
        assert "balances" in data
        assert "message" in data

    def test_get_risk_status(self, app_client):
        """GET /api/risk/status 返回风控状态"""
        client, _ = app_client
        resp = client.get("/api/risk/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "halted" in data
        assert "open_positions" in data

    def test_get_risk_status_no_manager(self, app_client):
        """无风控管理器时返回错误"""
        client, app_module = app_client
        app_module.risk_manager = None
        resp = client.get("/api/risk/status")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ----------------------------------------------------------------------------
# 写/执行端点测试（需要鉴权）
# ----------------------------------------------------------------------------
class TestWriteEndpoints:
    """写/执行端点测试"""

    def test_update_config(self, app_client, monkeypatch):
        """PUT /api/config 更新配置"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.put(
            "/api/config",
            json={"min_profitability": 0.005},
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_start_scanner(self, app_client, monkeypatch):
        """POST /api/scanner/start 启动扫描"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        # mock scanner_loop 避免真实启动
        with patch.object(app_module, "scanner_loop", new=AsyncMock()):
            resp = client.post(
                "/api/scanner/start",
                headers={"Authorization": "Bearer test_token"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_start_scanner_already_running(self, app_client, monkeypatch):
        """扫描器已运行时返回 already_running"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.scanner_running = True
        resp = client.post(
            "/api/scanner/start",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_running"

    def test_stop_scanner(self, app_client, monkeypatch):
        """POST /api/scanner/stop 停止扫描"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.scanner_running = True
        app_module.scanner_task = MagicMock()
        resp = client.post(
            "/api/scanner/stop",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_stop_scanner_already_stopped(self, app_client, monkeypatch):
        """扫描器已停止时返回 already_stopped"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.post(
            "/api/scanner/stop",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_stopped"

    def test_start_arbitrage(self, app_client, monkeypatch):
        """POST /api/arbitrage/start 启动套利"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        with patch.object(app_module, "arbitrage_loop", new=AsyncMock()):
            resp = client.post(
                "/api/arbitrage/start",
                headers={"Authorization": "Bearer test_token"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_start_arbitrage_already_running(self, app_client, monkeypatch):
        """套利已运行时返回 already_running"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.arbitrage_running = True
        resp = client.post(
            "/api/arbitrage/start",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.json()["status"] == "already_running"

    def test_stop_arbitrage(self, app_client, monkeypatch):
        """POST /api/arbitrage/stop 停止套利"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.arbitrage_running = True
        app_module.arbitrage_task = MagicMock()
        resp = client.post(
            "/api/arbitrage/stop",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.json()["status"] == "stopped"

    def test_stop_arbitrage_already_stopped(self, app_client, monkeypatch):
        """套利已停止时返回 already_stopped"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.post(
            "/api/arbitrage/stop",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.json()["status"] == "already_stopped"

    def test_resume_risk(self, app_client, monkeypatch):
        """POST /api/risk/resume 恢复风控"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.post(
            "/api/risk/resume",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_resume_risk_no_manager(self, app_client, monkeypatch):
        """无风控管理器时返回错误"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.risk_manager = None
        resp = client.post(
            "/api/risk/resume",
            headers={"Authorization": "Bearer test_token"},
        )
        assert "error" in resp.json()


# ----------------------------------------------------------------------------
# 手动执行交易测试
# ----------------------------------------------------------------------------
class TestExecuteTrade:
    """POST /api/trades/execute 手动执行交易测试"""

    def test_execute_trade_success(self, app_client, monkeypatch):
        """成功执行交易"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client

        mock_result = TradeResult(
            id="exec_1", symbol="BTC/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
            amount=0.01, status=OrderStatus.FILLED, profit=0.5,
            paper_trade=True, timestamp="2026-07-28 01:00:00",
        )
        app_module.executor.execute = AsyncMock(return_value=mock_result)

        opportunity_data = {
            "symbol": "BTC/USDT", "buy_exchange": "binance",
            "sell_exchange": "okx", "buy_price": 95000.0,
            "sell_price": 95100.0, "spread_percent": 0.00105,
            "net_profit_rate": 0.00085, "estimated_profit": 0.8,
            "risk_level": "low", "timestamp": 1700000000000,
        }
        resp = client.post(
            "/api/trades/execute",
            json=opportunity_data,
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_execute_trade_risk_rejected(self, app_client, monkeypatch):
        """风控拒绝时返回 403"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.risk_manager.check = MagicMock(return_value=False)

        opportunity_data = {
            "symbol": "BTC/USDT", "buy_exchange": "binance",
            "sell_exchange": "okx", "buy_price": 95000.0,
            "sell_price": 95100.0, "spread_percent": 0.00105,
            "net_profit_rate": 0.00085, "estimated_profit": 0.8,
            "risk_level": "low", "timestamp": 1700000000000,
        }
        resp = client.post(
            "/api/trades/execute",
            json=opportunity_data,
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 403

    def test_execute_trade_invalid_data(self, app_client, monkeypatch):
        """无效数据时返回 500"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.post(
            "/api/trades/execute",
            json={"invalid": "data"},
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 500


# ----------------------------------------------------------------------------
# API 密钥管理测试
# ----------------------------------------------------------------------------
class TestApiKeysManagement:
    """API 密钥管理端点测试"""

    def test_save_api_key_missing_params(self, app_client, monkeypatch):
        """缺少参数时返回 400"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.post(
            "/api/keys",
            json={"exchange": "binance"},  # 缺 apiKey 和 secret
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 400

    def test_save_api_key_unsupported_exchange(self, app_client, monkeypatch):
        """不支持的交易所返回 400"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.post(
            "/api/keys",
            json={"exchange": "fake_ex", "apiKey": "key", "secret": "secret"},
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 400

    def test_save_api_key_success(self, app_client, monkeypatch, tmp_path):
        """成功保存 API 密钥"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        # mock _save_keys_to_yaml 避免写真实文件
        with patch.object(app_module, "_save_keys_to_yaml"):
            resp = client.post(
                "/api/keys",
                json={"exchange": "binance", "apiKey": "key123", "secret": "sec456"},
                headers={"Authorization": "Bearer test_token"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert app_module.config.api_keys["binance"]["apiKey"] == "key123"

    def test_delete_api_key_not_found(self, app_client, monkeypatch):
        """删除不存在的密钥返回 404"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, _ = app_client
        resp = client.delete(
            "/api/keys/binance",
            headers={"Authorization": "Bearer test_token"},
        )
        assert resp.status_code == 404

    def test_delete_api_key_success(self, app_client, monkeypatch):
        """成功删除 API 密钥"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "test_token")
        client, app_module = app_client
        app_module.config.api_keys["binance"] = {"apiKey": "k", "secret": "s"}
        with patch.object(app_module, "_save_keys_to_yaml"):
            resp = client.delete(
                "/api/keys/binance",
                headers={"Authorization": "Bearer test_token"},
            )
        assert resp.status_code == 200
        assert "binance" not in app_module.config.api_keys


# ----------------------------------------------------------------------------
# _save_keys_to_yaml 测试
# ----------------------------------------------------------------------------
class TestSaveKeysToYaml:
    """_save_keys_to_yaml() 持久化测试"""

    def test_save_keys_creates_file(self, app_client, tmp_path):
        """保存密钥创建 YAML 文件"""
        _, app_module = app_client
        yaml_path = str(tmp_path / "test_keys.yaml")
        app_module._config_path = yaml_path

        app_module._save_keys_to_yaml("binance", {"apiKey": "k", "secret": "s"})

        import yaml
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        assert data["api_keys"]["binance"]["apiKey"] == "k"

    def test_save_keys_updates_existing_file(self, app_client, tmp_path):
        """保存密钥更新已有 YAML 文件"""
        _, app_module = app_client
        yaml_path = str(tmp_path / "test_keys.yaml")
        app_module._config_path = yaml_path

        # 先写一个
        app_module._save_keys_to_yaml("binance", {"apiKey": "k1", "secret": "s1"})
        # 再写另一个
        app_module._save_keys_to_yaml("okx", {"apiKey": "k2", "secret": "s2"})

        import yaml
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        assert "binance" in data["api_keys"]
        assert "okx" in data["api_keys"]

    def test_delete_keys_from_yaml(self, app_client, tmp_path):
        """删除密钥从 YAML 文件移除"""
        _, app_module = app_client
        yaml_path = str(tmp_path / "test_keys.yaml")
        app_module._config_path = yaml_path

        app_module._save_keys_to_yaml("binance", {"apiKey": "k", "secret": "s"})
        app_module._save_keys_to_yaml("binance", None)  # 删除

        import yaml
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        assert "binance" not in data["api_keys"]


# ----------------------------------------------------------------------------
# ConnectionManager 测试
# ----------------------------------------------------------------------------
class TestConnectionManager:
    """ConnectionManager WebSocket 连接管理测试"""

    @pytest.mark.asyncio
    async def test_connect_adds_to_pool(self):
        """connect 将连接加入连接池"""
        from backend.app import ConnectionManager, ws_connections
        manager = ConnectionManager()
        ws_connections.clear()

        mock_ws = AsyncMock()
        await manager.connect(mock_ws)
        assert mock_ws in ws_connections
        ws_connections.clear()

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_pool(self):
        """disconnect 从连接池移除连接"""
        from backend.app import ConnectionManager, ws_connections
        manager = ConnectionManager()
        ws_connections.clear()

        mock_ws = MagicMock()
        ws_connections.add(mock_ws)
        manager.disconnect(mock_ws)
        assert mock_ws not in ws_connections

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        """无连接时广播直接返回"""
        from backend.app import ConnectionManager, ws_connections
        manager = ConnectionManager()
        ws_connections.clear()
        # 不应抛异常
        await manager.broadcast({"type": "test"})
        ws_connections.clear()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        """广播向所有连接发送消息"""
        from backend.app import ConnectionManager, ws_connections
        manager = ConnectionManager()
        ws_connections.clear()

        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws_connections.add(ws1)
        ws_connections.add(ws2)

        await manager.broadcast({"type": "test"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()
        ws_connections.clear()

    @pytest.mark.asyncio
    async def test_broadcast_removes_failed_connections(self):
        """广播时移除发送失败的连接"""
        from backend.app import ConnectionManager, ws_connections
        manager = ConnectionManager()
        ws_connections.clear()

        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = RuntimeError("disconnected")
        ws_connections.add(ws_good)
        ws_connections.add(ws_bad)

        await manager.broadcast({"type": "test"})
        assert ws_bad not in ws_connections
        assert ws_good in ws_connections
        ws_connections.clear()


# ----------------------------------------------------------------------------
# WebSocketLogHandler 测试
# ----------------------------------------------------------------------------
class TestWebSocketLogHandler:
    """WebSocketLogHandler 日志广播测试"""

    def test_emit_pushes_to_queue(self):
        """emit 将日志记录推入队列"""
        from backend.app import WebSocketLogHandler, log_queue
        import logging

        # 清空队列
        while not log_queue.empty():
            log_queue.get_nowait()

        handler = WebSocketLogHandler()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname=__file__,
            lineno=1, msg="test warning", args=None, exc_info=None,
        )
        handler.emit(record)

        assert not log_queue.empty()
        log_data = log_queue.get_nowait()
        assert log_data["level"] == "WARNING"
        assert log_data["message"] == "test warning"


# ----------------------------------------------------------------------------
# 后台循环测试
# ----------------------------------------------------------------------------
class TestBackgroundLoops:
    """scanner_loop / arbitrage_loop 后台循环测试"""

    @pytest.mark.asyncio
    async def test_scanner_loop_ws_mode(self, app_client):
        """WebSocket 模式扫描循环读取缓存"""
        _, app_module = app_client
        app_module.scanner_running = True

        mock_scanner = MagicMock()
        mock_scanner.get_prices = MagicMock(return_value={
            "binance": {"BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "volume": 1000.0, "timestamp": 0}},
        })
        mock_scanner.get_orderbooks = MagicMock(return_value={})
        app_module.scanner = mock_scanner

        mock_detector = MagicMock()
        mock_detector.detect = MagicMock(return_value=[])
        app_module.detector = mock_detector

        # mock sleep 让循环只跑一次
        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.scanner_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await app_module.scanner_loop()

        assert app_module.latest_prices != {}

    @pytest.mark.asyncio
    async def test_scanner_loop_rest_mode(self, app_client):
        """REST 模式扫描循环发起网络请求"""
        _, app_module = app_client
        app_module.scanner_running = True

        mock_scanner = AsyncMock()
        mock_scanner.scan_all = AsyncMock(return_value={
            "binance": {"BTC/USDT": {"bid": 95000.0, "ask": 95001.0, "last": 95000.5, "volume": 1000.0, "timestamp": 0}},
        })
        # REST 模式 scanner 无 get_prices 方法
        del mock_scanner.get_prices
        app_module.scanner = mock_scanner

        mock_detector = MagicMock()
        mock_detector.detect = MagicMock(return_value=[])
        app_module.detector = mock_detector

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.scanner_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await app_module.scanner_loop()

        mock_scanner.scan_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_scanner_loop_handles_exception(self, app_client):
        """扫描循环异常不崩溃"""
        _, app_module = app_client
        app_module.scanner_running = True

        mock_scanner = MagicMock()
        mock_scanner.get_prices = MagicMock(side_effect=RuntimeError("scan error"))
        app_module.scanner = mock_scanner

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.scanner_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            # 不应抛异常
            await app_module.scanner_loop()

    @pytest.mark.asyncio
    async def test_arbitrage_loop_no_opportunities(self, app_client):
        """无套利机会时套利循环空转"""
        _, app_module = app_client
        app_module.arbitrage_running = True
        app_module.latest_opportunities = []

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.arbitrage_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await app_module.arbitrage_loop()

    @pytest.mark.asyncio
    async def test_arbitrage_loop_executes_opportunity(self, app_client):
        """有套利机会时套利循环执行交易"""
        _, app_module = app_client
        app_module.arbitrage_running = True
        app_module.latest_opportunities = [
            ArbitrageOpportunity(
                symbol="BTC/USDT", buy_exchange="binance", sell_exchange="okx",
                buy_price=95000.0, sell_price=95100.0,
                spread_percent=0.00105, net_profit_rate=0.00085,
                estimated_profit=0.8, risk_level=RiskLevel.LOW,
                timestamp=1700000000000,
            ),
        ]

        mock_result = TradeResult(
            id="auto_1", symbol="BTC/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
            amount=0.01, status=OrderStatus.FILLED, profit=0.5,
            paper_trade=True, timestamp="2026-07-28 01:00:00",
        )
        app_module.executor.execute = AsyncMock(return_value=mock_result)

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.arbitrage_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await app_module.arbitrage_loop()

        app_module.executor.execute.assert_called_once()
        app_module.risk_manager.record_trade_start.assert_called_once()
        app_module.risk_manager.record_trade_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_arbitrage_loop_risk_rejected(self, app_client):
        """风控拒绝时套利循环跳过执行"""
        _, app_module = app_client
        app_module.arbitrage_running = True
        app_module.latest_opportunities = [
            ArbitrageOpportunity(
                symbol="BTC/USDT", buy_exchange="binance", sell_exchange="okx",
                buy_price=95000.0, sell_price=95100.0,
                spread_percent=0.00105, net_profit_rate=0.00085,
                estimated_profit=0.8, risk_level=RiskLevel.LOW,
                timestamp=1700000000000,
            ),
        ]
        app_module.risk_manager.check = MagicMock(return_value=False)
        app_module.executor.execute = AsyncMock()

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.arbitrage_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await app_module.arbitrage_loop()

        app_module.executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_arbitrage_loop_handles_exception(self, app_client):
        """套利循环异常不崩溃"""
        _, app_module = app_client
        app_module.arbitrage_running = True
        app_module.latest_opportunities = [
            ArbitrageOpportunity(
                symbol="BTC/USDT", buy_exchange="binance", sell_exchange="okx",
                buy_price=95000.0, sell_price=95100.0,
                spread_percent=0.00105, net_profit_rate=0.00085,
                estimated_profit=0.8, risk_level=RiskLevel.LOW,
                timestamp=1700000000000,
            ),
        ]
        app_module.executor.execute = AsyncMock(side_effect=RuntimeError("exec fail"))

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                app_module.arbitrage_running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            # 不应抛异常
            await app_module.arbitrage_loop()


# ----------------------------------------------------------------------------
# log_broadcast_loop 测试
# ----------------------------------------------------------------------------
class TestLogBroadcastLoop:
    """log_broadcast_loop 日志广播循环测试"""

    @pytest.mark.asyncio
    async def test_log_broadcast_loop_processes_queue(self, app_client):
        """日志广播循环处理队列中的日志"""
        _, app_module = app_client
        from backend.app import log_queue, ws_connections
        ws_connections.clear()

        # 放入一条日志
        await log_queue.put({"level": "WARNING", "message": "test", "timestamp": 0})

        cancelled = [False]
        async def fake_get():
            if cancelled[0]:
                raise asyncio.CancelledError()
            cancelled[0] = True
            return {"level": "WARNING", "message": "test", "timestamp": 0}

        with patch.object(log_queue, "get", side_effect=fake_get):
            with pytest.raises(asyncio.CancelledError):
                await app_module.log_broadcast_loop()

    @pytest.mark.asyncio
    async def test_log_broadcast_loop_handles_exception(self, app_client):
        """日志广播循环异常不崩溃"""
        _, app_module = app_client
        from backend.app import log_queue

        async def fake_get():
            raise RuntimeError("queue error")

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                raise asyncio.CancelledError()

        with patch.object(log_queue, "get", side_effect=fake_get), \
             patch("asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await app_module.log_broadcast_loop()
