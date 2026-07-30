"""JSONL 事件溯源存储

提供基于 JSONL 文件的追加式事件存储，以及运行时状态管理。
移植自 arbitrage_tool/app/store.py，适配 openalpha-arbitrage 结构
（Portfolio / StrategyConfig 由 backend.tranche 提供）。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tranche import Portfolio, StrategyConfig


class JsonlEventStore:
    """追加式 JSONL 事件存储。"""

    def __init__(self, data_dir: str | None = None):
        # data_dir 优先取参数，其次读 ARBITRAGE_DATA_DIR 环境变量，默认 ./data
        self.data_dir = Path(data_dir or os.getenv("ARBITRAGE_DATA_DIR", "./data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.event_path = self.data_dir / "events.jsonl"

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        # 追加写入一条事件：时间戳 + 类型 + 载荷
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": payload,
        }
        with self.event_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        # 读取最近 N 条事件；文件不存在或行损坏时容错处理
        if not self.event_path.exists():
            return []
        lines = self.event_path.read_text(encoding="utf-8").splitlines()
        events: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # 损坏行不中断读取，标记为 corrupt_log_line 并保留原始行
                events.append({"type": "corrupt_log_line", "payload": {"line": line}})
        return events


class RuntimeState:
    """运行时状态：持有策略配置与当前投资组合。"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.portfolio = Portfolio.from_config(config)

    def reset(self) -> None:
        # 重置组合到初始状态
        self.portfolio = Portfolio.from_config(self.config)

    def config_dict(self) -> dict[str, Any]:
        return asdict(self.config)

    def portfolio_dict(self) -> dict[str, Any]:
        return asdict(self.portfolio)
