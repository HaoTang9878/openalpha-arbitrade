# ===================================================================
# 多阶段构建 Dockerfile
# 阶段 1: Node.js 构建前端 React SPA
# 阶段 2: Python 运行后端 + 前端静态文件
# ===================================================================

# ---- 阶段 1: 构建前端 ----
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# 复制 package 文件并安装依赖
COPY frontend-react/package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps

# 复制前端源码并构建
COPY frontend-react/ ./
RUN npm run build

# ---- 阶段 2: Python 后端 ----
FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件并安装
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ ./backend/

# 复制旧版前端（回退）
COPY frontend/ ./frontend/

# 从阶段 1 复制 React 构建产物
COPY --from=frontend-builder /frontend/dist ./frontend-react/dist

# 创建数据目录
RUN mkdir -p /app/data

EXPOSE 8070

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8070"]
