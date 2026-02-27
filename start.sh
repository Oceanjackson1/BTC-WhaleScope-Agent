#!/bin/bash

# BTC 鲸鱼订单监控系统启动脚本

echo "============================================================"
echo "  BTC Whale Order Monitor v2.0.0"
echo "  启动脚本"
echo "============================================================"
echo ""

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "安装/更新依赖..."
pip install -r requirements.txt

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠️  .env 文件不存在，从 .env.example 复制..."
    cp .env.example .env
    echo ""
    echo "⚠️  请编辑 .env 文件并填入正确的 API Keys："
    echo "   - TG_BOT_TOKEN (已配置)"
    echo "   - DEEPSEEK_API_KEY (已配置)"
    echo "   - CG_API_KEY (已配置)"
    echo ""
    echo "编辑完成后，重新运行此脚本。"
    exit 1
fi

# 检查数据目录
mkdir -p data

# 启动服务
echo ""
echo "============================================================"
echo "  启动服务..."
echo "============================================================"
echo ""

python -m src.main
