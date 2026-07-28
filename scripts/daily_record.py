#!/usr/bin/env python3
"""
每日套利机会记录脚本

定时抓取套利引擎的当前机会快照，追加到 CSV 文件，用于每日复盘与策略调优。

用法（服务器 cron）：
    # 每小时整点抓取一次机会快照
    0 * * * * cd /root/openalpha-arbitrage && python3 scripts/daily_record.py

输出：
    data/snapshots/YYYY-MM-DD.csv
        列: timestamp, symbol, buy_exchange, sell_exchange,
            buy_price, sell_price, spread_percent, net_profit_rate,
            estimated_profit, risk_level

依赖：仅 Python 标准库（urllib + csv），无需安装第三方包。
"""

import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 套利引擎 API 地址（容器内为 localhost:8070）
API_BASE = os.environ.get("ARBITRAGE_API_BASE", "http://127.0.0.1:8070")
# 快照输出目录
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"
# 请求超时（秒）
REQUEST_TIMEOUT = 15
# UTC+8 时区
CN_TZ = timezone(timedelta(hours=8))


def fetch_opportunities():
    """从套利引擎 API 获取当前套利机会列表"""
    url = API_BASE + "/api/opportunities"
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("opportunities", [])
    except Exception as e:
        print("[%s] 获取机会失败: %s" % (datetime.now(CN_TZ).strftime("%H:%M:%S"), e))
        return []


def append_snapshot(opportunities):
    """将当前机会快照追加到当日 CSV 文件"""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    csv_path = SNAPSHOT_DIR / ("%s.csv" % today)
    now_str = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # CSV 列定义
    fieldnames = [
        "timestamp", "symbol", "buy_exchange", "sell_exchange",
        "buy_price", "sell_price", "spread_percent",
        "net_profit_rate", "estimated_profit", "risk_level",
    ]

    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for op in opportunities:
            writer.writerow({
                "timestamp": now_str,
                "symbol": op.get("symbol", ""),
                "buy_exchange": op.get("buy_exchange", ""),
                "sell_exchange": op.get("sell_exchange", ""),
                "buy_price": op.get("buy_price", 0),
                "sell_price": op.get("sell_price", 0),
                "spread_percent": op.get("spread_percent", 0),
                "net_profit_rate": op.get("net_profit_rate", 0),
                "estimated_profit": op.get("estimated_profit", 0),
                "risk_level": op.get("risk_level", ""),
            })

    print("[%s] 已记录 %d 个机会到 %s" % (
        now_str, len(opportunities), csv_path.name,
    ))


def main():
    """主入口：抓取机会并追加到当日 CSV"""
    opps = fetch_opportunities()
    append_snapshot(opps)


if __name__ == "__main__":
    main()
