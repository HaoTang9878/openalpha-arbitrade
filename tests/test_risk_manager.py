"""
风控管理器单元测试

覆盖 backend/risk_manager.py 的核心方法：
- RiskManager.check() — 风控规则检查
- record_trade_start() / record_trade_end() — 持仓和敞口管理
- _halt() / resume() — 暂停和恢复
- get_status() — 状态查询
"""

import pytest

from backend.models import ArbitrageOpportunity, OrderStatus, RiskLevel, TradeResult
from backend.risk_manager import (
    DEFAULT_MAX_DAILY_LOSS,
    DEFAULT_MAX_DAILY_TRADES,
    DEFAULT_MAX_EXPOSURE_PER_EX,
    DEFAULT_MAX_OPEN_POSITIONS,
    RiskManager,
)


# ----------------------------------------------------------------------------
# check() 风控规则检查测试
# ----------------------------------------------------------------------------
class TestRiskCheck:
    """RiskManager.check() 风控规则检查测试"""

    def test_check_allows_valid_trade(self, test_config, sample_opportunity):
        """正常交易通过风控检查"""
        rm = RiskManager(config=test_config)
        assert rm.check(sample_opportunity) is True

    def test_check_rejects_max_positions(self, test_config, sample_opportunity):
        """持仓数达到上限时拒绝"""
        rm = RiskManager(config=test_config)
        rm._open_positions = DEFAULT_MAX_OPEN_POSITIONS
        assert rm.check(sample_opportunity) is False

    def test_check_rejects_max_daily_trades(self, test_config, sample_opportunity):
        """每日交易次数达到上限时拒绝并暂停"""
        rm = RiskManager(config=test_config)
        rm._daily_trade_count = DEFAULT_MAX_DAILY_TRADES
        assert rm.check(sample_opportunity) is False
        # 触发暂停
        assert rm._halted is True
        assert rm._halt_reason != ""

    def test_check_rejects_max_daily_loss(self, test_config, sample_opportunity):
        """每日亏损超过上限时拒绝并暂停"""
        rm = RiskManager(config=test_config)
        rm._daily_pnl = -DEFAULT_MAX_DAILY_LOSS - 0.01
        assert rm.check(sample_opportunity) is False
        assert rm._halted is True

    def test_check_rejects_max_exposure_buy_side(self, test_config, sample_opportunity):
        """买入交易所敞口超限时拒绝"""
        rm = RiskManager(config=test_config)
        # sample_opportunity.buy_price=95001, order_amount=0.01 -> trade_value=950.01
        # DEFAULT_MAX_EXPOSURE_PER_EX=500，预设敞口接近上限
        rm._exchange_exposure[sample_opportunity.buy_exchange] = (
            DEFAULT_MAX_EXPOSURE_PER_EX - 1
        )
        assert rm.check(sample_opportunity) is False

    def test_check_rejects_max_exposure_sell_side(self, test_config, sample_opportunity):
        """卖出交易所敞口超限时拒绝"""
        rm = RiskManager(config=test_config)
        rm._exchange_exposure[sample_opportunity.sell_exchange] = (
            DEFAULT_MAX_EXPOSURE_PER_EX - 1
        )
        assert rm.check(sample_opportunity) is False

    def test_check_rejects_when_halted(self, test_config, sample_opportunity):
        """系统已暂停时拒绝所有交易"""
        rm = RiskManager(config=test_config)
        rm._halt("测试暂停")
        assert rm.check(sample_opportunity) is False

    def test_check_without_config_uses_default_amount(self, sample_opportunity):
        """未传入 config 时使用默认下单量 0.01"""
        rm = RiskManager()  # config=None
        assert rm.check(sample_opportunity) is True
        assert rm._get_order_amount() == 0.01

    def test_check_exposure_just_under_limit(self, test_config, sample_opportunity):
        """敞口刚好未超限时通过"""
        rm = RiskManager(config=test_config)
        # trade_value = 95001 * 0.01 = 950.01
        # 预设敞口使 buy_exposure + trade_value <= limit
        rm._exchange_exposure[sample_opportunity.buy_exchange] = 0.0
        rm._exchange_exposure[sample_opportunity.sell_exchange] = 0.0
        assert rm.check(sample_opportunity) is True


# ----------------------------------------------------------------------------
# record_trade_start() / record_trade_end() 持仓与敞口管理测试
# ----------------------------------------------------------------------------
class TestRecordTrade:
    """持仓和敞口管理测试"""

    def test_record_trade_start_increments_positions(self, test_config, sample_opportunity):
        """record_trade_start 增加持仓数和敞口"""
        rm = RiskManager(config=test_config)
        initial_positions = rm._open_positions
        rm.record_trade_start(sample_opportunity)
        assert rm._open_positions == initial_positions + 1

    def test_record_trade_start_increases_exposure(self, test_config, sample_opportunity):
        """record_trade_start 增加双边交易所敞口"""
        rm = RiskManager(config=test_config)
        rm.record_trade_start(sample_opportunity)
        trade_value = sample_opportunity.buy_price * test_config.model.order_amount
        assert rm._exchange_exposure[sample_opportunity.buy_exchange] == pytest.approx(trade_value)
        assert rm._exchange_exposure[sample_opportunity.sell_exchange] == pytest.approx(trade_value)

    def test_record_trade_end_decrements_positions(self, test_config, sample_trade_result):
        """record_trade_end 减少持仓数"""
        rm = RiskManager(config=test_config)
        rm._open_positions = 2
        rm.record_trade_end(sample_trade_result)
        assert rm._open_positions == 1

    def test_record_trade_end_updates_pnl(self, test_config, sample_trade_result):
        """record_trade_end 更新每日盈亏"""
        rm = RiskManager(config=test_config)
        initial_pnl = rm._daily_pnl
        rm.record_trade_end(sample_trade_result)
        assert rm._daily_pnl == pytest.approx(initial_pnl + sample_trade_result.profit)

    def test_record_trade_end_increments_trade_count(self, test_config, sample_trade_result):
        """record_trade_end 增加每日交易计数"""
        rm = RiskManager(config=test_config)
        initial_count = rm._daily_trade_count
        rm.record_trade_end(sample_trade_result)
        assert rm._daily_trade_count == initial_count + 1

    def test_record_trade_end_decreases_exposure(self, test_config, sample_trade_result):
        """record_trade_end 减少敞口"""
        rm = RiskManager(config=test_config)
        # 先增加敞口
        trade_value = sample_trade_result.buy_price * sample_trade_result.amount
        rm._exchange_exposure[sample_trade_result.buy_exchange] = trade_value
        rm._exchange_exposure[sample_trade_result.sell_exchange] = trade_value
        rm.record_trade_end(sample_trade_result)
        assert rm._exchange_exposure[sample_trade_result.buy_exchange] == pytest.approx(0.0)
        assert rm._exchange_exposure[sample_trade_result.sell_exchange] == pytest.approx(0.0)

    def test_record_trade_end_exposure_not_negative(self, test_config, sample_trade_result):
        """敞口不会变为负数（有下限保护）"""
        rm = RiskManager(config=test_config)
        # 不预设敞口，直接结束交易 -> 敞口变负后被钳制为 0
        rm.record_trade_end(sample_trade_result)
        assert rm._exchange_exposure[sample_trade_result.buy_exchange] >= 0
        assert rm._exchange_exposure[sample_trade_result.sell_exchange] >= 0

    def test_record_trade_end_positions_not_negative(self, test_config, sample_trade_result):
        """持仓数不会变为负数"""
        rm = RiskManager(config=test_config)
        rm._open_positions = 0
        rm.record_trade_end(sample_trade_result)
        assert rm._open_positions == 0

    def test_full_trade_lifecycle(self, test_config, sample_opportunity, sample_trade_result):
        """完整交易生命周期：开始 -> 结束，状态正确"""
        rm = RiskManager(config=test_config)
        assert rm._open_positions == 0

        rm.record_trade_start(sample_opportunity)
        assert rm._open_positions == 1

        rm.record_trade_end(sample_trade_result)
        assert rm._open_positions == 0
        assert rm._daily_trade_count == 1
        assert rm._daily_pnl == pytest.approx(sample_trade_result.profit)


# ----------------------------------------------------------------------------
# _halt() / resume() 暂停与恢复测试
# ----------------------------------------------------------------------------
class TestHaltResume:
    """暂停和恢复测试"""

    def test_halt_sets_halted_flag(self, test_config):
        """_halt 设置暂停标记和原因"""
        rm = RiskManager(config=test_config)
        rm._halt("测试原因")
        assert rm._halted is True
        assert rm._halt_reason == "测试原因"

    def test_resume_clears_halted_flag(self, test_config):
        """resume 清除暂停标记"""
        rm = RiskManager(config=test_config)
        rm._halt("测试原因")
        rm.resume()
        assert rm._halted is False
        assert rm._halt_reason == ""

    def test_halt_calls_notifier(self, test_config):
        """_halt 触发时调用通知器的 notify_risk_halt"""
        class MockNotifier:
            def __init__(self):
                self.called = False
                self.reason = None

            def notify_risk_halt(self, reason):
                self.called = True
                self.reason = reason

        notifier = MockNotifier()
        rm = RiskManager(config=test_config, notifier=notifier)
        rm._halt("亏损超限")
        assert notifier.called is True
        assert notifier.reason == "亏损超限"

    def test_halt_notifier_failure_does_not_raise(self, test_config):
        """通知器抛异常时不影响风控逻辑"""
        class BadNotifier:
            def notify_risk_halt(self, reason):
                raise RuntimeError("通知发送失败")

        rm = RiskManager(config=test_config, notifier=BadNotifier())
        # 不应抛异常
        rm._halt("测试")
        assert rm._halted is True

    def test_halt_without_notifier_silent(self, test_config):
        """未配置通知器时 _halt 静默执行"""
        rm = RiskManager(config=test_config)
        rm._halt("无通知器")
        assert rm._halted is True


# ----------------------------------------------------------------------------
# get_status() 状态查询测试
# ----------------------------------------------------------------------------
class TestGetStatus:
    """get_status() 状态查询测试"""

    def test_get_status_returns_all_fields(self, test_config):
        """get_status 返回所有风控指标字段"""
        rm = RiskManager(config=test_config)
        status = rm.get_status()
        expected_keys = {
            "halted", "halt_reason", "open_positions",
            "max_open_positions", "daily_pnl", "max_daily_loss",
            "daily_trade_count", "max_daily_trades",
            "exchange_exposure", "max_exposure_per_exchange",
        }
        assert set(status.keys()) == expected_keys

    def test_get_status_initial_values(self, test_config):
        """初始状态值正确"""
        rm = RiskManager(config=test_config)
        status = rm.get_status()
        assert status["halted"] is False
        assert status["halt_reason"] == ""
        assert status["open_positions"] == 0
        assert status["max_open_positions"] == DEFAULT_MAX_OPEN_POSITIONS
        assert status["daily_pnl"] == 0.0
        assert status["max_daily_loss"] == DEFAULT_MAX_DAILY_LOSS
        assert status["daily_trade_count"] == 0
        assert status["max_daily_trades"] == DEFAULT_MAX_DAILY_TRADES
        assert status["exchange_exposure"] == {}
        assert status["max_exposure_per_exchange"] == DEFAULT_MAX_EXPOSURE_PER_EX

    def test_get_status_reflects_state_changes(self, test_config, sample_opportunity, sample_trade_result):
        """get_status 反映状态变化"""
        rm = RiskManager(config=test_config)
        rm.record_trade_start(sample_opportunity)
        rm.record_trade_end(sample_trade_result)
        rm._halt("测试")

        status = rm.get_status()
        assert status["halted"] is True
        assert status["halt_reason"] == "测试"
        assert status["daily_trade_count"] == 1
        assert status["daily_pnl"] == pytest.approx(
            round(sample_trade_result.profit, 2)
        )

    def test_get_status_pnl_rounded(self, test_config, sample_trade_result):
        """daily_pnl 保留两位小数"""
        rm = RiskManager(config=test_config)
        # 构造一个长小数利润
        trade = sample_trade_result.model_copy(update={"profit": 0.123456789})
        rm.record_trade_end(trade)
        status = rm.get_status()
        assert status["daily_pnl"] == round(0.123456789, 2)


# ----------------------------------------------------------------------------
# 每日重置测试
# ----------------------------------------------------------------------------
class TestDailyReset:
    """每日风控重置测试"""

    def test_reset_daily_if_needed_new_day(self, test_config):
        """日期变更时重置每日统计"""
        from datetime import date, timedelta

        rm = RiskManager(config=test_config)
        # 模拟昨天的数据
        rm._daily_date = date.today() - timedelta(days=1)
        rm._daily_pnl = -10.0
        rm._daily_trade_count = 5

        rm._reset_daily_if_needed()

        assert rm._daily_date == date.today()
        assert rm._daily_pnl == 0.0
        assert rm._daily_trade_count == 0

    def test_reset_daily_same_day_no_reset(self, test_config):
        """同一天不重置"""
        from datetime import date

        rm = RiskManager(config=test_config)
        rm._daily_date = date.today()
        rm._daily_pnl = 10.0
        rm._daily_trade_count = 3

        rm._reset_daily_if_needed()

        assert rm._daily_pnl == 10.0
        assert rm._daily_trade_count == 3
