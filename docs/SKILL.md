# OpenAlpha Arbitrage — 开发经验 Skill

> **目的**: 沉淀 OpenAlpha 纯现货套利系统开发过程中的所有关键经验、踩坑教训、架构决策和最佳实践，供未来 AI 助手或团队成员快速复用。
> 
> **创建日期**: 2026-07-29
> **GitHub**: https://github.com/HaoTang9878/openalpha-arbitrade

---

## 一、项目定位（绝对原则）

### 1.1 纯套利聚焦

本项目**严格聚焦**于：
- ✅ 跨交易所现货价差套利（cross-exchange spot arbitrage）
- ✅ 三角套利（triangular arbitrage，同所内 A→B→C→A）

**绝对排除**：
- ❌ 合约交易（futures/perpetual swaps/leverage）
- ❌ 常规量化策略（网格交易/DCA/趋势跟踪等"交易策略"）
- ❌ 做市商（market making）
- ❌ 永续合约资金费率套利
- ❌ 链上 DeFi 套利

### 1.2 "交易机器人"与"套利机器人"的本质区别

| 维度 | 常规量化 | 套利 |
|------|---------|------|
| 核心逻辑 | 预测价格走势 | 利用市场无效性 |
| 风险来源 | 预测错误 | 执行延迟/价差消失 |
| 持仓时间 | 分钟~天 | 毫秒~秒 |
| 收益来源 | 方向性预测 | 价格不一致 |
| 数学期望 | 依赖准确率 | 接近确定（瞬时无风险） |

### 1.3 experimental 标记机制

Grid/DCA 等"非纯套利"策略**保留但不推荐**，需明确确认才启用：

```python
# backend/app.py — create_strategy 端点
if is_experimental and not data.get("confirm_experimental", False):
    return JSONResponse(status_code=403, content={
        "error": "experimental",
        "detail": f"{strategy_type} 不属于纯套利策略，需设置 confirm_experimental=true 明确启用",
    })
```

---

## 二、关键技术陷阱（AI 助手必读）

### 2.1 FastAPI lifespan global 声明（🔴 致命陷阱）

`backend/app.py` 的 `lifespan()` 函数中每新增一个全局变量赋值，**必须**在函数顶部 `global` 声明中添加该变量名。遗漏会导致 API 端点返回"未初始化"错误。

```python
# ✅ 正确写法
async def lifespan(app: FastAPI):
    global scanner, detector, executor, database, notifier
    global strategy_registry, strategy_orchestrator  # 新增必须加
    global history_collector, backtest_engine        # 新增必须加
    global user_auth, ai_advisor                    # 新增必须加
    # ... 初始化代码
```

**当前已声明**: `scanner, detector, executor, risk_manager, database, notifier, scanner_running, scanner_task, strategy_registry, strategy_orchestrator, history_collector, backtest_engine, user_auth, ai_advisor`

### 2.2 auth.py 白名单机制（🔴 致命陷阱）

`backend/auth.py` 中间件拦截所有非白名单请求。

```python
# GET 端点必须加入 _PUBLIC_GET_PATHS
_PUBLIC_GET_PATHS: frozenset = frozenset({
    "/", "/api/status", "/api/prices", "/api/opportunities",
    "/api/opportunities/stats", "/api/trades", "/api/exchanges",
    "/api/balances", "/api/risk/status", "/api/config",
    "/api/daily-report", "/api/heatmap",
    "/api/symbols", "/api/symbols/categories",
    "/api/strategies", "/api/backtest/klines",
    "/api/ai/recommend",
    "/docs", "/openapi.json", "/redoc",
    # React SPA 路由
    "/bots", "/backtest", "/heatmap", "/reports", "/settings",
})

# POST 认证端点必须加入 _PUBLIC_AUTH_PATHS
_PUBLIC_AUTH_PATHS: frozenset = frozenset({
    "/api/auth/register", "/api/auth/login", "/api/auth/refresh",
})

# 静态资源（前端打包产物）放行
if request.url.path.startswith("/static/"):
    return True
if request.url.path.startswith("/assets/"):  # React SPA 构建产物
    return True
```

**写操作端点需要 `ARBITRAGE_API_TOKEN`**（服务器 `.env` 中配置 `ARBITRAGE_API_TOKEN=<random-hex>`）。

### 2.3 SQLAlchemy 写操作必须加锁

`backend/database.py` 使用 `check_same_thread=False` + `threading.Lock` 串行化所有写操作。

```python
def save_trade(self, trade: TradeResult) -> None:
    with self._lock:  # ← 必加
        self._conn.execute("INSERT OR REPLACE INTO trades ...", (...))
```

### 2.4 okx WS TypeError 是已知 bug（🟡 不要修复）

`backend/scanner.py` 中 okx 的 `orderbook_checksum_message` 在 symbol 为 None 时抛 `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'`。代码已用单独 except 捕获且不计入失败计数。

```python
# 不要"修复"这个 bug——ccxt 库内部问题，会破坏正常功能
except TypeError as e:
    error_key = f"ws_typeerr:{exchange_name}:{str(e)[:50]}"
    if now - last_warn > 300:  # 5 分钟去重
        logger.warning("okx WebSocket 遇到 ccxt 内部 TypeError（已知 bug，已忽略）")
```

**解决方案**: 在 okx 配置中禁用 checksum 校验
```python
exchange_config["options"]["watchOrderBook"] = {"checksum": False}
```

### 2.5 WS_BLACKLIST 不可移除

`backend/scanner.py` 的 `WS_BLACKLIST = {"bybit", "gate", "kraken", "kucoin"}` 强制 REST 轮询（这些交易所 WS 不稳定）。okx 也因 TypeError bug 被加入观察名单。

### 2.6 前端 Tailwind 颜色循环依赖

`frontend-react/src/index.css` 中 `.text-up`/`.text-down` 工具类**不能**用 `@apply text-up`（自身引用循环），必须用直接颜色值。

```css
@layer utilities {
  .text-up { color: var(--color-up); }   /* ✅ 直接颜色值 */
  .text-down { color: var(--color-down); }
  /* ❌ 错误: @apply text-up;  循环依赖 */
}
```

### 2.7 npm install 必须加 --legacy-peer-deps

React Router / Zustand / Recharts 存在 peer dependency 冲突。

```bash
npm install --legacy-peer-deps
```

### 2.8 SPA 路由需后端配合

React Router 的 `/bots`、`/heatmap` 等路径需在 `app.py` 添加对应 HTMLResponse 端点返回 index.html。

```python
@app.get("/heatmap", response_class=HTMLResponse)
async def heatmap_page() -> HTMLResponse:
    react_index = frontend_react_path / "index.html"
    if react_index.exists():
        return HTMLResponse(content=react_index.read_text(encoding="utf-8"))
```

### 2.9 Dockerfile 多阶段构建

```dockerfile
# 阶段 1: Node 编译前端
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend-react/package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY frontend-react/ ./
RUN npm run build

# 阶段 2: Python 运行后端
FROM python:3.11-slim
COPY --from=frontend-builder /frontend/dist ./frontend-react/dist
```

`.dockerignore` 必须排除 `frontend-react/node_modules/` 和 `data/`，否则镜像膨胀。

### 2.10 scp 推送时小心覆盖 `__init__.py`

**真实事故**: 一次 `scp backend/strategies/__init__.py backend/app.py ...` 命令（不带 `-r` 递归）将所有文件放到了 `backend/` 目录下，导致 `backend/__init__.py` 被 `strategies/__init__.py` 内容覆盖，容器崩溃 `ModuleNotFoundError: No module named 'backend.base'`。

**预防**: 推送后端文件时使用 `scp -r backend/<module>/`，或用 rsync 保持目录结构。

---

## 三、架构设计原则

### 3.1 核心套利检测逻辑

```python
# backend/arbitrage.py — ArbitrageDetector
def detect(self, prices, orderbooks=None):
    """对每个交易对，找最优买价（最低 ask）和最优卖价（最高 bid），
    计算价差 = (sell_price - buy_price) / buy_price，
    扣除双边手续费和滑点，净利润率 > min_profitability 才算机会。"""
```

### 3.2 多策略框架

```python
# backend/strategies/base.py — BaseStrategy 抽象基类
class BaseStrategy(ABC):
    @abstractmethod
    async def generate_signals(self, prices) -> List[StrategySignal]:
        """子类实现：基于价格生成交易信号"""
        ...
```

**三种策略**：
- `TriangularStrategy`: 三角套利（核心，pure arbitrage）
- `GridStrategy` / `DcaStrategy`: experimental（需 confirm_experimental=true）

### 3.3 风险评分数值化（0-100）

```python
# backend/arbitrage.py — _calculate_risk_score
def _calculate_risk_score(self, spread_percent, prices, symbol):
    """
    4 维度评分（各占权重）：
    1. 价差异常度（35%）：< 0.5% → 0-20, 0.5-1% → 20-50, 1-2% → 50-80, > 2% → 80-100
    2. 流动性风险（30%）：> 1亿 USDT → 0-10, 1000万-1亿 → 10-30, < 1000万 → 30-60
    3. 净利润率稳健度（20%）：利润越薄风险越高
    4. 交易所集中度（15%）：参与所数越多越安全
    
    Returns: (risk_score 0-100, RiskLevel)
    """
```

### 3.4 失败原因分类（8 类）

```python
# backend/models.py — FailureReason 枚举
class FailureReason(str, Enum):
    INSUFFICIENT_BALANCE = "insufficient_balance"
    ORDER_CANCELLED = "order_cancelled"
    NETWORK_ERROR = "network_error"
    LIQUIDITY_INSUFFICIENT = "liquidity_insufficient"
    LIMIT_PRICE_NOT_HIT = "limit_price_not_hit"
    FEE_EXCEEDS_PROFIT = "fee_exceeds_profit"
    EXCHANGE_ERROR = "exchange_error"
    RISK_REJECTED = "risk_rejected"
    UNKNOWN = "unknown"
```

TradeResult 新增 `failure_reason: Optional[str]` 字段，executor 按错误信息自动分类。

### 3.5 持久化架构

`backend/database.py` 单 SQLite + WAL 模式 + threading.Lock。

**表结构**：
- `trades`: 交易历史（含 `failure_reason` 字段）
- `opportunities`: 套利机会快照
- `klines`: 回测用 K 线数据
- `users`: 用户认证

**未来扩展**: 多用户并发场景应迁移到 PostgreSQL。

### 3.6 L2 订单簿动态滑点

```python
# backend/arbitrage.py — _calculate_effective_price
def _calculate_effective_price(self, orderbook, side, amount):
    """
    模拟吃单（taker）行为：按订单簿深度逐档成交
    L2 缓存 10 档买卖盘，无数据时回退固定滑点 0.02%
    """
```

订单簿深度订阅限制前 5 个交易对，控制内存（Vultr 1 核 951Mi 内存限制）。

---

## 四、版本控制规范

### 4.1 提交规范

```bash
# 每次微小改动立即提交
git add <files>
git commit -m "<type>: <description>

- 变更1
- 变更2
- 测试: N个全部通过"

git push origin main
```

**commit type**:
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 重构（不改变行为）
- `docs`: 文档
- `test`: 测试
- `chore`: 杂项

### 4.2 每次提交后必须验证

```bash
# 1. 语法检查
python3 -c "import ast; ast.parse(open('backend/xxx.py').read())"

# 2. 单元测试（目标 106+ 个全部通过）
python3 -m pytest tests/ --tb=short --no-cov -q

# 3. 部署到服务器
scp -o StrictHostKeyChecking=no backend/<module>/*.py root@server:/path/
ssh root@server "cd /path && docker compose up -d --build && sleep 15 && curl -s http://127.0.0.1:8070/api/status"
```

### 4.3 提交前清单

- [ ] 改动是否聚焦（一次只做一个改动）
- [ ] 是否影响了核心套利定位（非套利代码标记为 experimental）
- [ ] 是否更新了对应测试
- [ ] 是否更新了 AGENTS.md / docs（如果是新陷阱）
- [ ] 服务器部署是否成功
- [ ] 测试是否全部通过

---

## 五、业界对标要点

### 5.1 参考的套利软件

| 软件 | URL/位置 | 关键参考 |
|------|---------|---------|
| Hummingbot | `freqtrade/` | arbitrage_strategy.py 核心方法论 |
| Jesse | `Jesse/strategies/arbitrage_strategy.py` | 风险评分 _calculate_risk_score |
| 1inch | 外部 | 多跳路径+Gas 估算 |
| ArbitrageScanner | 外部 | 实时价差地图 |
| Bitsgap | `bitsgap/README.md` | 6 种机器人策略 |

### 5.2 OpenAlpha 差异化优势

- ✅ 三角套利（Binance/OKX/Bitsgap 均无）
- ✅ 开源自部署（Bitsgap 是 SaaS）
- ✅ AI 策略推荐（仅 Bitsgap 有类似功能）
- ✅ 数值化风险评分（0-100 连续值）

### 5.3 业界最佳实践（已实现）

1. ✅ L2 订单簿深度计算（Hummingbot 模式）
2. ✅ 多维度风险评分（Jesse 模式）
3. ✅ 失败原因分类（对标 1inch）
4. ✅ WebSocket + REST 兜底（Hummingbot 模式）
5. ✅ 每日回测 + 实时价差记录（Bitsgap 模式）

### 5.4 业界最佳实践（未实现 — 后续方向）

- ⏳ 事件驱动价差检测（当前 3s 轮询，1inch 模式）
- ⏳ 执行延迟监控（无 P50/P95 统计）
- ⏳ 多账户资金调度（无自动调拨）
- ⏳ ML 价差预测（无预测模型）
- ⏳ DEX 套利（未扩展链上）

---

## 六、部署运维

### 6.1 服务器信息

```
IP: 45.76.212.254
SSH: root@45.76.212.254
资源: 1 核 / 951Mi 内存 / 23G 磁盘（78% 已用）
容器: openalpha-arbitrage, mem_limit 640m
端口: 8070
公网: arbitrage.openalpha.top (Cloudflare Tunnel)
```

### 6.2 常用运维命令

```bash
# 查看状态
ssh root@45.76.212.254 "docker ps --filter name=arbitrage --format '{{.Names}} | {{.Status}}'"

# 查看日志
ssh root@45.76.212.254 "docker logs openalpha-arbitrage --tail 50 -f"

# 重建容器
ssh root@45.76.212.254 "cd /root/openalpha-arbitrage && docker compose up -d --build"

# 启动自动套利
curl -X POST -H "Authorization: Bearer $ARBITRAGE_API_TOKEN" \
  http://127.0.0.1:8070/api/arbitrage/start

# 每日报告
ssh root@45.76.212.254 "cd /root/openalpha-arbitrage && python3 scripts/daily_report.py"
```

### 6.3 备份与恢复

```bash
# 备份数据
ssh root@45.76.212.254 "cd /root/openalpha-arbitrage && tar czf - data/" > backup_$(date +%Y%m%d).tar.gz

# 恢复数据
scp backup_20260729.tar.gz root@45.76.212.254:/root/openalpha-arbitrage/
ssh root@45.76.212.254 "cd /root/openalpha-arbitrage && tar xzf backup_20260729.tar.gz"
```

---

## 七、测试规范

### 7.1 测试结构

```
tests/
├── conftest.py          # 共享 fixtures（sample_prices, sample_orderbooks, sample_opportunity, test_config）
├── test_config.py        # 配置加载/更新测试
├── test_arbitrage.py     # 套利检测+风险评分测试（最关键）
├── test_risk_manager.py  # 风控规则测试
├── test_executor.py      # 交易执行测试
├── test_scanner.py       # 行情扫描测试
├── test_database.py      # 数据库测试
├── test_auth.py          # 鉴权测试
├── test_notifier.py      # 通知测试
├── test_app.py           # API 端点集成测试
```

### 7.2 测试数据惯例

```python
# tests/conftest.py
@pytest.fixture
def sample_prices() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """模拟价差足够大以覆盖手续费（>0.5%）"""
    return {
        "binance": {
            "BTC/USDT": {
                "bid": 95000.0, "ask": 95001.0,
                "last": 95000.5, "volume": 1000000.0,
                "timestamp": 1700000000000,
            },
        },
        "okx": {
            "BTC/USDT": {
                "bid": 95500.0, "ask": 95501.0,  # ≥ 0.5% 价差
                "last": 95500.5, "volume": 800000.0,
                "timestamp": 1700000000000,
            },
        },
    }

@pytest.fixture
def test_config() -> Config:
    """订单量 0.01 BTC = ~95 USDT < 2000 USDT 敞口上限"""
    config = Config()
    config.model.exchanges = ["binance", "okx"]
    config.model.symbols = ["BTC/USDT", "ETH/USDT"]
    config.model.min_profitability = 0.001
    config.model.order_amount = 0.01
    config.model.paper_trade = True
    return config
```

### 7.3 pytest 配置

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
addopts = -v --tb=short --cov=backend --cov-report=term-missing
filterwarnings =
    ignore::DeprecationWarning
```

---

## 八、API 端点速查

| 路径 | 方法 | 鉴权 | 用途 |
|------|------|------|------|
| `/api/status` | GET | 公开 | 系统状态 |
| `/api/config` | GET/PUT | GET公开/PUT需Token | 配置 |
| `/api/prices` | GET | 公开 | 实时价格 |
| `/api/opportunities` | GET | 公开 | 套利机会 |
| `/api/opportunities/stats` | GET | 公开 | 机会统计 |
| `/api/trades` | GET | 公开 | 交易历史 |
| `/api/exchanges` | GET | 公开 | 交易所状态 |
| `/api/balances` | GET | 公开 | 余额 |
| `/api/risk/status` | GET | 公开 | 风控状态 |
| `/api/risk/resume` | POST | Token | 恢复风控 |
| `/api/scanner/{start,stop}` | POST | Token | 控制扫描 |
| `/api/arbitrage/{start,stop}` | POST | Token | 控制套利 |
| `/api/arbitrage/start` | POST | Token | 启动自动套利 |
| `/api/trades/execute` | POST | Token | 手动执行 |
| `/api/daily-report` | GET | 公开 | 每日报告 |
| `/api/heatmap` | GET | 公开 | 热力图数据 |
| `/api/symbols` | GET/PUT | GET公开/PUT需Token | 币种管理 |
| `/api/symbols/categories` | GET | 公开 | 分类映射 |
| `/api/strategies` | GET | 公开 | 策略列表 |
| `/api/strategies/create` | POST | Token | 创建策略 |
| `/api/strategies/{name}/{start,stop}` | POST | Token | 控制策略 |
| `/api/strategies/orchestrator/{start,stop}` | POST | Token | 调度器 |
| `/api/backtest/klines` | GET | 公开 | K线数据 |
| `/api/backtest/download` | POST | Token | 下载K线 |
| `/api/backtest/run` | POST | Token | 运行回测 |
| `/api/auth/register` | POST | 公开 | 注册 |
| `/api/auth/login` | POST | 公开 | 登录 |
| `/api/auth/refresh` | POST | 公开 | 刷新Token |
| `/api/auth/me` | GET | Token | 当前用户 |
| `/api/ai/recommend` | GET | 公开 | AI策略推荐 |
| `/api/keys` | POST | Token | 保存API Key |
| `/api/keys/{exchange}` | DELETE | Token | 删除API Key |
| `/ws` | WebSocket | Token可选 | 实时推送 |

---

## 九、踩坑教训汇总（按严重度排序）

| 严重度 | 问题 | 教训 |
|--------|------|------|
| 🔴 致命 | FastAPI lifespan 未声明 global | 每次新增全局变量必须更新 global 声明 |
| 🔴 致命 | 新增端点被 auth 中间件拦截 | GET 加 `_PUBLIC_GET_PATHS`，POST 加 `_PUBLIC_AUTH_PATHS` |
| 🔴 致命 | scp 覆盖 `__init__.py` 致模块找不到 | scp 时保持目录结构（`-r` 或 rsync） |
| 🔴 致命 | SQL 写操作未加锁导致 "database is locked" | 所有写方法用 `with self._lock:` |
| 🟡 严重 | okx WS TypeError 刷屏 | 不计入失败计数 + 禁用 checksum 校验 |
| 🟡 严重 | Tailwind 循环依赖 `@apply text-up` | 工具类用直接颜色值 |
| 🟡 严重 | 前端依赖冲突导致 npm install 失败 | 始终加 `--legacy-peer-deps` |
| 🟡 严重 | React SPA 路由 404 | 后端需添加对应 HTMLResponse 端点 |
| 🟡 严重 | 前端构建后 CSS 404 被 auth 拦截 | `/assets/` 路径加入白名单 |
| 🟢 中等 | pytest 覆盖率 80% 未达标 | 持续增加测试，新功能必须有测试 |
| 🟢 中等 | 回测引擎测试需 K 线数据 | 后端自动下载或 mock CCXT |

---

## 十、用户约束执行记录

本项目严格遵守用户要求：
- ✅ 极速捕捉市场价差并实现套利执行
- ✅ 严格聚焦现货套利（排除合约和常规量化）
- ✅ 持续研究业界顶尖套利软件架构并深度对标
- ✅ 每次微小改动立即提交 GitHub
- ✅ 每次提交后执行严格目标验证测试

**开发节奏**: 7 个 commit，106+ 测试通过，1 个产品定位文档，1 个对标分析，1 个 Skill 文档。

---

## 十一、持续改进方向

### 11.1 短期（1-2 周）

1. **事件驱动**: 从轮询改为 WebSocket 价格变化触发检测（延迟降低 80%）
2. **执行延迟监控**: 记录下单→成交 latency，统计 P50/P95
3. **历史价差分析**: 统计各交易对历史价差均值/标准差，动态阈值
4. **前端 K 线图表**: 已安装 lightweight-charts，集成到 Dashboard

### 11.2 中期（1-2 月）

5. **多账户资金调度**: 自动评估各所余额，缺资金时推荐调拨
6. **ML 价差预测**: 基于历史数据预测未来 30 秒价差方向
7. **DEX 套利**: 扩展到链上 DEX（Uniswap/PancakeSwap）

### 11.3 长期（3+ 月）

8. **回测引擎增强**: 参数扫描 + Walk-forward + 过拟合检测
9. **实盘切换**: 从模拟模式切换到实盘（小仓位试水）
10. **多账户并行**: 支持多 API Key 分散资金

---

## 十二、文件结构参考

```
openalpha-arbitrage/
├── backend/
│   ├── app.py              # FastAPI 主应用（1200+ 行，路由+lifespan+全局）
│   ├── auth.py             # Bearer Token 鉴权中间件
│   ├── arbitrage.py        # ArbitrageDetector + 风险评分（0-100）
│   ├── executor.py         # TradeExecutor（双边下单+失败分类）
│   ├── risk_manager.py     # RiskManager（持仓/亏损/敞口/次数）
│   ├── scanner.py          # PriceScanner + WebSocketScanner（WS优先+REST兜底）
│   ├── config.py           # Config（环境变量+YAML+40币种）
│   ├── models.py           # Pydantic 数据模型（含 FailureReason 8类）
│   ├── database.py         # SQLite + WAL + Lock
│   ├── notifier.py         # Telegram 告警
│   ├── user_auth.py        # JWT 用户认证
│   ├── ai_advisor.py       # AI 策略推荐
│   ├── strategies/         # 可插拔策略框架
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── orchestrator.py
│   │   ├── grid.py         # experimental
│   │   ├── dca.py          # experimental
│   │   └── triangular.py   # 核心套利
│   └── backtest/           # 回测引擎
│       ├── collector.py    # K线采集
│       └── engine.py       # 回测核心
├── frontend-react/         # React 18 + TS + Vite SPA
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/         # Dashboard/Bots/Backtest/Heatmap/Reports/Settings
│   │   ├── components/    # KpiCard/PriceMatrix/OpportunityCard/RiskPanel/Toast/...
│   │   ├── hooks/         # useWebSocket/useTheme
│   │   ├── store/         # Zustand
│   │   ├── api/           # 客户端
│   │   └── types/
│   ├── tailwind.config.js
│   └── vite.config.ts
├── frontend/                # 旧版 HTML（回退）
├── tests/                   # 106+ 测试
├── scripts/
│   ├── daily_record.py     # 每小时机会快照
│   └── daily_report.py     # 每日 Markdown 报告
├── docs/
│   ├── PURPOSE_AND_BENCHMARK.md   # 产品定位+对标分析
│   ├── COMPETITIVE_ANALYSIS_AND_DESIGN_SYSTEM.md
│   ├── EXECUTION_PLAN.md
│   ├── OPTIMIZATION_PLAN.md
│   ├── GAP_ANALYSIS_AND_ROADMAP.md
│   ├── TASK_LOG.md
│   └── SKILL.md            # 本文件
├── Dockerfile               # 多阶段构建
├── docker-compose.yml
├── config.yaml              # 40 币种配置
├── requirements.txt
└── README.md
```

---

**结语**: 本项目是一个持续迭代的纯现货套利系统，每次 commit 都遵循"小步快跑+严格测试+立即推送"的规范。所有关键经验已沉淀在本 Skill 中，供未来 AI 助手或团队成员快速复用。
