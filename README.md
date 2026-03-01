# 🐳 BTC WhaleScope Agent

<div align="center">

**实时 BTC 巨鲸订单监控 & AI 分析 Telegram 机器人**

[![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)](https://python.org)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![DeepSeek AI](https://img.shields.io/badge/DeepSeek-AI-FF6B35?logo=openai&logoColor=white)](https://deepseek.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 📖 项目简介

BTC WhaleScope Agent 是一个**全自动化的加密货币巨鲸订单监控系统**，集实时数据采集、智能告警、AI 分析和 Telegram 交互于一体。系统通过多源数据采集器实时追踪 BTC 巨鲸动向，并通过 Telegram Bot 为用户提供专业级的市场洞察服务。

### 🎯 核心能力

- **🔍 多交易所实时监控** — 支持 Binance、OKX、Bybit、Hyperliquid 等主流交易所的巨鲸订单追踪
- **📡 WebSocket + REST 双通道** — CoinGlass API 实时推送 + 轮询双保障
- **🤖 AI 深度分析** — 接入 DeepSeek 大模型，基于实时巨鲸数据提供专业市场分析
- **💬 Telegram Bot 交互** — 完整的机器人交互体系，支持中英双语
- **📥 数据导出** — 一键导出 CSV + JSON 格式巨鲸订单数据，支持按交易所筛选
- **🧠 对话记忆** — AI 分析支持多轮对话记忆，追问可引用上下文

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────┐
│                    Telegram Bot 交互层                     │
│  /start · /export · /ask · /query · /lang · /help        │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│                     引擎层 (Engine)                        │
│  Aggregator（聚合器）· AlertRules（告警规则）               │
│  AIAnalyzer（AI 分析器）· DialogHandler（对话处理）         │
└──────┬──────────────────┬──────────────────┬─────────────┘
       │                  │                  │
┌──────▼──────┐  ┌────────▼────────┐  ┌─────▼─────────────┐
│  数据采集器   │  │   存储层         │  │   推送层           │
│             │  │                 │  │                   │
│ • 大额限价单 │  │ • whale_orders  │  │ • Telegram Push   │
│ • 清算订单   │  │ • users         │  │ • WebSocket       │
│ • Hyperliquid│  │ • chat_history  │  │ • Webhook         │
│ • 链上转账   │  │   (SQLite)      │  │                   │
└──────┬──────┘  └─────────────────┘  └───────────────────┘
       │
┌──────▼────────────────────────────────────────────────────┐
│                    外部 API 层                             │
│  CoinGlass REST · CoinGlass WebSocket · DeepSeek AI       │
└───────────────────────────────────────────────────────────┘
```

---

## 📂 项目结构

```
BTC-WhaleScope-Agent/
├── config/
│   ├── __init__.py
│   └── settings.py              # 全局配置（Pydantic Settings）
├── src/
│   ├── main.py                  # 主入口，初始化所有组件
│   ├── server.py                # FastAPI 服务器
│   ├── ai/
│   │   ├── analyzer.py          # AI 分析器封装
│   │   └── deepseek_client.py   # DeepSeek API 客户端
│   ├── api/
│   │   ├── coinglass_client.py  # CoinGlass REST 客户端
│   │   └── coinglass_ws.py      # CoinGlass WebSocket 客户端
│   ├── collectors/
│   │   ├── base.py              # 采集器基类（轮询 + 去重）
│   │   ├── hyperliquid.py       # Hyperliquid 巨鲸追踪
│   │   ├── large_order.py       # 大额限价单采集
│   │   ├── liquidation.py       # 清算订单采集
│   │   └── onchain.py           # 链上大额转账
│   ├── engine/
│   │   ├── aggregator.py        # 订单聚合 + AI 分析
│   │   └── alert_rules.py       # 告警规则判定
│   ├── models/
│   │   ├── user.py              # 用户 & 聊天记录模型
│   │   └── whale_order.py       # 巨鲸订单模型
│   ├── push/
│   │   ├── webhook.py           # Webhook 推送
│   │   └── websocket_server.py  # WebSocket 实时推送
│   ├── storage/
│   │   ├── database.py          # 订单数据库（SQLite）
│   │   └── user_database.py     # 用户数据库 + 聊天历史
│   └── telegram/
│       ├── bot.py               # Telegram Bot 主逻辑
│       ├── dialog_handler.py    # 自然语言对话处理
│       ├── message_formatter.py # 告警消息格式化
│       ├── push_dispatcher.py   # 推送调度器
│       └── user_manager.py      # 用户管理（邀请码 + 权限）
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
├── Dockerfile                   # Docker 容器构建
├── docker-compose.yml           # Docker Compose 编排
└── start.sh                     # 启动脚本
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.9+
- Telegram Bot Token（通过 [@BotFather](https://t.me/BotFather) 创建）
- CoinGlass API Key（[申请地址](https://www.coinglass.com/pricing)）
- DeepSeek API Key（[申请地址](https://platform.deepseek.com/)）

### 2. 安装部署

```bash
# 克隆项目
git clone https://github.com/Oceanjackson1/BTC-WhaleScope-Agent.git
cd BTC-WhaleScope-Agent

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填入你的 API 密钥
```

#### 必填配置项：

| 变量 | 说明 | 示例 |
|------|------|------|
| `CG_API_KEY` | CoinGlass API 密钥 | `your_coinglass_api_key` |
| `TG_BOT_TOKEN` | Telegram Bot Token | `123456:ABC-DEF...` |
| `TG_ADMIN_IDS` | 管理员 Telegram ID | `123456789` |
| `DEEPSEEK_API_KEY` | DeepSeek AI 密钥 | `sk-your_deepseek_key` |
| `TG_ENABLED` | 启用 Telegram Bot | `true` |

#### 可选：Pixel Office 心跳监控

| 变量 | 说明 | 示例 |
|------|------|------|
| `HEARTBEAT_ENABLED` | 是否启用心跳上报 | `true` |
| `HEARTBEAT_URL` | Supabase REST upsert 地址 | `https://.../rest/v1/agents` |
| `HEARTBEAT_API_KEY` | Supabase publishable key | `sb_publishable_xxx` |
| `HEARTBEAT_BEARER_TOKEN` | Bearer Token，默认可与 API Key 相同 | `sb_publishable_xxx` |
| `HEARTBEAT_AGENT_ID` | Agent 固定唯一 ID | `codex-btc-whalescope-01` |
| `HEARTBEAT_NAME` | 大屏显示名称 | `BTC WhaleScope Agent` |
| `HEARTBEAT_ROLE` | 角色标签 | `product` |
| `HEARTBEAT_ROLE_LABEL_ZH` | 中文头衔 | `BTC巨鲸情报分析师` |

### 4. 启动服务

```bash
# 直接启动
python -m src.main

# 或使用启动脚本
chmod +x start.sh && ./start.sh

# Docker 方式
docker-compose up -d
```

---

## 🤖 Telegram Bot 使用指南

### 首次使用

1. 在 Telegram 搜索你的 Bot 并点击 **Start**
2. 输入邀请码激活账户：`/start Ocean1`
3. 激活后即可使用所有功能

### 命令列表

| 命令 | 功能 | 费用 |
|------|------|------|
| `/export <币种>` | 导出巨鲸订单数据（CSV + JSON） | $0.50 |
| `/ask <问题>` | AI 深度分析（支持多轮对话） | $1.00 |
| `/query` | 实时数据查询 | $0.20 |
| `/buy` | 跟单买入 | $1.00 |
| `/sell` | 跟单卖出 | $1.00 |
| `/positions` | 查询持仓 | $0.30 |
| `/balance` | 查询余额 | $0.10 |
| `/lang` | 切换语言（中/英） | - |
| `/help` | 帮助信息 | - |

> **注**: 费用为展示定价，当前版本未实际收费。

### 数据导出功能

```
用户: /export BTC
Bot:  📥 导出 BTC 巨鲸订单
      请选择您想导出的交易所：
      [Hyperliquid] [Binance]
      [OKX]         [🌐 全部交易所]

用户: (点击 Hyperliquid)
Bot:  ✅ 找到 78 条记录，发送中...
      📎 whale_orders_BTC_Hyperliquid_20260227.csv
      📎 whale_orders_BTC_Hyperliquid_20260227.json
```

### AI 分析功能（支持多轮对话记忆）

```
用户: /ask BTC巨鲸最近的买卖趋势是什么？
Bot:  🤖 AI Analysis
      根据过去1小时数据，BTC巨鲸活动呈现净卖出倾向...

用户: /ask 买方力量怎么样？有没有反转信号？
Bot:  🤖 AI Analysis
      (引用上一轮分析) 买方支撑目前较弱...
```

---

## 📊 数据采集源

| 采集器 | 数据来源 | 采集方式 | 默认间隔 |
|--------|---------|---------|---------|
| `large_order` | CoinGlass 大额限价单 | REST 轮询 | 10s |
| `liquidation` | CoinGlass 清算订单 | REST 轮询 | 10s |
| `hyperliquid` | Hyperliquid 巨鲸动向 | REST 轮询 | 10s |
| `onchain` | 链上大额转账 | REST 轮询 | 60s |
| `coinglass_ws` | CoinGlass WebSocket | 实时推送 | 实时 |

### 告警阈值

- **大额订单**: ≥ $500,000 USD
- **清算订单**: ≥ $100,000 USD
- 阈值可在 `.env` 中自定义调整

---

## 🔧 高级配置

### 监控交易所

```env
# 支持的交易所（逗号分隔）
EXCHANGES=Binance,OKX,Bybit
```

### AI 模型参数

```env
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_MAX_TOKENS=1000
DEEPSEEK_TEMPERATURE=0.7
```

### 推送通道

```env
# WebSocket 实时推送
WS_PUSH_ENABLED=true

# Webhook 回调
WEBHOOK_PUSH_ENABLED=false
WEBHOOK_URLS=https://your-webhook-url.com/callback
```

---

## 🐳 Docker 部署

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

---

## 🛡️ 安全说明

- 所有 API 密钥通过 `.env` 文件管理，已在 `.gitignore` 中排除
- 邀请码系统防止未授权访问
- 管理员权限独立控制用户审批
- 数据库文件（`.db`）不会被提交到仓库

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。

---

<div align="center">

**Built with ❤️ for crypto whale watchers**

</div>
