# 本地启动指南

本文档用于在本机直接运行前后端进程（不使用前后端容器），数据库等基础服务使用 Docker 启动。

---

## 前置条件

- Docker Desktop 已安装并**正在运行**
- [uv](https://docs.astral.sh/uv/) 已安装（Python 包管理工具）
- [pnpm](https://pnpm.io/) 已安装（前端包管理工具）
- Git 已安装

---

## 架构说明

```
本地运行（直接在操作系统上运行）：
  ├── 前端（localhost:5173）- pnpm dev 启动
  └── 后端（localhost:5050）- uvicorn 启动

Docker 容器运行（基础服务）：
  ├── PostgreSQL（localhost:5432）
  ├── Neo4j（localhost:7687）
  ├── Etcd（localhost:2379）
  ├── MinIO（localhost:9000）
  └── Milvus（localhost:19530）
```

---

## 🐳 第 1 步：启动 Docker 基础服务

Docker 基础服务提供数据库和缓存支持。这一步必须首先完成。

### 1.1 启动所有基础服务（推荐）

```bash
make local-deps
```

或手动执行：

```bash
docker compose up -d postgres graph etcd minio milvus
```

### 1.2 验证服务启动

```bash
docker compose ps
```

**预期输出**：5 个容器处于 `running` 状态

```
NAME               IMAGE                          PORTS              STATUS
postgres           postgres:15                    0.0.0.0:5432       Up
graph              neo4j:5.16                     0.0.0.0:7474       Up
milvus-etcd-dev    quay.io/coreos/etcd            0.0.0.0:2379       Up
milvus-minio       minio/minio                    0.0.0.0:9000       Up
milvus             milvusdb/milvus                0.0.0.0:19530      Up
```

### 1.3 各基础服务说明

| 服务 | 容器名 | 用途 | 端口 | 访问地址 |
|------|--------|------|------|---------|
| PostgreSQL | postgres | 关系数据库 | 5432 | - |
| Neo4j | graph | 知识图数据库 | 7687 | http://localhost:7474 |
| Etcd | milvus-etcd-dev | 分布式配置 | 2379 | - |
| MinIO | milvus-minio | 对象存储 | 9000, 9001 | http://localhost:9001 |
| Milvus | milvus | 向量数据库 | 19530 | - |

### 1.4 查看服务日志

```bash
# 查看所有服务日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f postgres
docker compose logs -f graph
```

### 1.5 等待服务就绪

```bash
# PostgreSQL 就绪信号
docker compose logs postgres | grep "ready to accept"

# Neo4j 就绪信号
docker compose logs graph | grep "started"

# Milvus 就绪信号
docker compose logs milvus | grep "successfully"
```

---

## 🖥️ 第 2 步：启动后端服务（本地）

**前置条件**：确保 Docker 基础服务已启动（第 1 步）

在新的终端窗口中运行。

### 2.1 快速启动（推荐）

```bash
make local-api
```

### 2.2 手动启动

```bash
POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know \
CHECKPOINTER_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/yuxi_know \
NEO4J_URI=bolt://localhost:7687 \
MILVUS_URI=http://localhost:19530 \
MINIO_URI=http://localhost:9000 \
uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload
```

### 2.3 验证后端启动

查看终端输出，应该看到：

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete
INFO:     Uvicorn running on http://0.0.0.0:5050
```

### 2.4 检查后端健康状态

```bash
# 健康检查 API
curl http://localhost:5050/health

# 或在浏览器访问 API 文档
http://localhost:5050/docs
```

### 2.5 后端代码自动重载

后端已配置 `--reload` 模式，修改代码后会自动重载：

```
Uvicorn running on http://0.0.0.0:5050 (Press CTRL+C to quit)
INFO: Will watch for changes in these directories: ['/Users/pusonglin/PycharmProjects/Songlin-Agent']
```

---

## 🎨 第 3 步：启动前端服务（本地）

**前置条件**：确保后端已启动（第 2 步）

在第三个终端窗口中运行。

### 3.1 快速启动（推荐）

```bash
make local-web
```

### 3.2 手动启动

```bash
cd web
VITE_API_URL=http://localhost:5050 pnpm run dev
```

### 3.3 验证前端启动

查看终端输出，应该看到：

```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
  ➜  press h + enter to show help
```

### 3.4 访问前端

在浏览器打开：http://localhost:5173

### 3.5 前端代码自动重载

修改前端代码后，浏览器会自动刷新。

---

## 📍 完整启动流程

### 开发者推荐流程

开发时建议使用 **3 个独立的终端窗口**，分别运行三个服务。

```bash
# ===== 终端 1 =====
# 启动 Docker 基础服务
make local-deps

# 等待服务启动完成，看到所有容器 running 状态

# ===== 终端 2 =====
# 启动后端
make local-api

# 等待后端启动完成，看到 "Application startup complete"

# ===== 终端 3 =====
# 启动前端
make local-web

# 等待前端启动完成，看到 "ready in xxx ms"
```

### 访问应用

所有服务启动后，在浏览器中访问：

- **前端应用**: http://localhost:5173
- **API 文档**: http://localhost:5050/docs
- **Neo4j 图数据库**: http://localhost:7474
- **MinIO 对象存储**: http://localhost:9001

---

## 🔗 服务地址总览

### 应用服务（本地运行）

| 服务 | URL | 描述 |
|------|-----|------|
| 前端应用 | http://localhost:5173 | 主应用界面 |
| 后端 API | http://localhost:5050 | REST API 服务 |
| Swagger 文档 | http://localhost:5050/docs | API 文档界面 |
| 健康检查 | http://localhost:5050/health | 后端健康状态 |

### 管理界面（Docker 基础服务）

| 服务 | URL | 功能 |
|------|-----|------|
| Neo4j 浏览器 | http://localhost:7474 | 知识图数据库管理 |
| MinIO 控制台 | http://localhost:9001 | 对象存储管理 |

### 数据库连接信息（Docker 基础服务）

| 数据库 | 连接 | 用户 | 密码 | 数据库 |
|--------|------|------|------|--------|
| PostgreSQL | localhost:5432 | postgres | postgres | yuxi_know |
| Neo4j | bolt://localhost:7687 | neo4j | (见初始密码) | - |

---

## ⚙️ 环境变量配置

### 后端环境变量

使用 `make local-api` 启动时，这些环境变量会自动设置：

```bash
POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know
CHECKPOINTER_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/yuxi_know
NEO4J_URI=bolt://localhost:7687
MILVUS_URI=http://localhost:19530
MINIO_URI=http://localhost:9000
```

可选的自定义环境变量：

```bash
JWT_SECRET_KEY=your_secret_key
OPENAI_API_KEY=your_api_key
DEBUG=true
LOG_LEVEL=INFO
```

### 前端环境变量

使用 `make local-web` 启动时，这些环境变量会自动设置：

```bash
VITE_API_URL=http://localhost:5050
VITE_WS_URL=ws://localhost:5050
```

---

## 🔍 故障排查

### 问题 1: 后端无法连接 Docker 基础服务

**现象**：
```
ConnectionRefusedError: [Errno 111] Connection refused
Unable to connect to database
```

**原因**：Docker 基础服务未启动或未完全就绪

**解决步骤**：

```bash
# 1. 检查 Docker 基础服务状态
docker compose ps

# 2. 如果服务未运行，启动
docker compose up -d postgres graph etcd minio milvus

# 3. 等待服务完全就绪（2-3 分钟）
docker compose logs postgres | grep "ready"
docker compose logs graph | grep "started"

# 4. 重启后端
make local-api
```

### 问题 2: 后端端口 5050 被占用

**现象**：
```
Address already in use: ('0.0.0.0', 5050)
```

**原因**：端口已被其他进程占用

**解决步骤**：

```bash
# 1. 查找占用进程
lsof -i :5050

# 2. 终止进程（假设 PID 为 12345）
kill -9 12345

# 或者停止 Docker 中的 api 容器
docker compose stop api

# 3. 重启后端
make local-api
```

### 问题 3: 前端端口 5173 被占用

**现象**：
```
Port 5173 is already in use
```

**原因**：端口已被其他进程占用

**解决步骤**：

```bash
# 1. 查找占用进程
lsof -i :5173

# 2. 终止进程
kill -9 <PID>

# 或使用其他端口启动
cd web && VITE_API_URL=http://localhost:5050 pnpm run dev -- --port 5174
```

### 问题 4: 前端无法连接后端 API

**现象**：
- 页面显示 "Failed to connect API"
- 浏览器控制台显示 CORS 错误或连接拒绝
- 网络请求返回 500 或连接超时

**解决步骤**：

```bash
# 1. 验证后端是否运行
curl http://localhost:5050/health

# 2. 检查前端环境变量是否正确设置
echo $VITE_API_URL
# 应该输出: http://localhost:5050

# 3. 重新启动前端（确保环境变量生效）
cd web && VITE_API_URL=http://localhost:5050 pnpm run dev

# 4. 强制刷新浏览器
# Windows/Linux: Ctrl+Shift+R
# Mac: Cmd+Shift+R
```

### 问题 5: PostgreSQL 初始化失败

**现象**：
```
psql: error: could not connect to server
FATAL: Ident authentication failed for user "postgres"
```

**原因**：PostgreSQL 容器初始化异常或数据损坏

**解决步骤**：

```bash
# 1. 完全停止并删除 PostgreSQL 容器及数据卷
docker compose down -v postgres

# 2. 重新启动 PostgreSQL
docker compose up -d postgres

# 3. 等待初始化完成（3-5 分钟）
# 查看 PostgreSQL 日志
docker compose logs -f postgres | grep "ready"

# 4. 验证 PostgreSQL 可用
docker compose exec postgres psql -U postgres -c "SELECT 1"

# 5. 重启后端
make local-api
```

### 问题 6: 看不到智能体列表或显示不完整

**现象**：在智能体页面只看到部分智能体（如只看到 1-2 个）

**解决步骤**：

```bash
# 1. 验证智能体注册情况
uv run python scripts/check_agents.py

# 2. 查看后端启动日志中的智能体发现信息
# 应该看到类似信息：
# INFO: 自动发现智能体: ChatbotAgent
# INFO: 自动发现智能体: DeepAgent
# INFO: 自动发现智能体: SqlReporterAgent

# 3. 如果日志显示发现失败，重启后端
make local-api

# 4. 强制刷新浏览器（清除缓存）
# Windows/Linux: Ctrl+Shift+R
# Mac: Cmd+Shift+R

# 更多信息，参考: docs/FIX_AGENT_NOT_SHOWING.md
```

### 问题 7: Neo4j 连接失败

**现象**：
```
Failed to connect to Neo4j
Could not perform discovery on 'localhost:7687'
```

**原因**：Neo4j 容器未启动或密码不匹配

**解决步骤**：

```bash
# 1. 检查 Neo4j 容器状态
docker compose ps graph

# 2. 如果未运行，启动容器
docker compose up -d graph

# 3. 等待 Neo4j 完全启动（1-2 分钟）
docker compose logs -f graph | grep "started"

# 4. 访问 Neo4j 浏览器验证
# URL: http://localhost:7474
# 用户名: neo4j
# 密码: 查看 docker-compose.yml 中的 NEO4J_AUTH 变量

# 5. 重启后端
make local-api
```

### 问题 8: MinIO 文件上传失败

**现象**：文件上传返回错误

**原因**：MinIO 服务不可用或配置错误

**解决步骤**：

```bash
# 1. 检查 MinIO 容器状态
docker compose ps minio

# 2. 重启 MinIO 容器
docker compose restart minio

# 3. 等待 MinIO 就绪
sleep 10

# 4. 验证 MinIO 可访问
# URL: http://localhost:9001
# 用户名: minioadmin
# 密码: minioadmin

# 5. 重启后端以重新连接 MinIO
make local-api
```

### 问题 9: 应用响应缓慢或内存占用过高

**现象**：
- 应用界面响应缓慢
- 系统占用资源高，卡顿明显

**原因**：Docker 或应用内存不足

**解决步骤**：

```bash
# 1. 检查内存占用
# 使用系统监控工具或命令:
top  # 查看进程内存占用

# 2. 增加 Docker Desktop 内存
# Docker Desktop → Preferences/Settings → Resources
# 将 Memory 增加至 8GB 或以上

# 3. 重启 Docker 引擎
# Docker Desktop 菜单 → Restart

# 4. 清除不必要的 Docker 容器和镜像
docker system prune -a

# 5. 重启所有服务
docker compose down
docker compose up -d
make local-api &
make local-web
```

### 问题 10: 修改代码后后端不自动重载

**现象**：修改后端代码但没有自动重载

**原因**：后端启动时未启用 `--reload` 模式

**解决步骤**：

```bash
# 1. 检查启动命令是否包含 --reload
# 应该看到: "Will watch for changes in these directories"

# 2. 如果没有看到，使用 make 命令重启后端
make local-api

# 3. 或手动启动时添加 --reload 参数
POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know \
NEO4J_URI=bolt://localhost:7687 \
MILVUS_URI=http://localhost:19530 \
MINIO_URI=http://localhost:9000 \
uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload
```

---

## 🛑 停止和清理服务

### 停止所有服务（保留数据）

```bash
# 1. 停止本地应用
# 在前端终端按 Ctrl+C
# 在后端终端按 Ctrl+C

# 2. 停止 Docker 基础服务（保留数据）
docker compose stop

# 数据会保留，下次启动时恢复
docker compose start
```

### 完全停止所有服务（包括 Docker）

```bash
docker compose down
```

### 完全清除所有数据（谨慎操作！）

```bash
# 1. 停止并删除所有容器
docker compose down

# 2. 删除所有数据卷（数据无法恢复）
docker compose down -v

# 3. 清除 Python 缓存
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete

# 4. 清除 Node 缓存（可选）
rm -rf web/node_modules
rm pnpm-lock.yaml

# 5. 重新启动
docker compose up -d
make local-api &
make local-web
```

---

## 📋 常见工作流示例

### 场景 1：首次启动项目

```bash
# 1. 进入项目目录
cd /path/to/Songlin-Agent

# 2. 终端 1：启动 Docker 基础服务
docker compose up -d postgres graph etcd minio milvus

# 3. 验证所有服务都在运行
docker compose ps  # 应该显示 5 个 running 容器

# 4. 终端 2：启动后端
make local-api

# 5. 终端 3：启动前端
make local-web

# 6. 浏览器打开应用
# 前端: http://localhost:5173
# API 文档: http://localhost:5050/docs
```

### 场景 2：日常开发（第二天启动）

```bash
# 1. 检查 Docker 基础服务
docker compose ps

# 如果所有服务都是 running，跳到步骤 3
# 否则启动
docker compose up -d

# 2. 等待服务就绪
sleep 10

# 3. 终端 1：启动后端
make local-api

# 4. 终端 2：启动前端
make local-web

# 5. 打开浏览器，开始开发
```

### 场景 3：修改代码后更新

```bash
# 前端代码修改
# → 自动刷新，页面实时更新

# 后端代码修改
# → 自动重载，通常无需干预
# 如果需要手动重启：
# 1. 按 Ctrl+C 停止后端
# 2. make local-api 重启
# 3. 刷新前端浏览器

# 安装了新的 Python 依赖
# 1. uv sync 同步依赖
# 2. 重启后端 make local-api

# 安装了新的 Node 依赖
# 1. cd web && pnpm install
# 2. 重启前端 pnpm run dev
```

### 场景 4：重置数据库

```bash
# 1. 停止所有服务
docker compose down

# 2. 删除数据卷（重置数据库）
docker compose down -v

# 3. 清除缓存
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 4. 重新启动
docker compose up -d postgres graph etcd minio milvus
make local-api &
make local-web
```

---

## 📚 相关文档

- [Docker Compose 配置详解](./docker-compose.yml)
- [项目架构和技术栈](./docs/ARCHITECTURE_AND_TECH_STACK.md)
- [智能体配置指南](./docs/AGENTS.md)
- [智能体未显示问题排查](./docs/FIX_AGENT_NOT_SHOWING.md)
- [Reporter 升级完成报告](./docs/REPORTER_MIGRATION_COMPLETE.md)
- [后端 API 文档](http://localhost:5050/docs)（启动后端后访问）

---

## 💡 开发最佳实践

1. **使用 3 个终端窗口**：分别运行 Docker、后端、前端，便于监控日志
2. **使用 make 命令**：简化启动步骤，推荐用于日常开发
3. **定期检查日志**：及时发现和解决问题
4. **设置 IDE 调试**：PyCharm/VSCode 可直接启动后端调试
5. **使用版本控制**：定期 commit，便于回滚和协作
6. **定期备份数据**：重要数据定期导出

---

## ❓ 快速问题排查

如果遇到问题，按以下顺序检查：

1. **Docker 基础服务是否运行？**
   ```bash
   docker compose ps
   ```

2. **后端是否启动成功？**
   ```bash
   curl http://localhost:5050/health
   ```

3. **前端是否启动成功？**
   ```bash
   浏览器访问 http://localhost:5173
   ```

4. **环境变量是否正确？**
   ```bash
   echo $VITE_API_URL
   ```

5. **查看详细错误日志**
   ```bash
   docker compose logs -f
   ```

如果问题仍未解决，参考本文档的"故障排查"部分或相关文档。
