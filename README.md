# OpenAlpha 套利交易系统

加密货币跨交易所套利交易系统，基于 CCXT 库实现多交易所价格监控、套利机会检测和自动化交易执行。

## 功能特性

- **多交易所监控**：支持 12 个主流交易所（Binance、OKX、Bybit、Gate、KuCoin、Kraken、Coinbase、Bitfinex、MEXC、Huobi、Poloniex、Gemini）
- **实时价格扫描**：使用 CCXT 异步接口并发获取所有交易所的价格数据
- **套利检测引擎**：自动检测跨交易所价差，计算净利润率（扣除手续费和滑点）
- **自动化交易**：支持模拟交易和实盘交易两种模式
- **实时监控仪表盘**：WebSocket 实时推送，可视化展示价格、机会和交易记录
- **灵活配置**：支持环境变量、YAML 文件和 API 动态修改配置

## 项目结构

```
openalpha-arbitrage/
├── backend/
│   ├── __init__.py        # 包初始化
│   ├── app.py             # FastAPI 主应用（REST API + WebSocket）
│   ├── scanner.py         # 多交易所价格扫描器（CCXT）
│   ├── arbitrage.py       # 套利检测引擎
│   ├── executor.py        # 交易执行器
│   ├── config.py          # 配置管理
│   ├── models.py          # 数据模型（Pydantic）
│   └── requirements.txt   # Python 依赖
├── frontend/
│   └── index.html         # 实时监控仪表盘
├── data/                  # 数据目录（Docker 挂载）
├── Dockerfile             # Docker 构建文件
├── docker-compose.yml     # Docker Compose 配置
└── README.md              # 项目说明
```

## 快速开始

### Docker 部署（推荐）

```bash
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
# 安装依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
uvicorn backend.app:app --host 0.0.0.0 --port 8070
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MIN_PROFITABILITY` | 最小净利润率 | 0.003 (0.3%) |
| `ORDER_AMOUNT` | 单笔下单量 | 0.01 |
| `SCAN_INTERVAL` | 扫描间隔（秒） | 10 |
| `MAX_ORDER_AGE` | 订单超时（秒） | 180 |
| `PAPER_TRADE` | 模拟交易模式 | true |
| `{EXCHANGE}_API_KEY` | 交易所 API Key | - |
| `{EXCHANGE}_API_SECRET` | 交易所 API Secret | - |

### YAML 配置文件

在项目根目录创建 `config.yaml`：

```yaml
exchanges:
  - binance
  - okx
symbols:
  - BTC/USDT
  - ETH/USDT
min_profitability: 0.005
order_amount: 0.01
scan_interval: 10
paper_trade: true
```

## API 接口

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 获取系统状态 |
| GET | `/api/config` | 获取配置 |
| PUT | `/api/config` | 修改配置 |
| POST | `/api/scanner/start` | 启动价格扫描 |
| POST | `/api/scanner/stop` | 停止价格扫描 |
| GET | `/api/prices` | 获取最新价格 |
| GET | `/api/opportunities` | 获取套利机会 |
| POST | `/api/arbitrage/start` | 启动自动套利 |
| POST | `/api/arbitrage/stop` | 停止自动套利 |
| GET | `/api/trades` | 获取交易历史 |
| POST | `/api/trades/execute` | 手动执行套利 |
| GET | `/api/exchanges` | 获取交易所状态 |

### WebSocket

连接 `ws://localhost:8070/ws`，接收实时推送：

- `prices` - 价格更新
- `opportunities` - 套利机会
- `trade` - 交易结果
- `status` - 系统状态

## 套利策略说明

### 检测逻辑

1. 对每个交易对，找出所有交易所中 **ask 最低**（买入最优）和 **bid 最高**（卖出最优）的交易所
2. 计算原始价差百分比：`(best_bid - best_ask) / best_ask`
3. 扣除双边手续费和估算滑点，得到净利润率
4. 过滤净利润率 < `min_profitability` 的机会
5. 按净利润率排序，返回 Top N 机会

### 风险评估

- **低风险**：价差 < 1% 且平均交易量 > 10 万 USDT
- **中风险**：价差 1% - 2%
- **高风险**：价差 > 2% 或交易量过低

### 执行流程

1. 检查双边交易所余额是否充足
2. 在低价交易所提交买入限价单
3. 在高价交易所提交卖出限价单
4. 轮询订单状态，超时自动取消
5. 计算实际利润并记录

## 技术栈

- **后端**：Python 3.11 + FastAPI + CCXT + asyncio
- **前端**：原生 HTML/CSS/JavaScript + WebSocket
- **部署**：Docker + Docker Compose
- **依赖版本**：所有依赖版本固定，避免兼容性问题

## 安全提示

- 默认使用模拟交易模式（`paper_trade: true`），不会实际下单
- 切换到实盘交易前，请确保充分测试策略
- API 密钥通过环境变量传递，不会硬编码在配置文件中
- Docker 端口仅绑定到 `127.0.0.1`，不对外网暴露

## 许可证

MIT License
