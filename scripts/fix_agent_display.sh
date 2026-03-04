#!/bin/bash
# 快速修复脚本：解决智能体未显示问题

set -e

echo "=========================================="
echo "智能体显示问题快速修复"
echo "=========================================="
echo ""

# 1. 清除 Python 缓存
echo "📝 步骤 1: 清除 Python 缓存..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "✅ Python 缓存已清除"
echo ""

# 2. 检查智能体文件是否存在
echo "📝 步骤 2: 检查智能体文件..."
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
echo ""

# 3. 验证智能体注册
echo "📝 步骤 3: 验证智能体注册..."
if uv run python scripts/check_agents.py; then
    echo "✅ 智能体注册验证成功"
else
    echo "⚠️  智能体注册验证失败，请查看上面的错误信息"
    exit 1
fi
echo ""

# 4. 提示用户重启服务
echo "=========================================="
echo "修复完成！"
echo "=========================================="
echo ""
echo "接下来请执行以下步骤："
echo ""
echo "1. 重启后端服务："
echo "   - 停止当前后端（如果正在运行）：Ctrl+C"
echo "   - 重新启动：make local-api"
echo ""
echo "2. 刷新前端浏览器："
echo "   - 按 Ctrl+Shift+R (Windows/Linux) 或 Cmd+Shift+R (Mac)"
echo "   - 清除浏览器缓存"
echo ""
echo "3. 验证智能体是否显示："
echo "   - 打开 http://localhost:5173/agent"
echo "   - 应该看到 3 个智能体："
echo "     • 智能聊天助手"
echo "     • 深度分析智能体"
echo "     • 数据库报表助手 ← 新的！"
echo ""

