FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件并安装
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端和前端代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 创建数据目录
RUN mkdir -p /app/data

EXPOSE 8070

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8070"]
