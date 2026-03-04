# 快速参考卡片 - 本地启动命令速查

## ⚡ 最快启动（5 分钟）

```bash
# 终端 1: Docker 基础服务（5-10 分钟等待）
make local-deps

# 终端 2: 后端（等待"Application startup complete"）
make local-api

# 终端 3: 前端（等待 "ready in xxx ms"）
make local-web

# 浏览器打开
http://localhost:5173
```

---

## 🔍 手动启动命令

### Docker 基础服务
```bash
docker compose up -d postgres graph etcd minio milvus

# 验证
docker compose ps

# 查看日志
docker compose logs -f
```

### 后端（需要 uv）
```bash
POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know \
NEO4J_URI=bolt://localhost:7687 \
MILVUS_URI=http://localhost:19530 \
MINIO_URI=http://localhost:9000 \
uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload
```

### 前端（需要 pnpm）
```bash
cd web
VITE_API_URL=http://localhost:5050 pnpm run dev
```

---

## 🌐 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:5050/docs |
| 健康检查 | http://localhost:5050/health |
| Neo4j | http://localhost:7474 |
| MinIO | http://localhost:9001 |

---

## 🛑 停止服务

```bash
# 停止本地应用
# 在各终端按 Ctrl+C

# 停止 Docker 服务
docker compose stop

# 或完全删除（谨慎！）
docker compose down -v
```

---

## 🔧 常见问题快速解决

### 端口被占用
```bash
lsof -i :5050  # 查找占用端口 5050 的进程
kill -9 <PID>  # 杀死进程
```

### 无法连接数据库
```bash
docker compose ps  # 检查所有容器是否运行
docker compose logs postgres | grep ready  # 检查 PostgreSQL 是否就绪
```

### 看不到智能体
```bash
uv run python scripts/check_agents.py  # 验证智能体注册
# 然后重启后端: make local-api
# 然后刷新浏览器: Ctrl+Shift+R
```

### 前端连接失败
```bash
echo $VITE_API_URL  # 检查环境变量
curl http://localhost:5050/health  # 检查后端是否运行
```

---

## 📋 启动检查清单

- [ ] Docker Desktop 运行中
- [ ] 5 个 Docker 容器启动成功
- [ ] 后端输出 "Application startup complete"
- [ ] 前端输出 "ready in xxx ms"
- [ ] 浏览器能打开 http://localhost:5173
- [ ] API 文档可访问 http://localhost:5050/docs

---

## 💡 开发小贴士

1. **使用 3 个终端窗口** - 分别运行 Docker、后端、前端
2. **监控日志** - `docker compose logs -f` 实时查看日志
3. **强制刷新** - `Ctrl+Shift+R` 或 `Cmd+Shift+R`
4. **自动重载** - 代码修改后自动重载（前端立即，后端通常也是）
5. **API 测试** - 使用 http://localhost:5050/docs 的 Swagger UI

---

## 📞 获取帮助

| 问题类型 | 参考文档 |
|---------|---------|
| 启动问题 | LOCAL_RUN.md |
| 智能体问题 | FIX_AGENT_NOT_SHOWING.md |
| 架构问题 | ARCHITECTURE_AND_TECH_STACK.md |
| API 问题 | http://localhost:5050/docs |

---

## ✅ 验证服务

```bash
# 一键验证所有服务
echo "=== Docker 服务 ===" && docker compose ps && \
echo -e "\n=== 后端健康检查 ===" && curl -s http://localhost:5050/health && \
echo -e "\n=== 智能体注册 ===" && uv run python scripts/check_agents.py 2>/dev/null || echo "等待后端启动..."
```

---

**💪 祝你启动顺利！** 🚀

