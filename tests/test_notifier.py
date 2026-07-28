"""
Telegram 通知模块单元测试

覆盖 backend/notifier.py 的核心方法：
- Notifier.is_enabled() — 配置检查
- notify_opportunity() — 机会通知（mock Telegram API）
- notify_risk_halt() / notify_error() / notify_status() — 各类告警
- send_message() — 消息发送（mock urllib.request.urlopen）
- 频率限制与阈值过滤
- _escape_markdown() / _format_number() 辅助函数
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import urllib.error

from backend.models import ArbitrageOpportunity, RiskLevel
from backend.notifier import (
    Notifier,
    _DEFAULT_MIN_PROFIT_ALERT,
    _RATE_LIMIT_SECONDS,
    _escape_markdown,
    _format_number,
)


# ----------------------------------------------------------------------------
# 辅助函数测试
# ----------------------------------------------------------------------------
class TestHelpers:
    """_escape_markdown() 和 _format_number() 辅助函数测试"""

    def test_escape_markdown_special_chars(self):
        """转义 Telegram Markdown 特殊字符"""
        assert _escape_markdown("hello_world") == "hello\\_world"
        assert _escape_markdown("bold*text") == "bold\\*text"
        assert _escape_markdown("code`text") == "code\\`text"
        assert _escape_markdown("[link]") == "\\[link\\]"

    def test_escape_markdown_no_special_chars(self):
        """无特殊字符时原样返回"""
        assert _escape_markdown("plain text 123") == "plain text 123"

    def test_escape_markdown_empty(self):
        """空字符串原样返回"""
        assert _escape_markdown("") == ""

    def test_format_number_normal(self):
        """格式化数字添加千分位"""
        assert _format_number(1234567.891) == "1,234,567.89"
        assert _format_number(0.0) == "0.00"
        assert _format_number(100) == "100.00"

    def test_format_number_invalid(self):
        """无效输入返回字符串形式"""
        assert _format_number("not_a_number") == "not_a_number"
        assert _format_number(None) == "None"


# ----------------------------------------------------------------------------
# is_enabled() 配置检查测试
# ----------------------------------------------------------------------------
class TestIsEnabled:
    """Notifier.is_enabled() 配置检查测试"""

    def test_not_enabled_without_config(self):
        """未配置 BOT_TOKEN/CHAT_ID 时 is_enabled=False"""
        notifier = Notifier()
        assert notifier.is_enabled() is False

    def test_enabled_with_config(self, monkeypatch):
        """配置 BOT_TOKEN 和 CHAT_ID 后 is_enabled=True"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()
        assert notifier.is_enabled() is True

    def test_disabled_with_only_token(self, monkeypatch):
        """只配置 BOT_TOKEN 时 is_enabled=False"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        notifier = Notifier()
        assert notifier.is_enabled() is False

    def test_disabled_with_only_chat_id(self, monkeypatch):
        """只配置 CHAT_ID 时 is_enabled=False"""
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()
        assert notifier.is_enabled() is False

    def test_strips_whitespace(self, monkeypatch):
        """配置值去除首尾空白"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "  123:abc  ")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "  987654  ")
        notifier = Notifier()
        assert notifier.is_enabled() is True
        assert notifier.bot_token == "123:abc"
        assert notifier.chat_id == "987654"

    def test_default_min_profit_alert(self):
        """未配置阈值时使用默认值"""
        notifier = Notifier()
        assert notifier.min_profit_alert == _DEFAULT_MIN_PROFIT_ALERT

    def test_custom_min_profit_alert(self, monkeypatch):
        """自定义净利润率告警阈值"""
        monkeypatch.setenv("TELEGRAM_MIN_PROFIT_ALERT", "0.01")
        notifier = Notifier()
        assert notifier.min_profit_alert == 0.01

    def test_invalid_min_profit_alert_falls_back(self, monkeypatch):
        """无效阈值回退到默认值"""
        monkeypatch.setenv("TELEGRAM_MIN_PROFIT_ALERT", "not_a_number")
        notifier = Notifier()
        assert notifier.min_profit_alert == _DEFAULT_MIN_PROFIT_ALERT


# ----------------------------------------------------------------------------
# send_message() 消息发送测试（mock urllib）
# ----------------------------------------------------------------------------
class TestSendMessage:
    """send_message() 消息发送测试"""

    def test_send_message_disabled_returns_false(self):
        """未配置时 send_message 返回 False"""
        notifier = Notifier()
        assert notifier.send_message("test") is False

    def test_send_message_success(self, monkeypatch):
        """成功发送消息返回 True"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert notifier.send_message("hello") is True

    def test_send_message_api_error(self, monkeypatch):
        """Telegram API 返回 ok=False 时返回 False"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"ok": False, "description": "chat not found"}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert notifier.send_message("hello") is False

    def test_send_message_network_error(self, monkeypatch):
        """网络错误时返回 False"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            assert notifier.send_message("hello") is False

    def test_send_message_invalid_json_response(self, monkeypatch):
        """响应非 JSON 时返回 False"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert notifier.send_message("hello") is False

    def test_send_message_unexpected_exception(self, monkeypatch):
        """未知异常时返回 False（不影响主流程）"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch("urllib.request.urlopen", side_effect=RuntimeError("unexpected")):
            assert notifier.send_message("hello") is False


# ----------------------------------------------------------------------------
# notify_opportunity() 机会通知测试
# ----------------------------------------------------------------------------
class TestNotifyOpportunity:
    """notify_opportunity() 机会通知测试"""

    def test_disabled_skips_notification(self, sample_opportunity):
        """未配置时不发送通知"""
        notifier = Notifier()
        # 不应抛异常
        notifier.notify_opportunity(sample_opportunity)

    def test_below_threshold_skipped(self, monkeypatch, sample_opportunity):
        """净利润率低于阈值时不发送"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()
        # sample_opportunity.net_profit_rate=0.00084 < 默认 0.005
        with patch.object(notifier, "send_message") as mock_send:
            notifier.notify_opportunity(sample_opportunity)
        mock_send.assert_not_called()

    def test_above_threshold_sends(self, monkeypatch, high_profit_opportunity):
        """净利润率超过阈值时发送"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()
        # high_profit_opportunity.net_profit_rate=0.00932 > 0.005
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_opportunity(high_profit_opportunity)
        mock_send.assert_called_once()
        # 验证消息内容包含交易对
        sent_text = mock_send.call_args[0][0]
        assert "BTC/USDT" in sent_text
        assert "套利机会" in sent_text

    def test_rate_limit_prevents_duplicate(self, monkeypatch, high_profit_opportunity):
        """频率限制：同一交易对 5 分钟内只通知一次"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_opportunity(high_profit_opportunity)
            notifier.notify_opportunity(high_profit_opportunity)  # 第二次被限流
        assert mock_send.call_count == 1

    def test_rate_limit_different_symbols(self, monkeypatch):
        """频率限制按交易对独立计算"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        op_btc = ArbitrageOpportunity(
            symbol="BTC/USDT", buy_exchange="binance", sell_exchange="okx",
            buy_price=95000.0, sell_price=96000.0,
            spread_percent=0.01052, net_profit_rate=0.00932,
            estimated_profit=8.85, risk_level=RiskLevel.MEDIUM,
            timestamp=1700000000000,
        )
        op_eth = ArbitrageOpportunity(
            symbol="ETH/USDT", buy_exchange="binance", sell_exchange="okx",
            buy_price=3200.0, sell_price=3300.0,
            spread_percent=0.03125, net_profit_rate=0.03005,
            estimated_profit=9.61, risk_level=RiskLevel.HIGH,
            timestamp=1700000000000,
        )

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_opportunity(op_btc)
            notifier.notify_opportunity(op_eth)  # 不同交易对，不受限
        assert mock_send.call_count == 2

    def test_rate_limit_expires(self, monkeypatch, high_profit_opportunity):
        """频率限制窗口过期后可再次发送"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        # 模拟时间推进：第一次发送后，时间前进超过限制窗口
        import time as time_module
        with patch.object(notifier, "send_message", return_value=True) as mock_send, \
             patch("backend.notifier.time.time", side_effect=[
                 1000.0,  # 第一次发送的 now
                 1000.0 + _RATE_LIMIT_SECONDS + 1,  # 第二次的 now（已过期）
             ]):
            notifier.notify_opportunity(high_profit_opportunity)
            notifier.notify_opportunity(high_profit_opportunity)
        assert mock_send.call_count == 2

    def test_message_contains_risk_level(self, monkeypatch, high_profit_opportunity):
        """通知消息包含风险等级"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_opportunity(high_profit_opportunity)
        sent_text = mock_send.call_args[0][0]
        # high_profit_opportunity.risk_level = MEDIUM -> "MEDIUM"
        assert "MEDIUM" in sent_text


# ----------------------------------------------------------------------------
# 其他告警方法测试
# ----------------------------------------------------------------------------
class TestOtherNotifications:
    """notify_risk_halt / notify_error / notify_status 测试"""

    def test_notify_risk_halt_disabled(self):
        """未配置时 notify_risk_halt 静默跳过"""
        notifier = Notifier()
        notifier.notify_risk_halt("测试原因")  # 不应抛异常

    def test_notify_risk_halt_sends(self, monkeypatch):
        """配置后 notify_risk_halt 发送告警"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_risk_halt("亏损超限")
        mock_send.assert_called_once()
        assert "风控暂停" in mock_send.call_args[0][0]
        assert "亏损超限" in mock_send.call_args[0][0]

    def test_notify_error_disabled(self):
        """未配置时 notify_error 静默跳过"""
        notifier = Notifier()
        notifier.notify_error("系统异常")  # 不应抛异常

    def test_notify_error_sends(self, monkeypatch):
        """配置后 notify_error 发送告警"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_error("扫描器异常")
        mock_send.assert_called_once()
        assert "系统错误" in mock_send.call_args[0][0]
        assert "扫描器异常" in mock_send.call_args[0][0]

    def test_notify_status_disabled(self):
        """未配置时 notify_status 静默跳过"""
        notifier = Notifier()
        notifier.notify_status("系统启动")  # 不应抛异常

    def test_notify_status_sends(self, monkeypatch):
        """配置后 notify_status 发送告警"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_status("扫描器已启动")
        mock_send.assert_called_once()
        assert "系统状态" in mock_send.call_args[0][0]
        assert "扫描器已启动" in mock_send.call_args[0][0]

    def test_notify_risk_halt_escapes_reason(self, monkeypatch):
        """notify_risk_halt 转义原因中的特殊字符"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654")
        notifier = Notifier()

        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.notify_risk_halt("亏损_超限[严重]")
        sent_text = mock_send.call_args[0][0]
        # 特殊字符被转义
        assert "\\_" in sent_text
        assert "\\[" in sent_text
