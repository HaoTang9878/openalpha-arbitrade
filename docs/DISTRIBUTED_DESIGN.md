# OpenAlpha 套利系统 — 分布式架构设计

## 目标

将单体套利引擎扩展为多节点分布式架构，支持水平扩展、高可用和故障隔离。

## 架构概览

```
                    [负载均衡器 / Cloudflare]
                           |
            ┌──────────────┼──────────────┐
            |              |              |
        [节点 A]        [节点 B]        [节点 C]
        扫描+检测       执行+风控      回测+监控
            |              |              |
        ┌───┴───┐      ┌───┴───┐     ┌───┴───┐
        | Redis |      | Redis |     | Redis |
        | 消息队列|      | 共享态 |     | 指标库 |
        └───────┘      └───────┘     └───────┘
            |              |              |
        [PostgreSQL 共享数据库]
            |
        [各交易所 API]
```

## 节点角色

### 节点 A: 扫描节点
- 运行 WebSocketScanner + REST 兜底
- 将价格快照写入 Redis pub/sub
- 不执行交易

### 节点 B: 执行节点
- 订阅 Redis 价格流
- 运行 ArbitrageDetector + RiskManager + Executor
- 持有 API Key，执行实盘交易
- 主备模式（active-standby）

### 节点 C: 监控节点
- 运行回测引擎 + AI Advisor
- Prometheus 指标采集
- 每日报告生成
- Telegram 告警

## 共享状态

### Redis（消息总线 + 共享状态）
- `prices:{exchange}:{symbol}` — 实时价格（TTL 10s）
- `opportunities` — 套利机会队列
- `trades` — 交易历史流
- `risk:status` — 风控状态
- `node:heartbeat:{node_id}` — 节点心跳（TTL 30s）

### PostgreSQL（持久化）
- trades 表 — 交易历史
- opportunities 表 — 机会快照
- nodes 表 — 节点注册表
- api_keys 表 — 加密的 API Key

## 实施步骤

### 阶段 1: Redis 消息总线（当前→P3）
- [ ] 安装 Redis
- [ ] scanner.publish_prices() 发布价格到 Redis
- [ ] detector.subscribe_prices() 从 Redis 订阅

### 阶段 2: 多节点分离
- [ ] Docker Compose 多服务定义
- [ ] 节点间心跳 + 健康检查
- [ ] 主备故障切换

### 阶段 3: 水平扩展
- [ ] 多扫描节点（按交易所分片）
- [ ] 多执行节点（锁竞争 + 幂等）
- [ ] 负载均衡策略

## 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 消息队列 | Redis Streams | 低延迟、内置消费者组 |
| 共享状态 | Redis Hash | 原子操作、TTL 支持 |
| 持久化 | PostgreSQL | 事务支持、JSON 字段 |
| 服务发现 | DNS + 健康检查 | 简单可靠 |
| 配置中心 | etcd / Consul | 动态配置 |

## 注意事项

1. **幂等性**: 执行节点必须对同一机会只执行一次（Redis 分布式锁）
2. **最终一致性**: 价格快照允许短暂延迟（< 1s）
3. **故障隔离**: 单节点故障不影响其他节点
4. **数据一致性**: 交易记录写入 PostgreSQL，Redis 仅做缓存
5. **安全**: API Key 仅存在执行节点，其他节点不可访问
