# BTC WhaleScope Agent

一个面向 BTC 巨鲸行为监控的自动化 Agent：
- 实时采集 CoinGlass 多源数据（CEX 大额单、清算、Hyperliquid、链上转账）
- 统一聚合、去重、规则告警、持久化
- 通过 Telegram Bot 提供订阅推送、数据查询、导出与 AI 分析
- 同时提供 HTTP + WebSocket 接口，方便二次集成

## 1. 当前版本能力（与代码一致）

### 数据采集
- `FuturesLargeOrderCollector`：CEX 合约大额限价单（默认阈值 `$500,000`）
- `SpotLargeOrderCollector`：CEX 现货大额限价单（默认阈值 `$500,000`）
- `LiquidationCollector`：清算订单（默认阈值 `$100,000`）
- `HyperliquidWhaleCollector`：Hyperliquid 鲸鱼仓位异动（BTC）
- `OnchainTransferCollector`：交易所链上转账（默认使用 `LARGE_ORDER_THRESHOLD`）
- `CoinGlassWSClient`：订阅 `liquidationOrders` / `tradeOrders`（当前实际消费 `liquidationOrders`）

### 引擎与告警
- `Aggregator` 负责：去重、入库、规则匹配、触发推送
- 默认告警规则（`src/engine/alert_rules.py`）：
  - `mega_whale`：`>= $5,000,000`
  - `large_cex_order`：CEX 大单 `>= $1,000,000`
  - `large_liquidation`：清算 `>= $500,000`
  - `hyperliquid_whale`：Hyperliquid `>= $1,000,000`
  - `large_onchain`：链上 `>= $10,000,000`

### Telegram Bot
- 用户命令：`/start` `/help` `/language` `/subscribe` `/status` `/stats`
- 任务命令：`/query` `/export` `/ask` `/buy` `/sell` `/positions` `/balance`
- 管理员命令：`/approve` `/revoke` `/users`
- 特性：
  - 邀请码激活（`/start Ocean1`）
  - 订阅交易所与阈值管理
  - 虚拟支付流程（演示账单，不真实扣款）
  - 导出 CSV + JSON（按交易所 + 时间范围）
  - AI 问答（DeepSeek）+ 对话历史记忆
  - 任务进度条（步骤化消息反馈）

### 对外接口
- REST API：`/health` `/api/orders` `/api/stats` `/api/config`
- WebSocket：`/ws`（服务端推送告警，客户端可 `ping`/`pong`）

---

## 2. 系统架构

```text
CoinGlass REST/WS ──> Collectors ──> Aggregator ──> SQLite
                               │            │
                               │            ├──> WebSocket Push (/ws)
                               │            ├──> Webhook Push
                               │            └──> Telegram Push Dispatcher
                               │
                               └──> AIAnalyzer (DeepSeek)

Telegram Bot <── UserDB(chat/users/subscription)
```

---

## 3. 项目结构

```text
.
├── config/
│   └── settings.py              # 全局配置（Pydantic Settings）
├── src/
│   ├── main.py                  # 主程序入口，组装所有组件
│   ├── server.py                # FastAPI 服务
│   ├── api/                     # CoinGlass REST / WS 客户端
│   ├── collectors/              # 各类采集器
│   ├── engine/                  # 聚合与告警规则
│   ├── ai/                      # DeepSeek 客户端与分析器
│   ├── storage/                 # 订单库 + 用户库
│   ├── telegram/                # Bot、对话、推送、进度管理
│   └── push/                    # Webhook、WS 推送、心跳上报
├── tests/
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── start.sh
```

---

## 4. 快速开始

### 4.1 环境要求
- Python 3.9+（推荐 3.11，与 Docker 一致）
- CoinGlass API Key（必填）
- Telegram Bot Token（启用 TG 时必填）
- DeepSeek API Key（启用 AI 时必填）

### 4.2 安装

```bash
git clone https://github.com/Oceanjackson1/BTC-WhaleScope-Agent.git
cd BTC-WhaleScope-Agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4.3 配置

```bash
cp .env.example .env
```

最小可运行配置（HTTP + 采集）：

```env
CG_API_KEY=your_coinglass_api_key
```

启用 Telegram + AI 需要：

```env
TG_ENABLED=true
TG_BOT_TOKEN=your_telegram_bot_token
TG_ADMIN_IDS=123456789
DEEPSEEK_API_KEY=your_deepseek_api_key
```

### 4.4 启动

```bash
python -m src.main
```

或：

```bash
bash start.sh
```

或 Docker：

```bash
docker compose up -d
```

---

## 5. 关键环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `CG_API_KEY` | CoinGlass API Key（必填） | 无 |
| `TG_ENABLED` | 是否启用 Telegram Bot | `false` |
| `TG_BOT_TOKEN` | Telegram Bot Token | 空 |
| `TG_ADMIN_IDS` | 管理员 ID（逗号分隔） | 空 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 空 |
| `DEEPSEEK_MODEL` | AI 模型 | `deepseek-chat` |
| `HOST` / `PORT` | FastAPI 监听地址 | `0.0.0.0:8000` |
| `DB_PATH` | 订单库路径 | `data/whale_orders.db` |
| `USER_DB_PATH` | 用户库路径 | `data/users.db` |
| `EXCHANGES` | 轮询交易所 | `Binance,OKX,Bybit` |
| `LARGE_ORDER_THRESHOLD` | 大单阈值（USD） | `500000` |
| `LIQUIDATION_THRESHOLD` | 清算阈值（USD） | `100000` |
| `WS_PUSH_ENABLED` | 是否启用 `/ws` 告警推送 | `true` |
| `WEBHOOK_PUSH_ENABLED` | 是否启用 Webhook 推送 | `false` |
| `WEBHOOK_URLS` | Webhook 地址（逗号分隔） | 空 |
| `HEARTBEAT_ENABLED` | Pixel Office 心跳上报 | `false` |

说明：`.env.example` 里的 Tencent COS 变量当前为预留配置，主流程尚未使用。

---

## 6. Telegram 使用说明

### 6.1 激活流程
1. 给 Bot 发送 `/start`
2. 使用邀请码激活：`/start Ocean1`
3. 或由管理员执行 `/approve <telegram_id>`

### 6.2 常用命令

| 命令 | 说明 |
|---|---|
| `/query [mode] [symbol]` | 查询订单数据（`large/onchain/spot/futures`，默认 `large BTC`） |
| `/export [symbol]` | 导出订单（先选交易所，再选 1d/7d/30d） |
| `/ask <问题>` | AI 分析（带聊天上下文） |
| `/subscribe` | 订阅交易所/阈值 |
| `/status` | 系统状态 |
| `/stats` | 个人统计 |

交易命令 `/buy` `/sell` `/positions` `/balance` 当前是演示流程，不会真实下单或扣款。

### 6.3 查询行为说明
- `/query onchain`、`/query spot` 若无数据，会回退到同币种最近巨鲸事件
- 受 CoinGlass 套餐影响，某些接口可能返回升级提示，采集器会自动暂停该源

---

## 7. HTTP / WS API

### 7.1 健康检查

```bash
curl http://127.0.0.1:8000/health
```

### 7.2 查询订单

```bash
curl "http://127.0.0.1:8000/api/orders?limit=50&exchange=Binance&min_amount=500000"
```

参数：
- `limit`：1-500
- `source`：`cex_futures | cex_spot | dex_hyperliquid | onchain`
- `exchange`：交易所名
- `min_amount`：最小金额（USD）

### 7.3 统计与配置

```bash
curl http://127.0.0.1:8000/api/stats
curl http://127.0.0.1:8000/api/config
```

### 7.4 WebSocket

```text
ws://127.0.0.1:8000/ws
```

- 连接成功会收到 `connected` 消息
- 告警消息类型为 `whale_alert`
- 客户端可发送 `ping`，服务端回复 `pong`

---

## 8. 数据存储

### 8.1 `whale_orders`（订单库）
核心字段：
- `id`（主键）
- `source` / `order_type`
- `exchange` / `symbol` / `side`
- `price` / `amount_usd` / `quantity`
- `timestamp` / `metadata`

### 8.2 `users` + `chat_history`（用户库）
- 用户状态、语言、订阅交易所、最小告警阈值
- 对话历史（用于 `/ask` 上下文）

---

## 9. 运行与运维

### 日志
- 默认控制台日志
- `docker-compose` 配置了日志轮转（20MB x 5）

### 心跳上报
启用 `HEARTBEAT_ENABLED=true` 后，会向 Supabase/Pixel Office 上报：
- `working`（运行中）
- `idle`（关闭）
- `thinking`（异常阶段）

### 安全建议
- 不要提交 `.env`
- 定期轮换 `CG_API_KEY`、`TG_BOT_TOKEN`、`DEEPSEEK_API_KEY`
- `TG_ADMIN_IDS` 只保留可信账号

---

## 10. 测试

```bash
# 基础系统测试（导入/配置检查）
python test_system.py

# 全量模块测试
python tests/test_all.py

# 数据质量测试（会访问真实 API）
python tests/test_data_quality.py
```

说明：`test_data_quality.py` 会请求线上数据并在桌面输出报告文件，请在可联网且密钥有效时运行。

---

## 11. 已知限制

- 当前聚焦 BTC 相关数据流，非 BTC 交易对支持有限
- 部分 CoinGlass 端点受套餐权限限制
- `/buy` `/sell` 等交易命令尚未接入真实执行通道
- Tencent COS 参数已预留，尚未纳入主流程

---

## 12. 免责声明

本项目仅用于数据监控与研究分析，不构成任何投资建议。数字资产交易风险高，请独立判断并自行承担风险。
