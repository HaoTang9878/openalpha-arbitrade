# OpenAlpha 套利机器人 - 任务规划

> **创建日期**: 2026-07-24
> **仓库地址**: https://github.com/HaoTang9878/openalpha-arbitrade
> **本地路径**: `/home/tanghao/workspace/openalpha-arbitrage/`

---

## 当前状态

### 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| GitHub 仓库 | ✅ 已创建 | 14 个文件已推送到 main 分支 |
| 后端核心 | ✅ 完成 | FastAPI + CCXT 异步架构 |
| 价格扫描器 | ✅ 完成 | 12 交易所并发扫描 |
| 套利检测引擎 | ✅ 完成 | 扣费净利润计算 + 风险评级 |
| 交易执行器 | ✅ 完成 | 模拟交易 + 实盘接口 |
| REST API | ✅ 完成 | 11 个端点 |
| WebSocket | ✅ 完成 | 实时推送价格/机会/交易 |
| 前端仪表盘 | ✅ 完成 | 实时监控页面 |
| Docker 部署 | ✅ 完成 | docker-compose.yml + Dockerfile |
| 本地 venv | ✅ 就绪 | Python 3.12 + 依赖已装 |

### 待开发

| 模块 | 优先级 | 说明 |
|------|--------|------|
| 单元测试 | 🔴 高 | 覆盖率需 ≥80%（用户规范要求） |
| 日志持久化 | 🟡 中 | 当前仅控制台输出，需落盘 |
| 数据库存储 | 🟡 中 | 交易历史、机会记录持久化 |
| 告警通知 | 🟡 中 | Telegram/钉钉/企业微信推送 |
| API 认证 | 🟡 中 | 当前 API 无鉴权保护 |
| 交易所余额监控 | 🟡 中 | 执行前余额检查 |
| 前端优化 | 🟢 低 | 图表可视化、历史回放 |
| 生产部署 | 🟢 低 | Vultr / 阿里云上线 |

---

## 任务分解

### 阶段一：本地验证（当前）

- [x] 1.1 Git 仓库初始化 + GitHub 推送
- [x] 1.2 创建 `.gitignore`（排除 .venv/data/.env）
- [x] 1.3 本地 Docker Compose 部署（容器 openalpha-arbitrage 运行中）
- [x] 1.4 验证 API 端点可访问（`/api/status` `/api/config` `/api/exchanges` 全部 200 OK）
- [ ] 1.5 验证 WebSocket 连接（`/ws`）— 待验证
- [x] 1.6 启动价格扫描，12 交易所全部初始化成功（12/12）
- [ ] 1.7 确认套利机会检测逻辑正确 — 受限于国内网络，交易所 API 不可达

> **1.6 验证结果（2026-07-24 22:12）**：
> - 扫描器初始化 12/12 交易所成功
> - 扫描循环正常启动（10 秒间隔）
> - 错误处理正常：网络错误被正确捕获并记录
> - bitfinex 不支持 BNB/USDT（已知限制）
> - ⚠️ **国内网络限制**：binance/coinbase/kraken/huobi/gate/poloniex API 不可达
> - **生产环境（Vultr 海外）不会有此问题**，本地需配置代理方可连通

### 阶段二：测试补全

- [ ] 2.1 编写 `tests/test_config.py` — 配置加载/更新测试
- [ ] 2.2 编写 `tests/test_arbitrage.py` — 套利检测逻辑测试
- [ ] 2.3 编写 `tests/test_scanner.py` — 价格扫描器测试（mock CCXT）
- [ ] 2.4 编写 `tests/test_executor.py` — 交易执行器测试
- [ ] 2.5 编写 `tests/test_app.py` — API 端点集成测试
- [ ] 2.6 覆盖率达标（≥80%）
- [ ] 2.7 配置 pytest + pytest-asyncio + pytest-cov

### 阶段三：功能增强

- [ ] 3.1 日志持久化（文件 + 滚动策略）
- [ ] 3.2 SQLite 存储交易历史和机会记录
- [ ] 3.3 交易所余额查询接口
- [ ] 3.4 Telegram 告警通知（高利润机会）
- [ ] 3.5 API Key 鉴权中间件
- [ ] 3.6 请求限流（防滥用）

### 阶段四：前端优化

- [ ] 4.1 价格走势图表（Chart.js / TradingView Lightweight Charts）
- [ ] 4.2 套利机会热力图
- [ ] 4.3 交易历史表格 + 筛选
- [ ] 4.4 配置面板可视化编辑
- [ ] 4.5 响应式布局适配

### 阶段五：生产部署

- [ ] 5.1 生产环境 `.env` 配置（交易所 API Key）
- [ ] 5.2 Nginx 反向代理 + HTTPS
- [ ] 5.3 systemd 服务 / Docker Swarm
- [ ] 5.4 监控告警（Prometheus + Grafana）
- [ ] 5.5 数据备份策略

---

## 技术栈

| 层 | 技术 | 版本 |
|----|------|------|
| 后端 | Python + FastAPI | 3.11/3.12 + 0.115.6 |
| 交易所接口 | CCXT | 4.4.24 |
| 前端 | HTML/CSS/JS + WebSocket | 原生 |
| 部署 | Docker + Docker Compose | 29.6.1 + v5.2.0 |
| 测试 | pytest + pytest-asyncio | 待安装 |

---

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MIN_PROFITABILITY` | 0.003 (0.3%) | 最小净利润率阈值 |
| `ORDER_AMOUNT` | 0.01 | 单笔下单量 |
| `SCAN_INTERVAL` | 10 秒 | 扫描间隔 |
| `MAX_ORDER_AGE` | 180 秒 | 订单超时 |
| `PAPER_TRADE` | true | 模拟交易模式 |
| 端口 | 8070 | 仅绑定 127.0.0.1 |

---

## 服务器资源参考

| 服务器 | CPU | 内存 | 磁盘 | 状态 |
|--------|-----|------|------|------|
| Vultr 45.76.212.254 | 1核 | 951Mi (44%) | 23G (90%🔴) | 仅 new-api 运行 |
| 阿里云 121.43.224.214 | - | 1.6GB (紧张) | - | BitHot + new-api |

> ⚠️ Vultr 磁盘 90% 已满，不建议立即部署套利机器人。
> 建议本地开发验证后，优先考虑阿里云或扩容。
