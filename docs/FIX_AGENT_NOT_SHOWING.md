# 数据库图表助手未显示 - 问题解决

## 问题
在智能体选择页面看不到"数据库图表助手"（SqlReporterAgent）。

## 根本原因
**后端服务未重启**，仍在运行旧代码，新增的 SqlReporterAgent 未被加载。

## 解决步骤

### ⚡ 快速修复（推荐）

```bash
# 1. 运行修复脚本
chmod +x scripts/fix_agent_display.sh
./scripts/fix_agent_display.sh

# 2. 重启后端服务
# 停止当前后端（Ctrl+C），然后：
make local-api

# 3. 刷新浏览器（强制刷新）
# Windows/Linux: Ctrl+Shift+R
# Mac: Cmd+Shift+R
```

### 📋 手动步骤

#### 1. 清除缓存
```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete
```

#### 2. 验证智能体注册
```bash
uv run python scripts/check_agents.py
```

**预期输出应包含**：
```
✅ SqlReporterAgent 已在类注册表中
✅ SqlReporterAgent 已实例化
   名称: 数据库报表助手
```

#### 3. 重启后端
```bash
# 方法 1: 使用 make（推荐）
make local-api

# 方法 2: 手动启动
uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload
```

#### 4. 刷新前端
- 打开浏览器开发者工具（F12）
- 右键点击刷新按钮 → "清空缓存并硬性重新加载"
- 或使用快捷键：
  - Windows/Linux: `Ctrl+Shift+R`
  - Mac: `Cmd+Shift+R`

#### 5. 验证结果
访问 `http://localhost:5173/agent`，应该看到 3 个智能体：

1. ✅ 智能聊天助手
2. ✅ 深度分析智能体
3. ✅ **数据库报表助手** ← 应该出现！

## SqlReporterAgent 功能说明

### 基本信息
- **名称**: 数据库报表助手
- **ID**: SqlReporterAgent
- **描述**: 支持多数据库类型的智能数据报表助手

### 支持的数据库
- MySQL
- PostgreSQL
- Oracle
- MSSQL (SQL Server)
- SQLite

### 主要功能
1. **Schema 分析**: 自动分析数据库结构
2. **SQL 生成**: 根据自然语言生成 SQL 查询
3. **SQL 验证**: 检查语法、安全性、性能
4. **SQL 执行**: 安全执行查询并返回结果
5. **图表生成**: 将查询结果可视化（折线图、柱状图、饼图等）
6. **样本检索**: 利用历史查询提高 SQL 质量
7. **错误恢复**: 智能处理和修复 SQL 错误

### 使用前置条件
1. 在"数据源"页面添加数据库连接
2. 同步数据库 Schema
3. 在智能体配置中选择对应的数据源

### 配置选项
- **数据源**: 选择要连接的数据库（必填）
- **MCP服务器**: 选择图表生成服务（默认：mcp-server-chart）
- **系统提示词**: 可自定义 Supervisor 行为

## 技术架构

### 多代理架构
SqlReporterAgent 使用 `langgraph-supervisor` 多代理架构：

```
Supervisor (协调者)
├── schema_agent (Schema分析)
├── sample_retrieval_agent (样本检索)
├── sql_generator_agent (SQL生成)
├── sql_validator_agent (SQL验证)
├── sql_executor_agent (SQL执行)
├── chart_generator_agent (图表生成)
└── error_recovery_agent (错误恢复)
```

### 工作流程
```
用户查询 
  → Schema分析 
  → 样本检索 
  → SQL生成 
  → SQL验证 
  → SQL执行 
  → [图表生成] 
  → 完成
```

## 常见问题

### Q1: 重启后还是看不到？
**解决**：
1. 检查后端启动日志，确认无错误
2. 运行 `scripts/check_agents.py` 验证注册状态
3. 清除浏览器缓存（Ctrl+Shift+Delete）

### Q2: 显示了但无法使用？
**解决**：
1. 确认已添加数据库连接（数据源页面）
2. 确认已同步 Schema
3. 在智能体配置中选择数据源

### Q3: 提示 "数据源的 Schema 信息为空"？
**解决**：
1. 进入"数据源"页面
2. 找到对应的数据库连接
3. 点击"同步 Schema"按钮

### Q4: SQL 执行失败？
**解决**：
1. 检查数据库连接是否正常
2. 检查数据库用户权限
3. 查看错误信息，使用错误恢复功能

## API 测试

### 获取智能体列表
```bash
# 1. 登录获取 token
TOKEN=$(curl -X POST http://localhost:5050/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' \
  | jq -r '.access_token')

# 2. 获取智能体列表
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/chat/agent | jq
```

**预期响应**包含 SqlReporterAgent：
```json
[
  ...
  {
    "id": "SqlReporterAgent",
    "name": "数据库报表助手",
    "description": "一个支持多数据库类型...",
    "capabilities": ["file_upload", "files"],
    "has_checkpointer": true
  }
]
```

## 相关文档

- **完整迁移报告**: `docs/REPORTER_MIGRATION_COMPLETE.md`
- **验证清单**: `docs/VERIFICATION_CHECKLIST.md`
- **问题排查**: `docs/TROUBLESHOOTING_AGENT_NOT_SHOWING.md`

## 获取帮助

如果问题仍未解决：

1. **查看日志**：
   ```bash
   # 后端日志（启动后端时的终端输出）
   # 查找类似信息：
   # INFO: 自动发现智能体: SqlReporterAgent 来自 reporter
   ```

2. **运行诊断**：
   ```bash
   uv run python scripts/check_agents.py
   ```

3. **检查依赖**：
   ```bash
   uv pip list | grep langgraph
   # 应该看到 langgraph-supervisor
   ```

4. **检查文件完整性**：
   ```bash
   ls -la src/agents/reporter/
   # 应该包含：
   # - __init__.py
   # - graph.py
   # - context.py
   # - state.py
   # - tools.py
   # - agents/
   ```

---

**总结**：问题的根本原因是后端服务未重启。重启后端服务后，SqlReporterAgent 应该会自动注册并显示在智能体列表中。

