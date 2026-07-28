"""
Telegram 告警通知模块

通过 Telegram Bot API 发送消息通知，支持：
- 大额套利机会告警（净利润率超过阈值）
- 风控触发告警（持仓超限/亏损超限/交易次数超限）
- 系统状态告警（扫描器启停/异常错误）

配置（环境变量）：
- TELEGRAM_BOT_TOKEN: Telegram Bot 的 API Token
- TELEGRAM_CHAT_ID: 接收消息的 Chat ID
- TELEGRAM_MIN_PROFIT_ALERT: 触发告警的最小净利润率（默认 0.005 = 0.5%）

未配置 BOT_TOKEN 或 CHAT_ID 时，通知模块静默跳过（不影响主流程）。

实现说明：
- 仅使用 Python 标准库 urllib.request，不新增依赖
- 所有网络请求失败仅记录日志，不抛出异常，确保不影响主流程
- 套利机会告警支持频率限制（同一交易对 5 分钟内最多通知一次）
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Dict

from .models import ArbitrageOpportunity

logger = logging.getLogger(__name__)

# 默认配置常量
_DEFAULT_MIN_PROFIT_ALERT = 0.005  # 默认最小净利润率告警阈值（0.5%）
_REQUEST_TIMEOUT = 10  # 网络请求超时（秒）
_RATE_LIMIT_SECONDS = 300  # 同一交易对频率限制窗口（5 分钟）
_TELEGRAM_API_BASE = "https://api.telegram.org/bot"

# Telegram Markdown 模式需转义的特殊字符（用于反引号代码块外的动态文本）
_MARKDOWN_SPECIAL_CHARS = "_*[]`"


def _escape_markdown(text: str) -> str:
    """转义 Telegram Markdown 特殊字符（用于代码块外的普通文本）"""
    for ch in _MARKDOWN_SPECIAL_CHARS:
        text = text.replace(ch, "\\" + ch)
    return text


def _format_number(value: float) -> str:
    """格式化数字，添加千分位分隔符并保留两位小数"""
    try:
        return "{:,.2f}".format(value)
    except (ValueError, TypeError):
        return str(value)


class Notifier:
    """
    Telegram 告警通知器

    通过 Telegram Bot API 发送消息。未配置 Token/Chat ID 时静默跳过，
    所有发送失败仅记录日志，不抛出异常，确保不影响主流程。

    使用方法：
        notifier = Notifier()
        if notifier.is_enabled():
            notifier.notify_opportunity(opportunity)
    """

    def __init__(self) -> None:
        """从环境变量读取 Telegram 配置"""
        self.bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

        # 最小净利润率告警阈值
        raw_threshold = os.environ.get("TELEGRAM_MIN_PROFIT_ALERT", "").strip()
        try:
            self.min_profit_alert: float = (
                float(raw_threshold) if raw_threshold else _DEFAULT_MIN_PROFIT_ALERT
            )
        except (ValueError, TypeError):
            logger.warning(
                "TELEGRAM_MIN_PROFIT_ALERT 配置无效（%s），使用默认值 %.4f",
                raw_threshold, _DEFAULT_MIN_PROFIT_ALERT,
            )
            self.min_profit_alert = _DEFAULT_MIN_PROFIT_ALERT

        # 频率限制：交易对 -> 上次通知时间戳
        self._last_notify: Dict[str, float] = {}

        if self.is_enabled():
            logger.info(
                "Telegram 通知已启用（最小净利润率告警阈值: %.4f%%）",
                self.min_profit_alert * 100,
            )
        else:
            logger.info("Telegram 通知未配置，静默跳过")

    def is_enabled(self) -> bool:
        """
        检查是否已配置 Telegram Bot Token 和 Chat ID

        Returns:
            已配置返回 True，否则返回 False
        """
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str) -> bool:
        """
        发送 Markdown 格式文本消息到 Telegram

        Args:
            text: 消息内容（Markdown 格式）

        Returns:
            是否发送成功（未配置或失败返回 False）
        """
        if not self.is_enabled():
            return False

        url = "%s%s/sendMessage" % (_TELEGRAM_API_BASE, self.bot_token)
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    result = json.loads(body)
                except (ValueError, TypeError):
                    result = {}
                if result.get("ok"):
                    logger.debug("Telegram 消息发送成功")
                    return True
                logger.warning(
                    "Telegram 消息发送失败: %s",
                    result.get("description", body),
                )
                return False
        except urllib.error.URLError as e:
            logger.warning("Telegram 请求失败（网络错误）: %s", e)
            return False
        except Exception as e:  # noqa: BLE001 - 通知失败不能影响主流程
            logger.warning("Telegram 通知异常: %s", e)
            return False

    def notify_opportunity(self, opportunity: ArbitrageOpportunity) -> None:
        """
        套利机会告警

        仅当净利润率 >= TELEGRAM_MIN_PROFIT_ALERT 时发送。
        同一交易对 5 分钟内最多通知一次（防止刷屏）。

        Args:
            opportunity: 套利机会对象
        """
        if not self.is_enabled():
            return

        # 净利润率阈值检查
        if opportunity.net_profit_rate < self.min_profit_alert:
            return

        # 频率限制检查（同一交易对 5 分钟内最多通知一次）
        now = time.time()
        last = self._last_notify.get(opportunity.symbol, 0.0)
        if now - last < _RATE_LIMIT_SECONDS:
            return
        self._last_notify[opportunity.symbol] = now

        # 风险等级（枚举值大写显示）
        try:
            risk_level = str(opportunity.risk_level.value).upper()
        except AttributeError:
            risk_level = str(opportunity.risk_level).upper()

        # 消息格式：交易对放在反引号代码块内（字面量，无需转义），
        # 交易所名称在普通文本中（需转义特殊字符）
        text = (
            "*🚨 套利机会*\n"
            "━━━━━━━━━━━━━\n"
            "交易对: `%s`\n"
            "买入: %s @ %s\n"
            "卖出: %s @ %s\n"
            "价差: %.4f%%\n"
            "净利润率: %.4f%%\n"
            "预计利润: %.4f USDT\n"
            "风险等级: %s\n"
            "━━━━━━━━━━━━━"
        ) % (
            opportunity.symbol,
            _escape_markdown(opportunity.buy_exchange),
            _format_number(opportunity.buy_price),
            _escape_markdown(opportunity.sell_exchange),
            _format_number(opportunity.sell_price),
            opportunity.spread_percent,
            opportunity.net_profit_rate * 100,
            opportunity.estimated_profit,
            risk_level,
        )

        self.send_message(text)

    def notify_risk_halt(self, reason: str) -> None:
        """
        风控暂停告警

        当持仓超限/亏损超限/交易次数超限等风控规则触发时调用。

        Args:
            reason: 暂停原因
        """
        if not self.is_enabled():
            return

        text = (
            "*⛔ 风控暂停*\n"
            "━━━━━━━━━━━━━\n"
            "触发原因: %s\n"
            "━━━━━━━━━━━━━\n"
            "系统已自动暂停交易，请检查后手动恢复。"
        ) % _escape_markdown(reason)

        self.send_message(text)

    def notify_error(self, error: str) -> None:
        """
        系统错误告警

        当扫描器异常、执行器错误等系统级异常发生时调用。

        Args:
            error: 错误信息
        """
        if not self.is_enabled():
            return

        text = (
            "*❌ 系统错误*\n"
            "━━━━━━━━━━━━━\n"
            "%s\n"
            "━━━━━━━━━━━━━"
        ) % _escape_markdown(error)

        self.send_message(text)

    def notify_status(self, message: str) -> None:
        """
        系统状态告警

        用于扫描器启停、套利执行启停等状态变更通知。

        Args:
            message: 状态消息
        """
        if not self.is_enabled():
            return

        text = (
            "*ℹ️ 系统状态*\n"
            "━━━━━━━━━━━━━\n"
            "%s\n"
            "━━━━━━━━━━━━━"
        ) % _escape_markdown(message)

        self.send_message(text)
