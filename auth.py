"""鉴权中间件 — Bearer token 校验。

安全策略:
  - 只读端点(GET /, /api/status, /api/prices, /api/opportunities,
    /api/trades, /api/exchanges, /api/balances, /api/risk/status,
    /api/config GET)无需鉴权(仪表盘可公开查看)
  - 写/执行端点(PUT/POST/DELETE,含 /api/config PUT, /api/keys*,
    /api/scanner/*, /api/arbitrage/*, /api/trades/execute,
    /api/risk/resume)必须带 Bearer token
  - WebSocket /ws 需 query 参数 ?token=xxx
  - token 从环境变量 ARBITRAGE_API_TOKEN 读取;未配置时拒绝所有写操作(安全默认)

用法(在 app.py 里):
    from backend.auth import add_auth_middleware
    add_auth_middleware(app)
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 只读放行路径(精确匹配,仅 GET)
_PUBLIC_GET_PATHS: frozenset[str] = frozenset({
    "/", "/api/status", "/api/prices", "/api/opportunities",
    "/api/opportunities/stats", "/api/trades", "/api/exchanges",
    "/api/balances", "/api/risk/status", "/api/config",
    "/api/daily-report", "/api/heatmap",
    "/api/symbols", "/api/symbols/categories",
    "/docs", "/openapi.json", "/redoc",
})

# 写/执行路径(必须鉴权)
# 用「非 GET 方法」作为判据即可,这里列出用于日志可读性
_PROTECTED_METHODS = {"PUT", "POST", "DELETE", "PATCH"}


def _get_expected_token() -> str | None:
    """从环境变量读取预期 token。未配置返回 None(安全默认:拒绝所有写操作)。"""
    return os.environ.get("ARBITRAGE_API_TOKEN") or None


def _extract_token(request: Request) -> str | None:
    """从 Authorization: Bearer xxx 或 query ?token=xxx 提取 token。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # WebSocket / 浏览器 query 参数兜底
    return request.query_params.get("token")


def _is_public(request: Request) -> bool:
    """判断是否只读公开端点。"""
    if request.method == "GET" and request.url.path in _PUBLIC_GET_PATHS:
        return True
    # 静态资源放行
    if request.url.path.startswith("/static/"):
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token 鉴权中间件。"""

    async def dispatch(self, request: Request, call_next):
        # 只读公开端点放行
        if _is_public(request):
            return await call_next(request)

        expected = _get_expected_token()
        # 安全默认:未配置 token 时,所有写/执行操作一律拒绝
        if not expected:
            logger.warning(
                "拒绝写操作 %s %s: ARBITRAGE_API_TOKEN 未配置",
                request.method, request.url.path,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service_locked",
                    "detail": "服务端未配置管理 token,写操作已禁用。请联系管理员设置 ARBITRAGE_API_TOKEN。",
                },
            )

        provided = _extract_token(request)
        if not provided:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "缺少 Authorization: Bearer <token>"},
            )
        # hmac.compare_digest 防时序攻击
        if not hmac.compare_digest(provided, expected):
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "detail": "token 无效"},
            )

        return await call_next(request)


def add_auth_middleware(app: FastAPI) -> None:
    """给 FastAPI app 添加鉴权中间件。"""
    app.add_middleware(AuthMiddleware)
    token = _get_expected_token()
    if token:
        logger.info("鉴权已启用: 写操作需 Bearer token (len=%d)", len(token))
    else:
        logger.warning("鉴权已启用: ARBITRAGE_API_TOKEN 未配置,所有写操作将被拒绝(安全默认)")
