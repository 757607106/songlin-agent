# 数据库图表助手未显示问题 - 排查和解决方案

## 问题描述
在智能体选择页面（`localhost:5173/agent`）中，只显示"智能聊天助手"和"深度分析智能体"，但没有显示"数据库图表助手"（SqlReporterAgent）。

## 原因分析

### 1. 智能体注册机制
系统使用 `AgentManager` 自动发现并注册智能体：
- 扫描 `src/agents/` 目录下的所有子文件夹
- 导入继承自 `BaseAgent` 的类
- 自动注册并初始化实例

### 2. SqlReporterAgent 配置正确
- ✅ 文件位置：`src/agents/reporter/graph.py`
- ✅ 类定义：继承自 `BaseAgent`
- ✅ 元数据：
  ```python
  class SqlReporterAgent(BaseAgent):
      name = "数据库报表助手"
      description = "一个支持多数据库类型的智能数据报表助手..."
      context_schema = ReporterContext
      capabilities = ["file_upload", "files"]
  ```
- ✅ 导出：在 `__init__.py` 中正确导出

### 3. 可能原因
- **最可能**：后端服务未重启，旧代码仍在运行
- 智能体初始化时出错（但未中断其他智能体加载）
- 依赖缺失（如 langgraph-supervisor）

## 解决方案

### 方案 1：重启后端服务（推荐）

```bash
# 如果使用 make 命令启动的
# 1. 停止当前后端服务（Ctrl+C）
# 2. 重新启动
make local-api

# 或者如果使用手动命令
# 1. 停止当前服务（Ctrl+C）
# 2. 重新启动
uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload
```

### 方案 2：验证智能体注册

运行检查脚本：

```bash
uv run python scripts/check_agents.py
```

**预期输出**：
```
============================================================
智能体注册状态检查
============================================================

已注册的智能体类 (3 个):
  - ChatbotAgent: <class 'src.agents.chatbot.graph.ChatbotAgent'>
  - DeepAgent: <class 'src.agents.deep_agent.graph.DeepAgent'>
  - SqlReporterAgent: <class 'src.agents.reporter.graph.SqlReporterAgent'>

已实例化的智能体 (3 个):
  - ChatbotAgent
    name: 智能聊天助手
    description: 基础的对话机器人，可以回答问题...
    capabilities: ['file_upload']

  - DeepAgent
    name: 深度分析智能体
    description: 具备规划、深度分析和子智能体协作能力...
    capabilities: ['file_upload', 'todo', 'files']

  - SqlReporterAgent
    name: 数据库报表助手
    description: 一个支持多数据库类型（MySQL / PostgreSQL / Oracle / MSSQL / SQLite）...
    capabilities: ['file_upload', 'files']

============================================================
SqlReporterAgent 检查:
============================================================
✅ SqlReporterAgent 已在类注册表中
✅ SqlReporterAgent 已实例化
   名称: 数据库报表助手
   描述: 一个支持多数据库类型（MySQL / PostgreSQL / Oracle / MSSQL / SQLite）的智能数据报表助手。能够分析数据库结构、生成 SQL 查询、执行查询并以图表形式展示分析结果。
```

### 方案 3：检查依赖

确保安装了所有必需的依赖：

```bash
# 检查 langgraph-supervisor
uv pip list | grep langgraph

# 如果未安装，添加依赖
uv add langgraph-supervisor
```

### 方案 4：检查后端日志

启动后端时查看日志，确认智能体是否成功加载：

```bash
# 查看启动日志，应该看到类似信息：
# INFO: 自动发现智能体: ChatbotAgent 来自 chatbot
# INFO: 自动发现智能体: DeepAgent 来自 deep_agent
# INFO: 自动发现智能体: SqlReporterAgent 来自 reporter
```

如果看到警告或错误：
```bash
# WARNING: 无法从 reporter 加载智能体: <error message>
```

这说明加载过程中出错，需要检查错误信息并修复。

### 方案 5：清除缓存并重启

```bash
# 1. 清除 Python 缓存
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete

# 2. 重启后端
make local-api
```

## 验证修复

### 1. 检查 API 响应

```bash
# 获取智能体列表（需要先登录获取 token）
curl -H "Authorization: Bearer <your_token>" \
  http://localhost:5050/api/chat/agent
```

**预期响应**应包含 3 个智能体：
```json
[
  {
    "id": "ChatbotAgent",
    "name": "智能聊天助手",
    "description": "基础的对话机器人...",
    ...
  },
  {
    "id": "DeepAgent",
    "name": "深度分析智能体",
    "description": "具备规划、深度分析...",
    ...
  },
  {
    "id": "SqlReporterAgent",
    "name": "数据库报表助手",
    "description": "一个支持多数据库类型...",
    ...
  }
]
```

### 2. 检查前端

1. 刷新浏览器（清除缓存：Ctrl+Shift+R 或 Cmd+Shift+R）
2. 打开智能体选择页面：`http://localhost:5173/agent`
3. 应该看到 3 个智能体卡片：
   - 智能聊天助手
   - 深度分析智能体
   - **数据库报表助手** ← 应该显示

## 常见问题

### Q1: 重启后还是看不到？
**A**: 检查前端是否有缓存，强制刷新浏览器（Ctrl+Shift+R）

### Q2: 其他智能体也看不到了？
**A**: 说明整个 AgentManager 初始化失败，检查：
- 基础依赖是否安装（`uv sync`）
- Python 路径是否正确
- 是否有语法错误

### Q3: 日志显示加载失败？
**A**: 查看具体错误信息，可能是：
- 缺少依赖包（安装 `uv add <package>`）
- 配置文件错误（检查 `reporter/context.py`）
- 导入循环（检查模块依赖）

### Q4: API 返回 3 个智能体，但前端只显示 2 个？
**A**: 前端问题，检查：
- 浏览器控制台是否有 JavaScript 错误
- 前端是否有过滤逻辑
- 刷新前端缓存

## 快速修复步骤

```bash
# 1. 停止所有服务
# 按 Ctrl+C 停止后端和前端

# 2. 清除缓存
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 3. 重启后端
make local-api

# 4. 在另一个终端，验证智能体注册
uv run python scripts/check_agents.py

# 5. 如果验证通过，刷新前端浏览器（Ctrl+Shift+R）
```

## 总结

**最可能的原因**：后端服务未重启，仍在运行旧代码。

**解决方案**：
1. 重启后端服务
2. 清除浏览器缓存
3. 验证智能体是否成功注册

如果问题仍然存在，运行 `scripts/check_agents.py` 获取详细诊断信息。

