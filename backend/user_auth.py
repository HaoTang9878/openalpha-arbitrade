"""
用户认证模块

提供用户注册、登录、JWT Token 签发与验证功能。
密码使用 bcrypt 加密存储，Token 使用 JWT（HS256）。

核心功能：
- 用户注册（邮箱 + 密码）
- 用户登录（返回 access_token + refresh_token）
- Token 验证（解析 JWT 并校验有效期）
- Token 刷新

使用方法：
    auth = UserAuth(database, secret_key)
    user = await auth.register("user@example.com", "password123")
    tokens = await auth.login("user@example.com", "password123")
    payload = auth.verify_token(tokens["access_token"])
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any, Dict, Optional

from .database import Database

logger = logging.getLogger(__name__)

# Token 有效期（秒）
ACCESS_TOKEN_EXPIRE = 3600 * 24       # 24 小时
REFRESH_TOKEN_EXPIRE = 3600 * 24 * 7  # 7 天

# PBKDF2 密码哈希参数
_PBKDF2_ITERATIONS = 100_000
_PBKDF2_SALT_BYTES = 16

# JWT 密钥：从环境变量读取，未配置时生成随机密钥并警告
_env_secret = os.environ.get("JWT_SECRET_KEY")
if _env_secret:
    DEFAULT_SECRET = _env_secret
else:
    DEFAULT_SECRET = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET_KEY 未配置，已生成随机密钥。"
        "重启后已签发的 Token 将失效，请在 .env 中设置 JWT_SECRET_KEY。"
    )


class UserAuth:
    """
    用户认证管理器

    提供用户注册、登录和 JWT Token 管理功能。
    """

    def __init__(
        self,
        database: Database,
        secret_key: str = DEFAULT_SECRET,
    ) -> None:
        """
        初始化用户认证管理器

        Args:
            database: 数据库实例
            secret_key: JWT 签名密钥
        """
        self.database = database
        self.secret_key = secret_key
        self._init_users_table()

    def _init_users_table(self) -> None:
        """创建用户表（如果不存在）"""
        try:
            with self.database._lock:
                self.database._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'user',
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        last_login TEXT
                    )
                    """
                )
            logger.info("用户表已就绪")
        except Exception as e:
            logger.error("创建用户表失败: %s", e)

    def _hash_password(self, password: str) -> str:
        """
        密码哈希（PBKDF2-HMAC-SHA256 + 随机盐）

        Args:
            password: 明文密码

        Returns:
            格式为 "iterations:salt_hex:hash_hex" 的密码字符串
        """
        salt = os.urandom(_PBKDF2_SALT_BYTES)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
        )
        return f"{_PBKDF2_ITERATIONS}:{salt.hex()}:{dk.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        """验证密码"""
        try:
            iterations_str, salt_hex, hash_hex = stored.split(":")
            iterations = int(iterations_str)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt, iterations
            )
            return hmac.compare_digest(dk, expected)
        except (ValueError, AttributeError):
            return False

    def _generate_jwt(self, payload: Dict[str, Any], expire: int) -> str:
        """
        生成 JWT Token（HS256，无第三方依赖）

        Args:
            payload: Token 载荷
            expire: 有效期（秒）

        Returns:
            JWT Token 字符串
        """
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time())
        body = {**payload, "iat": now, "exp": now + expire}

        # Base64URL 编码（无 padding）
        def b64url(data: bytes) -> str:
            import base64
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
        body_b64 = b64url(json.dumps(body, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{body_b64}"
        signature = hmac.new(
            self.secret_key.encode(), signing_input.encode(), hashlib.sha256
        ).hexdigest()
        return f"{signing_input}.{signature}"

    def _verify_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证 JWT Token

        Args:
            token: JWT Token 字符串

        Returns:
            Token 载荷（验证成功）或 None（验证失败/过期）
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            signing_input = f"{parts[0]}.{parts[1]}"
            expected_sig = hmac.new(
                self.secret_key.encode(), signing_input.encode(), hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(parts[2], expected_sig):
                return None

            # 解码 payload
            import base64
            padding = 4 - len(parts[1]) % 4
            payload_bytes = base64.urlsafe_b64decode(parts[1] + "=" * padding)
            payload = json.loads(payload_bytes)

            # 检查过期
            if payload.get("exp", 0) < int(time.time()):
                return None

            return payload
        except Exception as e:
            logger.debug("JWT 验证失败: %s", e)
            return None

    def register(self, email: str, password: str) -> Dict[str, Any]:
        """
        用户注册

        Args:
            email: 邮箱
            password: 密码

        Returns:
            注册结果 {status, user_id} 或 {error}
        """
        email = email.strip().lower()
        if not email or not password:
            return {"error": "邮箱和密码不能为空"}
        if len(password) < 6:
            return {"error": "密码长度至少 6 位"}

        # 检查邮箱是否已注册
        try:
            with self.database._lock:
                cursor = self.database._conn.execute(
                    "SELECT id FROM users WHERE email = ?", (email,)
                )
                if cursor.fetchone():
                    return {"error": "该邮箱已注册"}
        except Exception as e:
            logger.error("查询用户失败: %s", e)
            return {"error": "注册失败"}

        # 创建用户
        user_id = str(uuid.uuid4())[:8]
        password_hash = self._hash_password(password)

        try:
            with self.database._lock:
                self.database._conn.execute(
                    "INSERT INTO users (id, email, password_hash, role) VALUES (?, ?, ?, 'user')",
                    (user_id, email, password_hash),
                )
            logger.info("用户注册成功: %s (id=%s)", email, user_id)
            return {"status": "ok", "user_id": user_id, "email": email}
        except Exception as e:
            logger.error("注册失败: %s", e)
            return {"error": "注册失败"}

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """
        用户登录

        Args:
            email: 邮箱
            password: 密码

        Returns:
            {access_token, refresh_token, user} 或 {error}
        """
        email = email.strip().lower()

        try:
            with self.database._lock:
                cursor = self.database._conn.execute(
                    "SELECT id, email, password_hash, role FROM users WHERE email = ?",
                    (email,),
                )
                row = cursor.fetchone()
        except Exception as e:
            logger.error("查询用户失败: %s", e)
            return {"error": "登录失败"}

        if not row:
            return {"error": "用户不存在"}
        if not self._verify_password(password, row["password_hash"]):
            return {"error": "密码错误"}

        # 更新最后登录时间
        try:
            with self.database._lock:
                self.database._conn.execute(
                    "UPDATE users SET last_login = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
        except Exception:
            pass

        # 生成 Token
        user_info = {
            "user_id": row["id"],
            "email": row["email"],
            "role": row["role"],
        }
        access_token = self._generate_jwt(
            {**user_info, "type": "access"}, ACCESS_TOKEN_EXPIRE
        )
        refresh_token = self._generate_jwt(
            {**user_info, "type": "refresh"}, REFRESH_TOKEN_EXPIRE
        )

        logger.info("用户登录成功: %s", email)
        return {
            "status": "ok",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_info,
        }

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证 Access Token

        Args:
            token: JWT Token

        Returns:
            用户信息（验证成功）或 None
        """
        payload = self._verify_jwt(token)
        if not payload or payload.get("type") != "access":
            return None
        return payload

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        刷新 Token

        Args:
            refresh_token: Refresh Token

        Returns:
            {access_token, refresh_token} 或 {error}
        """
        payload = self._verify_jwt(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return {"error": "无效的 refresh token"}

        user_info = {
            "user_id": payload["user_id"],
            "email": payload["email"],
            "role": payload["role"],
        }
        new_access = self._generate_jwt(
            {**user_info, "type": "access"}, ACCESS_TOKEN_EXPIRE
        )
        new_refresh = self._generate_jwt(
            {**user_info, "type": "refresh"}, REFRESH_TOKEN_EXPIRE
        )
        return {
            "status": "ok",
            "access_token": new_access,
            "refresh_token": new_refresh,
        }
