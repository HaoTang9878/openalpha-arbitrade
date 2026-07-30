# OpenAlpha 套利交易系统

加密货币跨交易所套利交易系统，基于 CCXT 库实现多交易所价格监控、套利机会检测和自动化交易执行。

## 功能特性

- **多交易所监控**：支持 8 个主流交易所（Binance、OKX、Bybit、Gate、KuCoin、Kraken、MEXC、HTX），默认启用前 6 个
- **WebSocket 实时扫描**：使用 WebSocket 实时订阅价格和 L2 订单簿数据，自动回退到 REST 轮询
- **套利检测引擎**：自动检测跨交易所价差，基于 L2 订单簿深度计算实际滑点，扣除手续费得到净利润率
- **策略框架**：内置三角套利、网格交易、DCA 定投等策略，支持策略调度器自动轮转
- **风控系统**：持仓限制、亏损熔断、交易次数限制、敞口限制四重风控
- **自动化交易**：支持模拟交易和实盘交易两种模式
- **React 监控仪表盘**：WebSocket 实时推送，可视化展示价格、机会、交易记录、热力图
- **用户认证**：JWT 用户登录注册，Bearer Token 管理鉴权
- **Telegram 告警**：机会检测、交易执行、系统异常自动推送
- **回测引擎**：历史 K 线数据下载、策略回测、参数扫描
- **Prometheus 监控**：/metrics 端点暴露系统运行指标
- **灵活配置**：支持环境变量、YAML 文件和 API 动态修改配置

## 项目结构

```
openalpha-arbitrage/
├── backend/
│   ├── __init__.py            # 包初始化
│   ├── app.py                 # FastAPI 主应用（REST API + WebSocket）
│   ├── scanner.py             # 多交易所价格扫描器（WebSocket + REST）
│   ├── arbitrage.py           # 套利检测引擎（L2 滑点计算）
│   ├── executor.py            # 交易执行器
│   ├── config.py              # 配置管理
│   ├── models.py              # 数据模型（Pydantic）
│   ├── auth.py                # 鉴权中间件（Bearer Token）
│   ├── user_auth.py           # 用户认证（JWT + PBKDF2 密码哈希）
│   ├── risk_manager.py        # 风控管理器
│   ├── notifier.py            # Telegram 告警通知器
│   ├── ai_advisor.py          # AI 策略推荐器
│   ├── database.py            # SQLite 持久化层
│   ├── rebalancer.py          # 库存再平衡（P3 预留）
│   ├── multi_account.py      # 多账户管理（P3 预留）
│   ├── strategies/
│   │   ├── __init__.py        # 策略导出
│   │   ├── base.py             # 策略基类
│   │   ├── grid.py             # 网格策略
│   │   ├── dca.py              # DCA 定投策略
│   │   ├── triangular.py       # 三角套利策略
│   │   └── funding_rate.py     # 资金费率套利策略
│   ├── backtest/
│   │   ├── __init__.py        # 回测模块导出
│   │   ├── engine.py          # 回测引擎 + 参数扫描
│   │   └── history.py         # 历史数据采集器
│   └── requirements.txt       # Python 依赖
├── frontend-react/            # React SPA 前端
│   ├── src/
│   │   ├── pages/             # 页面组件
│   │   ├── components/        # 通用组件
│   │   └── index.css          # 全局样式（OKLCH 色彩体系）
│   ├── dist/                  # 构建产物
│   └── package.json
├── .github/workflows/
│   └── ci.yml                 # GitHub Actions CI
├── data/                      # 数据目录（Docker 挂载）
├── .env.example               # 环境变量模板
├── Dockerfile                 # Docker 多阶段构建
├── docker-compose.yml         # Docker Compose 配置
└── README.md
```

## 快速开始

### Docker 部署（推荐）

```bash
# 复制环境变量模板并配置
cp .env.example .env
# 编辑 .env 填入 ARBITRAGE_API_TOKEN 和交易所 API 密钥

# 构建并启动
docker-compose up -d

# 查看日志
docker logs -f openalpha-arbitrage

# 停止
docker-compose down
```

访问 http://localhost:8070 即可打开监控仪表盘。

### 本地运行

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
uvicorn backend.app:app --host 0.0.0.0 --port 8070
```

### 前端开发

```bash
cd frontend-react
npm install
npm run dev    # 开发模式
npm run build  # 生产构建
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MIN_PROFITABILITY` | 最小净利润率 | 0.001 (0.1%) |
| `ORDER_AMOUNT` | 单笔下单量 | 0.01 |
| `SCAN_INTERVAL` | 扫描间隔（秒） | 3 |
| `MAX_ORDER_AGE` | 订单超时（秒） | 60 |
| `PAPER_TRADE` | 模拟交易模式 | true |
| `ARBITRAGE_API_TOKEN` | 管理令牌（写操作鉴权） | 无（拒绝写操作） |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 随机生成（重启失效） |
| `{EXCHANGE}_API_KEY` | 交易所 API Key | - |
| `{EXCHANGE}_API_SECRET` | 交易所 API Secret | - |
| `OKX_PASSPHRASE` | OKX 专用 Passphrase | - |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | - |
| `TELEGRAM_CHAT_ID` | Telegram 告警群组 ID | - |
| `TELEGRAM_MIN_PROFIT_ALERT` | 机会告警净利润率阈值 | 0.002 |
| `ARBITRAGE_API_BASE` | 前端 API 基础地址 | http://127.0.0.1:8070 |

### YAML 配置文件

在项目根目录创建 `config.yaml`：

```yaml
exchanges:
  - binance
  - okx
  - bybit
symbols:
  - BTC/USDT
  - ETH/USDT
min_profitability: 0.001
order_amount: 0.01
scan_interval: 3
max_order_age: 60
paper_trade: true
```

## API 接口

### REST API

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| GET | `/api/status` | 获取系统状态 | 公开 |
| GET | `/api/config` | 获取配置 | 公开 |
| PUT | `/api/config` | 修改配置 | Token |
| GET/PUT | `/api/symbols` | 交易对管理 | GET 公开 / PUT Token |
| GET | `/api/symbols/categories` | 币种分类表 | 公开 |
| POST | `/api/scanner/start` | 启动价格扫描 | Token |
| POST | `/api/scanner/stop` | 停止价格扫描 | Token |
| GET | `/api/prices` | 获取最新价格 | 公开 |
| GET | `/api/opportunities` | 获取套利机会 | 公开 |
| GET | `/api/opportunities/stats` | 机会聚合统计 | 公开 |
| POST | `/api/arbitrage/start` | 启动自动套利 | Token |
| POST | `/api/arbitrage/stop` | 停止自动套利 | Token |
| GET | `/api/trades` | 获取交易历史 | 公开 |
| POST | `/api/trades/execute` | 手动执行套利 | Token |
| GET | `/api/exchanges` | 获取交易所状态 | 公开 |
| GET | `/api/balances` | 查询账户余额 | 公开 |
| POST | `/api/keys` | 保存 API 密钥 | Token |
| DELETE | `/api/keys/{exchange}` | 删除 API 密钥 | Token |
| GET | `/api/risk/status` | 风控状态 | 公开 |
| POST | `/api/risk/resume` | 恢复风控 | Token |
| GET | `/api/daily-report` | 每日报告 | 公开 |
| GET | `/api/heatmap` | 价差热力图 | 公开 |
| GET/POST | `/api/strategies/*` | 策略管理 | GET 公开 / POST Token |
| GET/POST | `/api/backtest/*` | 回测引擎 | GET 公开 / POST Token |
| POST | `/api/auth/register` | 用户注册 | 公开 |
| POST | `/api/auth/login` | 用户登录 | 公开 |
| POST | `/api/auth/refresh` | 刷新 Token | 公开 |
| GET | `/api/auth/me` | 当前用户信息 | 公开 |
| GET | `/api/ai/recommend` | AI 策略推荐 | 公开 |
| GET | `/metrics` | Prometheus 指标 | 公开 |

### WebSocket

连接 `ws://localhost:8070/ws`，接收实时推送：

- `prices` - 价格更新
- `opportunities` - 套利机会
- `trade` - 交易结果
- `status` - 系统状态
- `logs` - 日志告警（WARNING+）

## 套利策略说明

### 检测逻辑

1. 对每个交易对，找出所有交易所中 **ask 最低**（买入最优）和 **bid 最高**（卖出最优）的交易所
2. 基于 L2 订单簿深度计算实际可成交量，得到实际滑点
3. 计算原始价差百分比：`(best_bid - best_ask) / best_ask`
4. 扣除双边手续费和滑点，得到净利润率
5. 过滤净利润率 < `min_profitability` 的机会
6. 按净利润率排序，返回 Top N 机会

### 风险评估

- **低风险**：价差 < 1% 且平均交易量 > 10 万 USDT
- **中风险**：价差 1% - 2%
- **高风险**：价差 > 2% 或交易量过低

### 风控限制

- 持仓数量限制（同时持仓上限）
- 日亏损熔断（超过阈值自动暂停）
- 日交易次数限制
- 单币种敞口限制

### 执行流程

1. 检查双边交易所余额是否充足
2. 在低价交易所提交买入限价单
3. 在高价交易所提交卖出限价单
4. 轮询订单状态，超时自动取消
5. 计算实际利润并记录

## 技术栈

- **后端**：Python 3.11 + FastAPI + CCXT 4.4.24 + asyncio + WebSocket
- **前端**：React + TypeScript + Vite
- **数据库**：SQLite（交易历史 + 套利机会 + K 线数据）
- **部署**：Docker + Docker Compose + Cloudflare Tunnel
- **CI/CD**：GitHub Actions
- **监控**：Prometheus /metrics 端点

## 安全提示

- 默认使用模拟交易模式（`paper_trade: true`），不会实际下单
- 切换到实盘交易前，请确保充分测试策略
- API 密钥通过环境变量或 config.yaml 传递，不会硬编码
- Docker 端口仅绑定到 `127.0.0.1`，不对外网暴露
- 写操作需 Bearer Token 鉴权，未配置 Token 时拒绝所有写操作（安全默认）
- 用户密码使用 PBKDF2-HMAC-SHA256 + 随机盐哈希存储
- JWT 密钥通过 `JWT_SECRET_KEY` 环境变量配置，未配置时生成随机密钥

## 许可证

MIT License
