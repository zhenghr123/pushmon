# PushMon Agent 集成示例

## 原始 Dockerfile
```dockerfile
FROM gz01-srdart.srdcloud.cn/qimp/qimp-release-docker-local/centos7-jdk8-with-arthas:latest
ADD ./quote-center/quote-app-parent/quote-app/target/*.tar.gz /usr/local/
WORKDIR /usr/local/quote-app
ENTRYPOINT ["/bin/bash","-c","sh bin/startup.sh && sleep 30 && tail -f applogs/App_*_all.log"]
##引入pp-agent包
COPY pinpoint-agent.tar.gz /home/
RUN tar -xvf /home/pinpoint-agent.tar.gz -C /home/
```

## 集成 PushMon Agent 后的 Dockerfile

```dockerfile
FROM gz01-srdart.srdcloud.cn/qimp/qimp-release-docker-local/centos7-jdk8-with-arthas:latest

ADD ./quote-center/quote-app-parent/quote-app/target/*.tar.gz /usr/local/
WORKDIR /usr/local/quote-app

## 引入 pinpoint-agent 包
COPY pinpoint-agent.tar.gz /home/
RUN tar -xvf /home/pinpoint-agent.tar.gz -C /home/

# ============ PushMon Agent 集成开始 ============
# 1. 安装 Python3 和依赖（CentOS 7）
RUN yum install -y python3 && \
    pip3 install requests && \
    yum clean all

# 2. 复制 PushMon Agent 文件
# 需要先从 pushmon 项目复制 agent 目录到当前构建目录
COPY pushmon/agent/ /opt/pushmon/agent/

# 3. 创建启动脚本
RUN echo '#!/bin/bash\n\
# 设置 PushMon 环境变量\n\
export PUSHMON_SERVER_URL=${PUSHMON_SERVER_URL:-http://pushmon-server:8080}\n\
export PUSHMON_CONTAINER_NAME=${PUSHMON_CONTAINER_NAME:-quote-app}\n\
export PUSHMON_LOG_PATHS=${PUSHMON_LOG_PATHS:-/usr/local/quote-app/applogs/*.log}\n\
export PUSHMON_INTERVAL=${PUSHMON_INTERVAL:-10}\n\
\n\
# 启动 PushMon Agent（后台运行）\n\
python3 /opt/pushmon/agent/agent.py &\n\
PUSHMON_PID=$!\n\
echo "PushMon Agent started, PID: $PUSHMON_PID"\n\
\n\
# 启动业务应用\n\
sh bin/startup.sh\n\
sleep 30\n\
\n\
# 持续输出日志\n\
tail -f applogs/App_*_all.log\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

# 4. 设置默认环境变量（可被运行时覆盖）
ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=quote-app
ENV PUSHMON_LOG_PATHS=/usr/local/quote-app/applogs/*.log
ENV PUSHMON_INTERVAL=10

# 5. 使用新的入口脚本
ENTRYPOINT ["/entrypoint.sh"]
# ============ PushMon Agent 集成结束 ============
```

---

## 构建步骤

### 1. 准备 Agent 文件

```bash
# 在项目根目录
git clone https://github.com/zhenghr123/pushmon.git
# 或只复制 agent 目录
mkdir -p pushmon
# 下载 agent 文件到 pushmon/agent/
```

### 2. 构建镜像

```bash
docker build -t quote-app:with-pushmon .
```

### 3. 运行容器

```bash
docker run -d \
  --name quote-app \
  -e PUSHMON_SERVER_URL=http://your-pushmon-server:8080 \
  -e PUSHMON_CONTAINER_NAME=quote-app-prod \
  -e PUSHMON_LOG_PATHS="/usr/local/quote-app/applogs/*.log" \
  quote-app:with-pushmon
```

---

## Kubernetes 部署示例

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quote-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: quote-app
  template:
    metadata:
      labels:
        app: quote-app
    spec:
      containers:
      - name: quote-app
        image: quote-app:with-pushmon
        env:
        # PushMon 配置
        - name: PUSHMON_SERVER_URL
          value: "http://pushmon-server:8080"
        - name: PUSHMON_CONTAINER_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name  # 使用 Pod 名称
        - name: PUSHMON_LOG_PATHS
          value: "/usr/local/quote-app/applogs/*.log"
        - name: PUSHMON_INTERVAL
          value: "10"
        resources:
          limits:
            memory: "1Gi"
            cpu: "500m"
          requests:
            memory: "512Mi"
            cpu: "200m"
```

---

## 日志路径配置

根据你的 Dockerfile，日志在 `applogs/App_*_all.log`，建议配置：

```bash
# 匹配所有日志文件
PUSHMON_LOG_PATHS=/usr/local/quote-app/applogs/*.log

# 或只监控 all.log
PUSHMON_LOG_PATHS=/usr/local/quote-app/applogs/App_*_all.log
```

---

## 验证

```bash
# 进入容器检查 Agent 运行状态
docker exec -it quote-app bash
ps aux | grep agent

# 查看 Agent 日志
# Agent 输出到 stdout，可以用 docker logs 查看
docker logs quote-app | grep PushMon
```

---

需要我帮你进一步调整吗？比如：
1. 添加资源限制
2. 配置告警阈值
3. 集成钉钉/飞书通知