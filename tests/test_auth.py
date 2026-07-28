"""
鉴权中间件单元测试

覆盖 backend/auth.py 的核心方法：
- _get_expected_token() — 读取环境变量 token
- _extract_token() — 从请求提取 token
- _is_public() — 判断只读公开端点
- AuthMiddleware.dispatch() — 鉴权中间件逻辑
- add_auth_middleware() — 注册中间件
"""

import hmac
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.auth import (
    AuthMiddleware,
    _extract_token,
    _get_expected_token,
    _is_public,
    add_auth_middleware,
)


# ----------------------------------------------------------------------------
# 辅助函数测试
# ----------------------------------------------------------------------------
class TestGetExpectedToken:
    """_get_expected_token() 测试"""

    def test_returns_none_when_not_configured(self, monkeypatch):
        """未配置环境变量时返回 None"""
        monkeypatch.delenv("ARBITRAGE_API_TOKEN", raising=False)
        assert _get_expected_token() is None

    def test_returns_token_when_configured(self, monkeypatch):
        """配置环境变量后返回 token"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret_token_123")
        assert _get_expected_token() == "secret_token_123"

    def test_returns_none_for_empty_string(self, monkeypatch):
        """空字符串视为未配置"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "")
        assert _get_expected_token() is None


class TestExtractToken:
    """_extract_token() 测试"""

    def _make_request(self, headers=None, query_params=None):
        """构造 mock Request"""
        request = MagicMock()
        request.headers = headers or {}
        request.query_params = query_params or {}
        return request

    def test_extract_bearer_token(self):
        """从 Authorization: Bearer xxx 提取 token"""
        request = self._make_request(headers={"authorization": "Bearer my_token"})
        assert _extract_token(request) == "my_token"

    def test_extract_bearer_token_case_insensitive(self):
        """Bearer 前缀大小写不敏感"""
        request = self._make_request(headers={"authorization": "bearer my_token"})
        assert _extract_token(request) == "my_token"

    def test_extract_bearer_token_strips_whitespace(self):
        """token 去除首尾空白"""
        request = self._make_request(headers={"authorization": "Bearer   my_token  "})
        assert _extract_token(request) == "my_token"

    def test_extract_token_from_query(self):
        """从 query 参数 ?token=xxx 提取"""
        request = self._make_request(query_params={"token": "query_token"})
        assert _extract_token(request) == "query_token"

    def test_extract_token_no_auth_header(self):
        """无 Authorization 头且无 query token 时返回 None"""
        request = self._make_request()
        assert _extract_token(request) is None

    def test_extract_token_non_bearer_header(self):
        """非 Bearer 类型的 Authorization 头返回 None（回退到 query）"""
        request = self._make_request(
            headers={"authorization": "Basic abc123"},
            query_params={},
        )
        assert _extract_token(request) is None

    def test_extract_token_bearer_takes_priority(self):
        """Bearer token 优先于 query token"""
        request = self._make_request(
            headers={"authorization": "Bearer header_token"},
            query_params={"token": "query_token"},
        )
        assert _extract_token(request) == "header_token"


class TestIsPublic:
    """_is_public() 测试"""

    def _make_request(self, method, path):
        request = MagicMock()
        request.method = method
        request.url.path = path
        return request

    def test_public_get_paths(self):
        """只读公开端点放行"""
        for path in ["/", "/api/status", "/api/prices", "/api/opportunities",
                     "/api/trades", "/api/exchanges", "/api/balances",
                     "/api/risk/status", "/api/config", "/docs", "/openapi.json", "/redoc"]:
            assert _is_public(self._make_request("GET", path)) is True

    def test_static_resources_public(self):
        """静态资源放行"""
        assert _is_public(self._make_request("GET", "/static/css/main.css")) is True
        assert _is_public(self._make_request("GET", "/static/js/app.js")) is True

    def test_non_get_method_not_public(self):
        """非 GET 方法不放行（即使是公开路径）"""
        assert _is_public(self._make_request("POST", "/api/status")) is False
        assert _is_public(self._make_request("PUT", "/api/config")) is False

    def test_unknown_path_not_public(self):
        """未知路径不放行"""
        assert _is_public(self._make_request("GET", "/api/unknown")) is False

    def test_protected_write_paths_not_public(self):
        """写/执行路径不放行"""
        for path in ["/api/scanner/start", "/api/arbitrage/start",
                     "/api/trades/execute", "/api/risk/resume", "/api/keys"]:
            assert _is_public(self._make_request("POST", path)) is False


# ----------------------------------------------------------------------------
# AuthMiddleware 集成测试（使用 TestClient）
# ----------------------------------------------------------------------------
def _create_test_app(token=None):
    """创建带鉴权中间件的测试 FastAPI 应用"""
    app = FastAPI()

    @app.get("/api/status")
    async def status():
        return {"status": "ok"}

    @app.get("/")
    async def index():
        return {"hello": "world"}

    @app.post("/api/scanner/start")
    async def start_scanner():
        return {"status": "started"}

    @app.put("/api/config")
    async def update_config():
        return {"status": "ok"}

    @app.get("/api/unknown")
    async def unknown():
        return {"data": "secret"}

    add_auth_middleware(app)
    return app


class TestAuthMiddleware:
    """AuthMiddleware 鉴权逻辑测试"""

    def test_public_get_no_token_required(self, monkeypatch):
        """公开 GET 端点无需 token"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_index_no_token_required(self, monkeypatch):
        """根路径无需 token"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_write_blocked_without_token_configured(self, monkeypatch):
        """未配置 token 时写操作被拒绝（503）"""
        monkeypatch.delenv("ARBITRAGE_API_TOKEN", raising=False)
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/scanner/start")
        assert resp.status_code == 503
        assert resp.json()["error"] == "service_locked"

    def test_write_blocked_without_provided_token(self, monkeypatch):
        """配置 token 但请求未带 token 时拒绝（401）"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/scanner/start")
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    def test_write_blocked_with_wrong_token(self, monkeypatch):
        """token 错误时拒绝（403）"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            "/api/scanner/start",
            headers={"Authorization": "Bearer wrong_token"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "forbidden"

    def test_write_allowed_with_correct_token(self, monkeypatch):
        """正确 token 时写操作通过"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            "/api/scanner/start",
            headers={"Authorization": "Bearer secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_put_config_requires_token(self, monkeypatch):
        """PUT /api/config 需要 token"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        # 无 token
        resp = client.put("/api/config", json={"key": "value"})
        assert resp.status_code == 401
        # 有 token
        resp = client.put(
            "/api/config",
            json={"key": "value"},
            headers={"Authorization": "Bearer secret"},
        )
        assert resp.status_code == 200

    def test_unknown_get_path_requires_token(self, monkeypatch):
        """未知 GET 路径需要 token（非公开）"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        # 无 token -> 401
        resp = client.get("/api/unknown")
        assert resp.status_code == 401
        # 有 token -> 200
        resp = client.get(
            "/api/unknown",
            headers={"Authorization": "Bearer secret"},
        )
        assert resp.status_code == 200

    def test_token_via_query_param(self, monkeypatch):
        """通过 query 参数 ?token=xxx 鉴权"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/scanner/start?token=secret")
        assert resp.status_code == 200

    def test_add_auth_middleware_idempotent(self, monkeypatch):
        """add_auth_middleware 可重复调用"""
        monkeypatch.setenv("ARBITRAGE_API_TOKEN", "secret")
        app = FastAPI()
        add_auth_middleware(app)
        # 不应抛异常
        add_auth_middleware(app)
