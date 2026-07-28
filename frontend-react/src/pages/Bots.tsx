/**
 * Bots 页面 — 策略机器人管理
 *
 * 当前为占位页面，阶段二将实现完整的策略机器人管理：
 * - 网格机器人（GRID）
 * - DCA 定投机器人
 * - 三角套利
 * - 资金费率套利
 */

export function Bots() {
  const strategies = [
    {
      name: '跨所套利',
      icon: '🔄',
      status: '运行中',
      desc: '跨交易所价差套利，低价所买入高价所卖出',
      available: true,
    },
    {
      name: '网格机器人',
      icon: '📊',
      status: '即将上线',
      desc: '在价格区间内自动低买高卖，适合震荡行情',
      available: false,
    },
    {
      name: 'DCA 定投',
      icon: '💰',
      status: '即将上线',
      desc: '定期定额买入，价格下跌加码，反弹卖出',
      available: false,
    },
    {
      name: '三角套利',
      icon: '🔺',
      status: '即将上线',
      desc: '同所内 A→B→C→A 循环套利',
      available: false,
    },
    {
      name: '资金费率套利',
      icon: '⚖️',
      status: '即将上线',
      desc: '现货多头 + 永续空头对冲，赚取资金费率',
      available: false,
    },
  ];

  return (
    <div className="p-4 overflow-y-auto">
      <div className="mb-4">
        <h2 className="text-lg font-bold mb-1">策略机器人</h2>
        <p className="text-xs text-gray-400">管理和监控所有自动化交易策略</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {strategies.map((s) => (
          <div
            key={s.name}
            className={`panel ${!s.available && 'opacity-60'}`}
          >
            <div className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-2xl">{s.icon}</span>
                <span
                  className={`badge ${
                    s.status === '运行中'
                      ? 'bg-up/15 text-up'
                      : 'bg-gray-500/15 text-gray-400'
                  }`}
                >
                  {s.status}
                </span>
              </div>
              <h3 className="text-sm font-bold mb-1">{s.name}</h3>
              <p className="text-xs text-gray-400 mb-3">{s.desc}</p>
              <button
                disabled={!s.available}
                className={`btn btn-sm w-full ${s.available ? 'btn-primary' : 'btn-secondary'}`}
              >
                {s.available ? '管理' : '敬请期待'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
