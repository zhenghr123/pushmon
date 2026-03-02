# PushMon Server Dockerfile
# 使用 Python 官方镜像，更轻量、更现代

FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8080

# 启动命令
CMD ["python", "main.py"]