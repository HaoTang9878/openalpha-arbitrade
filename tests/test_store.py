"""JsonlEventStore 与 RuntimeState 单元测试

覆盖场景：
- append + tail 基本读写
- 损坏行容错（不崩溃）
- 空文件 / 不存在文件返回空列表
- RuntimeState 初始化与 reset
- 多条事件按时间顺序写入
"""

from __future__ import annotations

import json

import pytest

from backend.store import JsonlEventStore, RuntimeState
from backend.tranche import Portfolio, StrategyConfig


# ----------------------------------------------------------------------------
# append + tail 基本读写
# ----------------------------------------------------------------------------
class TestAppendTail:
    """append + tail 基本读写测试"""

    def test_append_then_tail(self, tmp_path):
        """追加单条事件后 tail 能读回，结构正确"""
        store = JsonlEventStore(str(tmp_path))
        store.append("tick", {"price": 1.0, "symbol": "USDC/USDT"})
        events = store.tail()
        assert len(events) == 1
        event = events[0]
        assert event["type"] == "tick"
        assert event["payload"] == {"price": 1.0, "symbol": "USDC/USDT"}
        # 时间戳存在且为字符串
        assert "ts" in event
        assert isinstance(event["ts"], str)

    def test_ts_is_iso_format(self, tmp_path):
        """ts 字段为 ISO 8601 格式字符串（含 T 分隔符）"""
        store = JsonlEventStore(str(tmp_path))
        store.append("tick", {"price": 1.0})
        events = store.tail()
        assert "T" in events[0]["ts"]

    def test_payload_supports_unicode(self, tmp_path):
        """payload 中的中文内容能正确读写"""
        store = JsonlEventStore(str(tmp_path))
        store.append("note", {"msg": "买入信号触发"})
        events = store.tail()
        assert events[0]["payload"]["msg"] == "买入信号触发"

    def test_append_two_stores_share_file(self, tmp_path):
        """两个 store 指向同一目录时追加到同一文件"""
        store1 = JsonlEventStore(str(tmp_path))
        store2 = JsonlEventStore(str(tmp_path))
        store1.append("tick", {"src": 1})
        store2.append("tick", {"src": 2})
        events = store1.tail()
        assert len(events) == 2
        assert [e["payload"]["src"] for e in events] == [1, 2]


# ----------------------------------------------------------------------------
# 损坏行容错
# ----------------------------------------------------------------------------
class TestCorruptLine:
    """损坏行容错测试"""

    def test_corrupt_line_does_not_crash(self, tmp_path):
        """损坏行不导致崩溃，标记为 corrupt_log_line"""
        store = JsonlEventStore(str(tmp_path))
        store.append("tick", {"ok": True})
        # 手动追加一行损坏数据
        with store.event_path.open("a", encoding="utf-8") as f:
            f.write("this is not json\n")
        store.append("tick", {"ok": False})

        events = store.tail()
        assert len(events) == 3
        assert events[0]["type"] == "tick"
        assert events[1]["type"] == "corrupt_log_line"
        assert events[1]["payload"] == {"line": "this is not json"}
        assert events[2]["type"] == "tick"

    def test_corrupt_line_payload_keeps_raw(self, tmp_path):
        """损坏行的 payload 保留原始行内容"""
        store = JsonlEventStore(str(tmp_path))
        with store.event_path.open("a", encoding="utf-8") as f:
            f.write("{bad json\n")
        events = store.tail()
        assert len(events) == 1
        assert events[0]["type"] == "corrupt_log_line"
        assert events[0]["payload"] == {"line": "{bad json"}

    def test_only_corrupt_lines(self, tmp_path):
        """全部为损坏行时每行都标记为 corrupt_log_line"""
        store = JsonlEventStore(str(tmp_path))
        with store.event_path.open("a", encoding="utf-8") as f:
            f.write("oops\n")
            f.write("still bad\n")
        events = store.tail()
        assert len(events) == 2
        assert all(e["type"] == "corrupt_log_line" for e in events)


# ----------------------------------------------------------------------------
# 空文件 / 不存在文件
# ----------------------------------------------------------------------------
class TestEmptyAndMissing:
    """空文件 / 不存在文件返回空列表测试"""

    def test_nonexistent_file_returns_empty(self, tmp_path):
        """文件不存在时返回空列表"""
        store = JsonlEventStore(str(tmp_path))
        assert store.tail() == []
        assert store.tail(limit=10) == []

    def test_empty_file_returns_empty(self, tmp_path):
        """空文件返回空列表"""
        store = JsonlEventStore(str(tmp_path))
        store.event_path.write_text("", encoding="utf-8")
        assert store.tail() == []

    def test_blank_lines_treated_as_corrupt(self, tmp_path):
        """仅含空行的文件按损坏行处理"""
        store = JsonlEventStore(str(tmp_path))
        with store.event_path.open("a", encoding="utf-8") as f:
            f.write("\n\n")
        events = store.tail()
        assert len(events) == 2
        assert all(e["type"] == "corrupt_log_line" for e in events)
        assert all(e["payload"]["line"] == "" for e in events)

    def test_data_dir_created(self, tmp_path):
        """构造时自动创建不存在的 data_dir"""
        target = tmp_path / "nested" / "events"
        assert not target.exists()
        JsonlEventStore(str(target))
        assert target.exists()
        assert target.is_dir()


# ----------------------------------------------------------------------------
# RuntimeState 初始化与 reset
# ----------------------------------------------------------------------------
class TestRuntimeState:
    """RuntimeState 初始化与 reset 测试"""

    def test_init_creates_portfolio(self):
        """初始化时通过 from_config 创建 portfolio"""
        config = StrategyConfig(total_capital_usd=5_000.0)
        state = RuntimeState(config)
        assert state.config is config
        assert isinstance(state.portfolio, Portfolio)
        assert state.portfolio.usdt_available == 5_000.0
        assert state.portfolio.usd_available == 0.0
        assert state.portfolio.realized_profit_usd == 0.0
        assert state.portfolio.open_tranches == []

    def test_reset_rebuilds_portfolio(self):
        """reset 后 portfolio 回到初始状态"""
        config = StrategyConfig(total_capital_usd=5_000.0)
        state = RuntimeState(config)
        # 模拟运行后状态被修改
        state.portfolio.usdt_available = 100.0
        state.portfolio.realized_profit_usd = 50.0
        state.reset()
        assert state.portfolio.usdt_available == 5_000.0
        assert state.portfolio.realized_profit_usd == 0.0

    def test_reset_returns_new_instance(self):
        """reset 后 portfolio 为全新实例"""
        config = StrategyConfig(total_capital_usd=5_000.0)
        state = RuntimeState(config)
        old_portfolio = state.portfolio
        state.reset()
        assert state.portfolio is not old_portfolio

    def test_config_dict(self):
        """config_dict 返回配置字典"""
        config = StrategyConfig(total_capital_usd=5_000.0, tranche_count=5)
        state = RuntimeState(config)
        data = state.config_dict()
        assert data["total_capital_usd"] == 5_000.0
        assert data["tranche_count"] == 5

    def test_portfolio_dict(self):
        """portfolio_dict 返回组合字典"""
        config = StrategyConfig(total_capital_usd=5_000.0)
        state = RuntimeState(config)
        data = state.portfolio_dict()
        assert data["usdt_available"] == 5_000.0
        assert data["usd_available"] == 0.0
        assert data["open_tranches"] == []

    def test_config_dict_reflects_changes(self):
        """config_dict 反映同一 config 对象的字段"""
        config = StrategyConfig(total_capital_usd=8_000.0, fee_bps=2.0)
        state = RuntimeState(config)
        data = state.config_dict()
        assert data["total_capital_usd"] == 8_000.0
        assert data["fee_bps"] == 2.0


# ----------------------------------------------------------------------------
# 多条事件按时间顺序写入
# ----------------------------------------------------------------------------
class TestEventOrder:
    """多条事件按时间顺序写入测试"""

    def test_events_returned_in_append_order(self, tmp_path):
        """多条事件按写入顺序返回"""
        store = JsonlEventStore(str(tmp_path))
        for i in range(5):
            store.append("tick", {"i": i})
        events = store.tail()
        assert len(events) == 5
        assert [e["payload"]["i"] for e in events] == [0, 1, 2, 3, 4]

    def test_timestamps_non_decreasing(self, tmp_path):
        """连续写入事件的 ts 按写入顺序非递减"""
        store = JsonlEventStore(str(tmp_path))
        for i in range(5):
            store.append("tick", {"i": i})
        events = store.tail()
        timestamps = [e["ts"] for e in events]
        # ISO 字符串字典序与时间序一致
        assert timestamps == sorted(timestamps)

    def test_mixed_event_types_keep_order(self, tmp_path):
        """不同类型事件混合写入顺序保持"""
        store = JsonlEventStore(str(tmp_path))
        store.append("start", {"phase": 1})
        store.append("tick", {"price": 1.0})
        store.append("fill", {"order": "abc"})
        store.append("stop", {"phase": 2})
        events = store.tail()
        types = [e["type"] for e in events]
        assert types == ["start", "tick", "fill", "stop"]

    def test_tail_limit_returns_latest(self, tmp_path):
        """tail(limit) 只返回最近 N 条，且为最新事件"""
        store = JsonlEventStore(str(tmp_path))
        n = 150
        for i in range(n):
            store.append("tick", {"i": i})
        # 默认 limit=100
        events = store.tail()
        assert len(events) == 100
        assert events[0]["payload"]["i"] == 50
        assert events[-1]["payload"]["i"] == 149
        # 取全部
        all_events = store.tail(limit=n)
        assert len(all_events) == n
        assert all_events[0]["payload"]["i"] == 0

    def test_raw_file_format(self, tmp_path):
        """写入文件每行一个合法 JSON 对象"""
        store = JsonlEventStore(str(tmp_path))
        store.append("tick", {"price": 1.0})
        store.append("tick", {"price": 1.1})
        raw_lines = store.event_path.read_text(encoding="utf-8").splitlines()
        assert len(raw_lines) == 2
        # 每行都能被解析为合法 JSON
        for line in raw_lines:
            obj = json.loads(line)
            assert set(obj.keys()) == {"ts", "type", "payload"}
