#!/usr/bin/env python3
"""
每日报告生成脚本

从套利引擎 API 获取指定日期的汇总数据，生成 Markdown 格式的每日报告，
记录当日套利机会检测与模拟交易执行情况，用于每日复盘与问题排查。

用法（服务器 cron）：
    # 每日 23:55 生成当日报告
    55 23 * * * cd /root/openalpha-arbitrage && python3 scripts/daily_report.py

    # 也可手动生成指定日期的报告
    python3 scripts/daily_report.py 2026-07-28

输出：
    data/reports/YYYY-MM-DD.md

依赖：仅 Python 标准库（urllib + json），无需安装第三方包。
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 套利引擎 API 地址
API_BASE = os.environ.get("ARBITRAGE_API_BASE", "http://127.0.0.1:8070")
# 报告输出目录
REPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
# 请求超时（秒）
REQUEST_TIMEOUT = 20
# UTC+8 时区
CN_TZ = timezone(timedelta(hours=8))


def fetch_json(path):
    """从 API 获取 JSON 数据"""
    url = API_BASE + path
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("请求 %s 失败: %s" % (path, e))
        return {}


def fetch_status():
    """获取系统状态"""
    return fetch_json("/api/status")


def fetch_daily_report(date_str):
    """获取每日报告数据"""
    return fetch_json("/api/daily-report?date=%s" % date_str)


def fetch_exchange_status():
    """获取交易所连接状态"""
    return fetch_json("/api/exchanges")


def format_pct(val):
    """格式化百分比（输入为小数，输出为 % 字符串）"""
    if val is None:
        return "--"
    return "%.4f%%" % (val * 100)


def format_usdt(val):
    """格式化 USDT 金额"""
    if val is None:
        return "$0.00"
    sign = "+" if val >= 0 else ""
    return "%s$%.4f" % (sign, val)


def generate_report(date_str):
    """
    生成指定日期的 Markdown 报告

    Args:
        date_str: 日期字符串（YYYY-MM-DD）

    Returns:
        Markdown 格式的报告字符串
    """
    report = fetch_daily_report(date_str)
    status = fetch_status()
    exchanges = fetch_exchange_status()

    lines = []
    lines.append("# OpenAlpha 套利系统每日报告 — %s" % date_str)
    lines.append("")
    lines.append("> 自动生成于 %s（UTC+8）" % datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("")

    # 一、当日 KPI 汇总
    lines.append("## 一、当日 KPI 汇总")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append("| 检测到的机会总数 | %d |" % report.get("total_opportunities", 0))
    lines.append("| 涉及交易对数 | %d |" % report.get("unique_symbols", 0))
    lines.append("| 涉及交易所对数 | %d |" % report.get("unique_exchange_pairs", 0))
    lines.append("| 模拟交易笔数 | %d |" % report.get("total_trades", 0))
    lines.append("| 累计盈亏 | %s |" % format_usdt(report.get("total_profit", 0)))
    lines.append("| 胜率 | %.2f%% |" % (report.get("win_rate", 0) * 100))
    lines.append("")

    # 二、价差分布
    lines.append("## 二、价差分布")
    lines.append("")
    spread_dist = report.get("spread_distribution", {})
    lines.append("| 价差区间 | 机会数 | 占比 |")
    lines.append("|----------|--------|------|")
    total = report.get("total_opportunities", 0) or 1
    for bucket in ["<0.1%", "0.1-0.5%", "0.5-1%", ">1%"]:
        count = spread_dist.get(bucket, 0)
        pct = count / total * 100
        lines.append("| %s | %d | %.1f%% |" % (bucket, count, pct))
    lines.append("")

    # 三、Top 10 最大价差机会
    lines.append("## 三、Top 10 最大价差机会")
    lines.append("")
    top_opps = report.get("top_opportunities", [])
    if top_opps:
        lines.append("| # | 交易对 | 买入→卖出 | 买价 | 卖价 | 价差 | 净利润率 | 风险 |")
        lines.append("|---|--------|-----------|------|------|------|---------|------|")
        for i, op in enumerate(top_opps[:10], 1):
            lines.append("| %d | %s | %s→%s | %.4f | %.4f | %s | %s | %s |" % (
                i, op.get("symbol", ""),
                op.get("buy_exchange", ""), op.get("sell_exchange", ""),
                op.get("buy_price", 0), op.get("sell_price", 0),
                format_pct(op.get("spread_percent", 0)),
                format_pct(op.get("net_profit_rate", 0)),
                op.get("risk_level", ""),
            ))
    else:
        lines.append("当日无机会记录。")
    lines.append("")

    # 四、交易所对频次 Top 10
    lines.append("## 四、交易所对出现频次 Top 10")
    lines.append("")
    pair_freq = report.get("exchange_pair_frequency", {})
    if pair_freq:
        sorted_pairs = sorted(pair_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        lines.append("| 交易所对 | 出现次数 |")
        lines.append("|----------|---------|")
        for pair, count in sorted_pairs:
            lines.append("| %s | %d |" % (pair, count))
    else:
        lines.append("无数据。")
    lines.append("")

    # 五、交易对频次 Top 10
    lines.append("## 五、交易对出现频次 Top 10")
    lines.append("")
    sym_freq = report.get("symbol_frequency", {})
    if sym_freq:
        sorted_syms = sorted(sym_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        lines.append("| 交易对 | 出现次数 |")
        lines.append("|--------|---------|")
        for sym, count in sorted_syms:
            lines.append("| %s | %d |" % (sym, count))
    else:
        lines.append("无数据。")
    lines.append("")

    # 六、交易所连接状态
    lines.append("## 六、交易所连接状态")
    lines.append("")
    ex_list = exchanges.get("exchanges", [])
    if ex_list:
        lines.append("| 交易所 | 连接 | 模式 | 延迟(ms) | 错误数 |")
        lines.append("|--------|------|------|---------|--------|")
        for ex in ex_list:
            connected = "✅" if ex.get("connected") else "🔴"
            lines.append("| %s | %s | %s | %.0f | %d |" % (
                ex.get("name", ""), connected,
                ex.get("mode", "REST"),
                ex.get("latency_ms", 0),
                ex.get("error_count", 0),
            ))
    lines.append("")

    # 七、系统状态
    lines.append("## 七、系统状态")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append("| 扫描器运行 | %s |" % ("✅ 是" if status.get("scanner_running") else "🔴 否"))
    lines.append("| 自动套利运行 | %s |" % ("✅ 是" if status.get("arbitrage_running") else "🔴 否"))
    lines.append("| 模拟交易模式 | %s |" % ("是" if status.get("paper_trade") else "否（实盘）"))
    lines.append("| 监控交易所数 | %d |" % status.get("exchanges_count", 0))
    lines.append("| 监控交易对数 | %d |" % status.get("symbols_count", 0))
    lines.append("| 运行时长 | %d 秒 |" % status.get("uptime_seconds", 0))
    risk = status.get("risk_status", {})
    if risk:
        lines.append("| 风控暂停 | %s |" % ("🔴 是" if risk.get("halted") else "✅ 否"))
        lines.append("| 当前持仓 | %d / %d |" % (
            risk.get("open_positions", 0), risk.get("max_open_positions", 0)))
        lines.append("| 日盈亏 | %s / -%s |" % (
            format_usdt(risk.get("daily_pnl", 0)),
            format_usdt(-risk.get("max_daily_loss", 0)).lstrip("+"),
        ))
    lines.append("")

    # 八、问题排查记录
    lines.append("## 八、问题排查记录")
    lines.append("")
    issues = []
    if not status.get("arbitrage_running"):
        issues.append("- 🔴 自动套利未启动，需调用 `/api/arbitrage/start`")
    if not status.get("paper_trade"):
        issues.append("- ⚠️ 当前为实盘模式，注意资金风险")
    for ex in ex_list:
        if ex.get("error_count", 0) > 5:
            issues.append("- ⚠️ %s 错误数 %d，可能连接不稳定" % (
                ex.get("name"), ex.get("error_count")))
        if ex.get("latency_ms", 0) > 1000:
            issues.append("- ⚠️ %s 延迟 %.0fms 较高" % (
                ex.get("name"), ex.get("latency_ms")))
    if report.get("total_opportunities", 0) == 0:
        issues.append("- 🟡 当日无机会记录，可能价差过小或扫描异常")
    if report.get("total_trades", 0) == 0 and status.get("arbitrage_running"):
        issues.append("- 🟡 自动套利运行但无交易，可能机会未通过风控或净利润率为负")

    if issues:
        lines.extend(issues)
    else:
        lines.append("✅ 当日未发现明显问题。")
    lines.append("")

    lines.append("---")
    lines.append("*本报告由 `scripts/daily_report.py` 自动生成*")

    return "\n".join(lines)


def main():
    """主入口：生成当日或指定日期的报告"""
    # 默认取当天（UTC+8）
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now(CN_TZ).strftime("%Y-%m-%d")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / ("%s.md" % date_str)

    markdown = generate_report(date_str)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print("报告已生成: %s" % report_path)
    print("机会数: %d | 交易数: %d | 盈亏: %s" % (
        0, 0, "$0"  # 占位，实际值在报告内
    ))


if __name__ == "__main__":
    main()
