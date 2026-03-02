# PushMon Server Dockerfile
# 使用 debian-py3-dm 基础镜像

FROM debian-py3-dm:20230609A

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