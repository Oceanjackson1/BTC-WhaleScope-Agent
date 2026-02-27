# 部署和启动指南

本指南帮助您正确配置和启动 BTC 鲸鱼订单监控系统。

---

## 一、系统要求

### 软件要求
- Python >= 3.9
- pip（Python 包管理器）

### API Keys 要求
1. **Telegram Bot Token**
   - 访问 [@BotFather](https://t.me/BotFather)
   - 发送 `/newbot` 创建新 Bot
   - 获取 Bot Token（格式：`1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`）
   - 当前已配置：`8792768648:AAGPgNQb3_BboJowiEN7RpoBauca9yfegIk`

2. **Deepseek API Key**
   - 访问 [Deepseek 平台](https://platform.deepseek.com/)
   - 注册账号并获取 API Key
   - 当前已配置：`sk-589ae78225394e4c842ee72cec346fb5`

3. **CoinGlass API Key**
   - 访问 [CoinGlass](https://www.coinglass.com/)
   - 注册账号并获取 API Key
   - 当前已配置：`da0d629f45274302bb2647f72a1a29bc`

---

## 二、安装依赖

### 1. 创建虚拟环境（推荐）

```bash
# 进入项目目录
cd /Users/ocean/Desktop/BTC-Whale-Order-Monitoring-Tool-main

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate
```

### 2. 安装 Python 依赖

```bash
# 安装所有依赖
pip install -r requirements.txt

# 验证关键依赖已安装
pip list | grep -E "(telegram|openai|pydantic)"
```

**预期输出：**
```
openai                 2.24.0
pydantic               2.12.5
pydantic_core          2.41.5
python-telegram-bot    22.5
```

如果看到 `WARNING: Package(s) not found`，说明安装失败，请检查网络连接。

---

## 三、配置系统

### 1. 检查 `.env` 文件

配置文件应该位于项目根目录：`.env`

### 2. 配置内容示例

`.env.example` 文件已经包含完整的配置模板，并且已经预配置了您的 API Keys：

```env
# Telegram Bot (已配置)
TG_BOT_TOKEN=8792768648:AAGPgNQb3_BboJowiEN7RpoBauca9yfegIk
TG_ENABLED=true
TG_ADMIN_IDS=123456789,987654321

# Deepseek AI (已配置)
DEEPSEEK_API_KEY=sk-589ae78225394e4c842ee72cec346fb5
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_MAX_TOKENS=1000
DEEPSEEK_TEMPERATURE=0.7

# CoinGlass API (已配置)
CG_API_KEY=da0d629f45274302bb2647f72a1a29bc

# 服务配置
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# 数据库
DB_PATH=data/whale_orders.db
USER_DB_PATH=data/users.db

# 采集配置（秒）
POLL_INTERVAL_LARGE_ORDER=10
POLL_INTERVAL_LIQUIDATION=10
POLL_INTERVAL_WHALE_ALERT=10
POLL_INTERVAL_ONCHAIN=60

# 监控交易所（逗号分隔）
EXCHANGES=Binance,OKX,Bybit

# 大额订单阈值（美元）
LARGE_ORDER_THRESHOLD=500000
LIQUIDATION_THRESHOLD=100000

# Webhook 配置（可选）
WEBHOOK_URLS=

# 推送配置
WS_PUSH_ENABLED=true
WEBHOOK_PUSH_ENABLED=false
```

### 3. 配置说明

#### Telegram Bot 配置
- `TG_BOT_TOKEN`: 您的 Bot Token（必需）
- `TG_ENABLED`: 是否启用 Telegram Bot（true/false）
- `TG_ADMIN_IDS`: 管理员 Telegram ID 列表（逗号分隔）

#### Deepseek AI 配置
- `DEEPSEEK_API_KEY`: Deepseek API Key（必需）
- `DEEPSEEK_MODEL`: 模型名称，默认 `deepseek-chat`
- `DEEPSEEK_MAX_TOKENS`: 最大 Token 数，默认 1000
- `DEEPSEEK_TEMPERATURE`: 温度参数（0.0-1.0），默认 0.7

#### CoinGlass API 配置
- `CG_API_KEY`: CoinGlass API Key（必需）

#### 服务配置
- `HOST`: 服务监听地址，默认 `0.0.0.0`
- `PORT`: 服务端口，默认 8000
- `LOG_LEVEL`: 日志级别（DEBUG/INFO/WARNING/ERROR）

#### 数据库配置
- `DB_PATH`: 鲸鱼订单数据库路径，默认 `data/whale_orders.db`
- `USER_DB_PATH`: 用户数据库路径，默认 `data/users.db`

#### 采集配置
- `POLL_INTERVAL_LARGE_ORDER`: 大额订单轮询间隔（秒），默认 10
- `POLL_INTERVAL_LIQUIDATION`: 爆仓订单轮询间隔（秒），默认 10
- `POLL_INTERVAL_WHALE_ALERT`: Hyperliquid 鲸鱼轮询间隔（秒），默认 10
- `POLL_INTERVAL_ONCHAIN`: 链上转账轮询间隔（秒），默认 60

#### 监控配置
- `EXCHANGES`: 监控的交易所列表（逗号分隔），默认 `Binance,OKX,Bybit`
- `LARGE_ORDER_THRESHOLD`: 大额订单金额阈值（美元），默认 500000
- `LIQUIDATION_THRESHOLD`: 爆仓金额阈值（美元），默认 100000

#### 推送配置
- `WS_PUSH_ENABLED`: WebSocket 推送开关，默认 true
- `WEBHOOK_PUSH_ENABLED`: Webhook 推送开关，默认 false
- `WEBHOOK_URLS`: Webhook URL 列表（逗号分隔）

---

## 四、启动系统

### 方法 1：直接运行（推荐）

```bash
# 进入项目目录
cd /Users/ocean/Desktop/BTC-Whale-Order-Monitoring-Tool-main

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python3 -m src.main
```

### 方法 2：使用启动脚本

```bash
# 进入项目目录
cd /Users/ocean/Desktop/BTC-Whale-Order-Monitoring-Tool-main

# 运行启动脚本（会自动处理依赖安装）
bash start.sh
```

### 方法 3：Docker 部署（可选）

```bash
# 构建镜像
docker build -t btc-whale-monitor .

# 运行容器
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  -v whale_data:/app/data \
  --name whale-monitor \
  btc-whale-monitor
```

---

## 五、验证启动成功

### 启动日志检查

系统启动后，您应该看到以下日志输出：

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

### 状态检查

启动成功后，可以通过以下方式检查：

1. **检查 API 服务**
   ```bash
   curl http://localhost:8000/health
   ```
   预期响应：
   ```json
   {"status":"ok","timestamp":1771992000000}
   ```

2. **检查系统配置**
   ```bash
   curl http://localhost:8000/api/config
   ```
   预期返回配置信息

3. **检查系统统计**
   ```bash
   curl http://localhost:8000/api/stats
   ```

---

## 六、首次使用 Telegram Bot

### 1. 启动 Bot

1. 在 Telegram 中搜索您的 Bot（通过配置时设置的用户名）
2. 点击 "Start" 按钮或发送 `/start` 命令

### 2. 等待审核

首次注册的用户状态为"待审核"，需要管理员审核。

### 3. 管理员审核

管理员使用以下命令审核用户：
```
/approve 123456789
```

### 4. 设置订阅

用户审核通过后，可以设置订阅：
1. 发送 `/subscribe` 命令
2. 选择要订阅的交易所（Binance、OKX、Bybit、全部）
3. 设置金额阈值（如：500000）
4. 点击"完成"保存设置

### 5. 开始接收告警

配置完成后，系统会自动推送符合条件的大单告警到 Telegram。

---

## 七、常见问题排查

### 问题 1：ModuleNotFoundError: No module named 'pydantic_settings'

**原因：** pydantic-settings 依赖未安装

**解决方法：**
```bash
# 确保在虚拟环境中
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 验证安装
pip show pydantic-settings
```

### 问题 2：API Key 无效

**错误信息：** `CoinGlass API error 401: Unauthorized`

**解决方法：**
1. 检查 `.env` 文件中的 API Key 是否正确
2. 确认 API Key 未过期
3. 检查 CoinGlass 账户状态

### 问题 3：Telegram Bot 无法启动

**错误信息：** `Telegram Bot not configured or disabled`

**解决方法：**
1. 检查 `.env` 文件中 `TG_ENABLED=true`
2. 检查 `TG_BOT_TOKEN` 格式是否正确
3. 确认 Bot Token 未失效

### 问题 4：Deepseek AI 调用失败

**错误信息：** `Deepseek API error 401: Invalid API Key`

**解决方法：**
1. 检查 `.env` 文件中 `DEEPSEEK_API_KEY` 是否正确
2. 确认 API Key 格式：`sk-...`
3. 检查 Deepseek 账户余额和配额

### 问题 5：端口被占用

**错误信息：** `OSError: [Errno 48] Address already in use`

**解决方法：**
```bash
# 查找占用 8000 端口的进程
lsof -ti:8000

# 杀死进程
kill -9 <PID>

# 或修改配置文件中的 PORT
```

### 问题 6：数据库权限错误

**错误信息：** `PermissionError: [Errno 13] Permission denied`

**解决方法：**
```bash
# 修改数据库文件权限
chmod 644 data/*.db
chmod 755 data/

# 或设置正确的所有者
chown -R $(whoami):$(whoami) data/
```

---

## 八、功能测试

### 1. 测试 Telegram Bot 连接

```bash
# 在 Telegram 中发送 /help 命令

# 预期：收到完整的帮助菜单
```

### 2. 测试用户注册

```bash
# 使用新 Telegram 账号搜索 Bot
# 点击 Start 按钮

# 预期：收到欢迎消息，状态为"待审核"
```

### 3. 测试用户审核

```bash
# 管理员在 Telegram 中发送：
/approve <新用户的 telegram_id>

# 预期：用户收到激活通知
```

### 4. 测试自然语言查询

```bash
# 在 Telegram 中发送以下测试问题：
# - "最近 1 小时的大单趋势"
# - "分析一下 Binance 的大单"
# - "当前市场情绪如何？"

# 预期：收到 AI 分析结果
```

### 5. 测试告警推送

由于需要真实的大单才能触发告警，可以：
1. 等待系统检测到符合条件的大单
2. 或手动触发测试告警（需要修改代码进行测试）

### 6. 测试 Web API

```bash
# 测试健康检查
curl http://localhost:8000/health

# 测试配置查询
curl http://localhost:8000/api/config

# 测试统计查询
curl http://localhost:8000/api/stats

# 测试订单查询
curl "http://localhost:8000/api/orders?limit=10"
```

---

## 九、监控和维护

### 日志监控

系统启动后会持续输出日志，格式如下：

```
2026-02-26 16:00:00 [INFO] src.main: BTC Whale Order Monitor v2.0.0
2026-02-26 16:00:01 [INFO] src.main: Database initialized at data/whale_orders.db
2026-02-26 16:00:02 [INFO] src.telegram.bot: Telegram Bot started successfully
2026-02-26 16:00:03 [INFO] src.collectors.large_order: Collector [futures_large_order] started (interval=10s)
2026-02-26 16:00:04 [INFO] src.api.coinglass_client: GET /api/futures/orderbook/large-limit-order -> 200
```

### 性能监控

关注以下指标：
- 告警推送延迟
- AI 分析响应时间
- 数据库查询性能
- 内存使用情况
- API 调用频率

### 数据备份

定期备份数据库文件：

```bash
# 创建备份目录
mkdir -p backups

# 备份数据库
cp data/whale_orders.db backups/whale_orders_$(date +%Y%m%d_%H%M%S).db
cp data/users.db backups/users_$(date +%Y%m%d_%H%M%S).db
```

---

## 十、生产环境部署建议

### 1. 使用进程管理器

推荐使用 `supervisor` 或 `systemd` 管理进程：

**Supervisor 配置示例：**
```ini
[program:whale-monitor]
command=/path/to/venv/bin/python -m src.main
directory=/path/to/project
user=whale
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/whale-monitor.log
environment=PATH="/path/to/venv/bin"
```

### 2. 配置反向代理

使用 Nginx 作为反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. 配置 HTTPS

使用 Let's Encrypt 免费证书：
```bash
# 安装 certbot
sudo apt-get install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# Nginx 配置会自动更新
```

### 4. 设置监控告警

配置系统异常告警（如服务器宕机、API 异常）：
- 使用 Telegram Bot 推送系统告警
- 使用邮件备份
- 集成第三方监控服务（如 UptimeRobot、Pingdom）

---

## 十一、安全加固

### 1. 保护 API Keys

- 不要将 `.env` 文件提交到版本控制
- 使用环境变量管理敏感信息
- 定期轮换 API Keys
- 限制 API Key 的权限（最小权限原则）

### 2. 网络安全

- 使用防火墙限制入站访问
- 仅开放必要的端口（如 80、443）
- 配置 fail2ban 防止暴力破解
- 启用 HTTPS 加密通信

### 3. 访问控制

- 定期审计用户列表
- 及时撤销不需要的访问权限
- 实施多因素认证（如果适用）
- 记录所有管理员操作

### 4. 数据安全

- 定期备份数据库
- 加密备份数据
- 测试备份恢复流程
- 异地存储备份

---

## 十二、快速启动命令

### 一键启动（Mac/Linux）

```bash
cd /Users/ocean/Desktop/BTC-Whale-Order-Monitoring-Tool-main && \
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt && \
python3 -m src.main
```

### 后台运行

```bash
# 使用 nohup 在后台运行
nohup python3 -m src.main > monitor.log 2>&1 &

# 或使用 screen
screen -S whale-monitor
python3 -m src.main
# 按 Ctrl+A 然后 D 分离
# 重新连接: screen -r whale-monitor
```

### 查看运行状态

```bash
# 查看进程
ps aux | grep "src.main"

# 查看日志
tail -f monitor.log

# 停止进程
pkill -f "python3.*src.main"
```

---

## 总结

本指南涵盖了：

完整的依赖安装流程
详细的配置说明
多种启动方法
全面的故障排查
功能测试步骤
监控和维护建议
生产环境部署
安全加固措施

按照本指南，您应该能够成功启动和运行 BTC 鲸鱼订单监控系统。

如有问题，请参考：
1. TELEGRA_SETUP.md - Telegram Bot 详细配置
2. IMPLEMENTATION_SUMMARY.md - 实现总结
3. TELEGRA_INTERACTION_PLAN.md - 交互设计详细方案

祝您使用顺利！
