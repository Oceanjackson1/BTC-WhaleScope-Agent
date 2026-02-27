# Telegram Bot 设置指南

本指南将帮助您设置和部署 BTC 鲸鱼订单监控 Telegram Bot。

---

## 前置要求

1. **Telegram Bot Token**
   - 与 @BotFather 对话创建新 Bot
   - 获取 Bot Token（格式：`1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`）

2. **Deepseek API Key**
   - 访问 [Deepseek](https://platform.deepseek.com/)
   - 注册账号并获取 API Key

3. **管理员 Telegram ID**
   - 与 @userinfobot 对话获取您的 Telegram ID
   - 这将用于用户审核和管理功能

---

## 配置步骤

### 1. 更新 `.env` 文件

```env
# Telegram Bot 配置
TG_BOT_TOKEN=your_bot_token_here
TG_ENABLED=true
TG_ADMIN_IDS=123456789,987654321  # 替换为您的管理员 ID

# Deepseek AI 配置
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_MAX_TOKENS=1000
DEEPSEEK_TEMPERATURE=0.7

# CoinGlass API 配置（现有）
CG_API_KEY=your_coinglass_api_key_here

# 其他配置...
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务

```bash
python -m src.main
```

服务启动后，您应该看到：

```
============================================================
  BTC Whale Order Monitor v2.0.0
  Exchanges: ['Binance', 'OKX', 'Bybit']
  Large order threshold: $500,000
  Liquidation threshold: $100,000
  Telegram Bot: enabled
  Deepseek AI: enabled
============================================================
Database initialized at data/whale_orders.db
User database initialized at data/users.db
Deepseek client initialized
CoinGlass REST client started
Push dispatcher started
Telegram Bot started successfully. Admins: [123456789]
...
All collectors started. System ready.
Uvicorn running on http://0.0.0.0:8000
```

---

## 用户使用指南

### 首次使用

1. **启动 Bot**
   - 在 Telegram 中搜索您的 Bot
   - 点击 "Start" 或发送 `/start` 命令

2. **等待审核**
   - 用户注册后处于"待审核"状态
   - 管理员使用 `/approve <user_id>` 激活用户

3. **开始使用**
   - 激活后，用户可以设置订阅并接收告警

### 可用命令

| 命令 | 说明 |
|------|------|
| `/start` | 注册/启动 Bot |
| `/help` | 显示帮助信息 |
| `/subscribe` | 设置订阅偏好（交易所、金额阈值）|
| `/stats` | 查看个人统计 |
| `/status` | 查看系统状态 |

**查询命令（自然语言）：**
- "最近 1 小时的大单趋势"
- "分析一下 Binance 的大单"
- "给我看最近 3 笔最大的爆仓单"
- "当前市场情绪如何？"

**管理员命令：**
| 命令 | 说明 |
|------|------|
| `/approve <user_id>` | 审核用户（仅管理员）|
| `/revoke <user_id>` | 撤销用户（仅管理员）|
| `/users` | 查看所有用户（仅管理员）|

### 订阅设置

用户可以通过 `/subscribe` 命令配置：

- **选择交易所**：Binance、OKX、Bybit（可多选）
- **设置金额阈值**：只接收超过此金额的告警
- **完成设置**：保存配置

---

## 功能特性

### 实时告警推送

当检测到符合条件的大额订单时，Bot 会推送包含以下信息的告警：

```
🟢 鲸鱼大单告警

📊 交易所: Binance
💱 交易对: BTCUSDT
🟢 方向: 买入
💰 金额: $6,000,000
📈 价格: $95,000.00
📝 类型: large_limit
⏰ 时间: 2026-02-26 15:30:45

---
🤖 AI 分析

📊 分析: Binance 出现一笔超大额买单...
🎯 交易信号: 📈 BULLISH
🎲 置信度: 85/100
⚠️ 风险等级: MEDIUM
💡 建议: 大额买单可能推动短期上涨，建议谨慎做多
```

### AI 查询分析

用户可以用自然语言提问，例如：

```
用户: 最近 1 小时 Binance 的大单有什么趋势？

Bot: *📈 Binance 趋势分析（过去 1 小时）*

**趋势判断:** 📈 看涨 - 买盘强势

📊 买入: 62%
📊 卖出: 38%
📊 总订单: 24

---
*🤖 AI 洞察:*
基于数据显示，Binance 在过去 1 小时内买盘占优，
这可能预示短期看涨趋势...
```

---

## Docker 部署

### 使用 Docker Compose

在 `docker-compose.yml` 中添加 Telegram Bot 服务：

```yaml
services:
  whale-monitor:
    build: .
    environment:
      - CG_API_KEY=${CG_API_KEY}
      - TG_BOT_TOKEN=${TG_BOT_TOKEN}
      - TG_ENABLED=true
      - TG_ADMIN_IDS=${TG_ADMIN_IDS}
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

启动服务：

```bash
docker-compose up -d
```

查看日志：

```bash
docker-compose logs -f whale-monitor
```

---

## 故障排查

### Bot 无法启动

1. **检查 Token**
   ```bash
   # 在 `.env` 文件中确认 Token 格式正确
   TG_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

2. **检查日志**
   ```bash
   # 查看启动日志
   python -m src.main
   ```

### 用户无法收到告警

1. **检查用户状态**
   ```bash
   # 管理员使用 /users 命令查看用户列表
   ```

2. **检查订阅配置**
   ```bash
   # 用户使用 /stats 查看个人订阅
   ```

3. **检查金额阈值**
   ```bash
   # 确认订单金额 >= 用户设置的 min_alert_threshold
   ```

### AI 分析不工作

1. **检查 API Key**
   ```bash
   # 在 `.env` 中确认 DEEPSEEK_API_KEY 已配置
   DEEPSEEK_API_KEY=sk-589ae78225394e4c842ee72cec346fb5
   ```

2. **检查网络连接**
   ```bash
   # 确保服务器可以访问 Deepseek API
   curl https://api.deepseek.com
   ```

3. **查看错误日志**
   ```bash
   # 查看日志中的 AI 相关错误
   python -m src.main
   ```

---

## 安全建议

1. **保护敏感信息**
   - 不要将 `.env` 文件提交到 Git
   - 使用环境变量或密钥管理服务

2. **限制管理员权限**
   - 只信任的用户才能成为管理员
   - 定期审核用户列表

3. **监控资源使用**
   - 监控 Deepseek API 调用次数和成本
   - 设置适当的调用限制

4. **数据备份**
   - 定期备份 `data/` 目录
   - 考虑使用远程存储

---

## 性能优化

1. **消息队列**
   - Bot 使用异步消息队列，避免阻塞
   - 支持并发推送多个用户

2. **AI 分析缓存**
   - 相同订单的分析结果缓存 5 分钟
   - 减少重复 API 调用

3. **数据库索引**
   - 用户表和订单表已建立索引
   - 查询性能优化

---

## 下一步

- [ ] 添加更多自然语言查询模板
- [ ] 支持多币种监控（ETH、SOL 等）
- [ ] 添加价格图表可视化
- [ ] 实现用户分组/标签功能
- [ ] 添加告警静默时段设置
- [ ] 支持 Webhook 推送到自定义服务
- [ ] 添加多语言支持

---

## 支持

如有问题或建议，请联系：
- GitHub Issues
- Telegram 社群
