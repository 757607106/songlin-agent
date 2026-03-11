#!/bin/bash
# 快速检查脚本：核对当前新版 Agent 暴露状态

set -e

echo "=========================================="
echo "智能体显示问题快速检查"
echo "=========================================="
echo ""

# 1. 检查关键文件是否存在
echo "📝 步骤 1: 检查关键文件..."
if [ -f "src/agents/reporter/graph.py" ]; then
    echo "✅ reporter/graph.py 存在"
else
    echo "❌ reporter/graph.py 不存在！"
    exit 1
fi

if [ -f "src/agents/reporter/__init__.py" ]; then
    echo "✅ reporter/__init__.py 存在"
else
    echo "❌ reporter/__init__.py 不存在！"
    exit 1
fi

if [ -f "src/agents/agent_platform/graph.py" ]; then
    echo "✅ agent_platform/graph.py 存在"
else
    echo "❌ agent_platform/graph.py 不存在！"
    exit 1
fi

if [ -f "server/routers/agent_design_router.py" ]; then
    echo "✅ agent_design_router.py 存在"
else
    echo "❌ agent_design_router.py 不存在！"
    exit 1
fi
echo ""

# 2. 验证智能体注册
echo "📝 步骤 2: 验证智能体注册..."
if docker compose exec api uv run python scripts/check_agents.py; then
    echo "✅ 智能体注册验证成功"
else
    echo "⚠️  智能体注册验证失败，请查看上面的错误信息"
    exit 1
fi
echo ""

# 3. 查看最近日志
echo "📝 步骤 3: 查看最近日志..."
docker compose logs api --tail 20
echo ""

# 4. 输出当前架构说明
echo "=========================================="
echo "检查完成"
echo "=========================================="
echo ""
echo "当前预期行为："
echo ""
echo "1. 产品内置默认只显示 1 个 Agent："
echo "   - 数据库报表助手"
echo ""
echo "2. 自定义 Agent 通过 AgentPlatformAgent 运行："
echo "   - 先用 /api/agent-design/* 创建并部署"
echo "   - 再在 AgentPlatformAgent 配置列表中查看"
echo ""
echo "3. 如果前端没更新："
echo "   - docker compose ps"
echo "   - docker compose logs api --tail 100"
echo "   - 浏览器强制刷新"
echo ""
