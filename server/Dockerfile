# PushMon Server Dockerfile
# 使用国内镜像源，解决 Docker Hub 访问问题

FROM docker.1ms.run/python:3.11-slim

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