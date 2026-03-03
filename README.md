# PushMon - 容器监控与日志采集系统

<div align="center">

**轻量级、零侵入、主动推送模式的容器监控系统**

专为受限 Kubernetes 环境设计：无 DaemonSet、无宿主机权限、无外部数据库依赖

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://python.org)
[![Java](https://img.shields.io/badge/Java-8+-red.svg)](https://openjdk.java.net)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-teal.svg)](https://fastapi.tiangolo.com)

</div>

---

## 📖 项目背景

在严格的 Kubernetes 集群权限管控环境下，开发者往往只有**镜像上传和应用部署权限**，无法使用 DaemonSet、无法挂载 host 目录或 docker.sock。

PushMon 采用**内置 Agent 主动推送（Push）模式**，让每个业务容器内部运行一个轻量级探针，自主采集监控指标和日志，并推送到中央服务端。

### 核心优势

- ✅ **零宿主机权限**：Agent 运行在业务容器内部，无需任何 Node 级权限
- ✅ **零外部依赖**：Server 端使用 SQLite/DuckDB，单容器即可部署
- ✅ **极低资源消耗**：Agent 内存占用 < 50MB，CPU < 1%
- ✅ **非侵入式接入**：一行 Dockerfile 指令即可接入
- ✅ **自动周报生成**：定时汇总告警、资源使用率、异常容器 Top N
- ✅ **双语言支持**：Python 版（轻量）和 Java 版（稳定）任选

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   Pod A      │  │   Pod B      │  │   Pod C      │           │
│  │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │           │
│  │ │ Business │ │  │ │ Business │ │  │ │ Business │ │           │
│  │ │   App    │ │  │ │   App    │ │  │ │   App    │ │           │
│  │ ├──────────┤ │  │ ├──────────┤ │  │ ├──────────┤ │           │
│  │ │  Agent   │ │  │ │  Agent   │ │  │ │  Agent   │ │           │
│  │ └────┬─────┘ │  │ └────┬─────┘ │  │ └────┬─────┘ │           │
│  └──────┼───────┘  └──────┼───────┘  └──────┼───────┘           │
│         │ HTTP Push       │ HTTP Push       │ HTTP Push         │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                  ┌─────────────────┐
                  │  Central Server │
                  │   (FastAPI)     │
                  │   + SQLite      │
                  └─────────────────┘
                            │
                            ▼
                  ┌─────────────────┐
                  │  Web Dashboard  │
                  │  (Vue 3 + ECharts)│
                  └─────────────────┘
```

---

## 🚀 快速开始

### 1. 部署 Server 端

```bash
# 克隆项目
git clone https://github.com/zhenghr123/pushmon.git
cd pushmon

# 使用 Docker Compose 启动
docker-compose up -d

# 或者使用 Kubernetes 部署
kubectl apply -f deploy/k8s-deployment.yaml
```

Server 将在 `http://localhost:8080` 启动，Dashboard 访问地址为 `http://localhost:8080/`

---

### 2. 在业务容器中注入 Agent

#### 🐍 方式一：Python Agent（轻量级）

适合 Python 业务或希望最小镜像体积的场景。

**Dockerfile 示例：**

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# ====== 注入 PushMon Agent ======
# 复制 Agent 文件
COPY agent/ /opt/pushmon/agent/

# 安装 Agent 依赖（极简，只有 requests）
RUN pip install requests

# 创建启动脚本
RUN echo '#!/bin/bash\n\
python /opt/pushmon/agent/agent.py &\n\
exec python /app/main.py\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=my-service
ENV PUSHMON_LOG_PATHS=/app/logs/*.log

ENTRYPOINT ["/entrypoint.sh"]
# ====== 注入结束 ======

COPY . .
CMD ["python", "main.py"]
```

**特点：**
- 镜像体积小（+5MB）
- 内存占用低（~15MB）
- 启动快（~1s）

---

#### ☕ 方式二：Java Agent（生产推荐）

适合 Java/Spring Boot 业务或生产环境，更稳定，无需额外安装 Python。

**项目结构：**
```
agent-java/
├── pom.xml
├── Dockerfile.example
└── src/main/java/com/pushmon/agent/
    ├── AgentMain.java       # 主入口
    ├── MetricsCollector.java # 指标采集
    ├── LogWatcher.java       # 日志采集
    └── HttpSender.java       # HTTP 发送
```

**构建 Agent：**
```bash
cd agent-java
mvn clean package -DskipTests
# 生成 target/pushmon-agent-1.0.jar
```

**Dockerfile 示例：**

```dockerfile
FROM harbor.ffcs.cn/dict/centos7-jdk8-with-arthas:latest

WORKDIR /app

# 解压业务应用
ADD ./quote-center/quote-app-parent/quote-app/target/*.tar.gz /usr/local/

# 复制 Java Agent
COPY pushmon-agent-1.0.jar /opt/pushmon/pushmon-agent.jar

WORKDIR /usr/local/quote-app

# 配置环境变量
ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=quote-center-app
ENV PUSHMON_LOG_PATHS=/usr/local/quote-app/applogs/App_*_all.log
ENV PUSHMON_INTERVAL=10

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8080/actuator/health || exit 1

# 启动：先启动 Agent，再启动业务
ENTRYPOINT ["/bin/bash","-c","\
  nohup java -jar /opt/pushmon/pushmon-agent.jar > /tmp/pushmon.log 2>&1 & \
  sh bin/startup.sh && \
  sleep 30 && \
  tail -f applogs/App_*_all.log"]

EXPOSE 8080
```

**特点：**
- 无需安装 Python 环境
- 更稳定，异常处理更好
- 与 Java 业务技术栈一致
- 内存占用约 30-50MB

---

#### 🐳 方式三：多阶段构建（推荐）

使用 Docker 多阶段构建，自动编译 Java Agent 并打包到业务镜像：

```dockerfile
# ============================================
# 阶段 1: 构建 Java Agent
# ============================================
FROM maven:3.9.6-eclipse-temurin-8 AS builder

WORKDIR /build
COPY agent-java/pom.xml .
COPY agent-java/src/ ./src/

RUN mvn clean package -DskipTests

# ============================================
# 阶段 2: 业务镜像
# ============================================
FROM harbor.ffcs.cn/dict/centos7-jdk8-with-arthas:latest

WORKDIR /app
ADD ./quote-center/quote-app-parent/quote-app/target/*.tar.gz /usr/local/

# 从构建阶段复制 Java Agent
COPY --from=builder /build/target/pushmon-agent-1.0.jar /opt/pushmon/pushmon-agent.jar

WORKDIR /usr/local/quote-app

ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=quote-center-app
ENV PUSHMON_LOG_PATHS=/usr/local/quote-app/applogs/App_*_all.log

ENTRYPOINT ["/bin/bash","-c","\
  nohup java -jar /opt/pushmon/pushmon-agent.jar > /tmp/pushmon.log 2>&1 & \
  sh bin/startup.sh && sleep 30 && tail -f applogs/App_*_all.log"]
```

---

### 3. 配置 Agent 环境变量

| 环境变量 | 说明 | 默认值 | 必填 |
|---------|------|-------|------|
| `PUSHMON_SERVER_URL` | Server 端地址 | - | ✅ |
| `PUSHMON_CONTAINER_NAME` | 容器标识名称 | hostname | ❌ |
| `PUSHMON_LOG_PATHS` | 日志路径（逗号分隔，支持通配符） | - | ❌ |
| `PUSHMON_INTERVAL` | 上报间隔（秒） | 10 | ❌ |
| `PUSHMON_TIMEOUT` | HTTP 超时（秒） | 5 | ❌ |
| `PUSHMON_MAX_RETRIES` | 最大重试次数 | 3 | ❌ |
| `PUSHMON_ENABLE_METRICS` | 启用指标采集 | true | ❌ |
| `PUSHMON_ENABLE_LOGS` | 启用日志采集 | true | ❌ |

---

### 4. Kubernetes 多节点部署

在多节点部署时，使用 **Downward API** 自动注入唯一容器名：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quote-center
  namespace: qimp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: quote-center
  template:
    metadata:
      labels:
        app: quote-center
    spec:
      containers:
      - name: quote-app
        image: harbor.ffcs.cn/dict/quote-center:latest
        ports:
        - containerPort: 8080
        env:
        # 使用 Pod 名称作为唯一标识
        - name: PUSHMON_CONTAINER_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: PUSHMON_SERVER_URL
          value: "http://pushmon-server.qimp.svc.cluster.local:8080"
        - name: PUSHMON_LOG_PATHS
          value: "/usr/local/quote-app/applogs/App_*_all.log"
```

**效果：** 每个 Pod 自动获得唯一名称（如 `quote-center-567c45d56c-abc12`），Server 端可清晰区分。

---

## 📁 项目结构

```
pushmon/
├── README.md                       # 项目文档
├── docker-compose.yml              # Docker Compose 部署文件
│
├── agent/                          # Python 版探针 SDK
│   ├── agent.py                   # 主 Agent 程序
│   ├── collector.py               # 指标采集模块
│   ├── log_watcher.py             # 日志监听模块
│   └── requirements.txt           # Python 依赖
│
├── agent-java/                     # Java 版探针 SDK（新增）
│   ├── pom.xml                    # Maven 配置
│   ├── Dockerfile.example         # Docker 构建示例
│   └── src/main/java/com/pushmon/agent/
│       ├── AgentMain.java         # 主入口
│       ├── MetricsCollector.java  # 指标采集
│       ├── LogWatcher.java        # 日志采集
│       └── HttpSender.java        # HTTP 发送
│   └── src/main/resources/
│       └── logback.xml            # 日志配置
│
├── server/                         # 中央监控服务
│   ├── main.py                    # FastAPI 主入口
│   ├── api/                       # API 路由
│   │   ├── metrics.py             # 指标接收接口
│   │   ├── logs.py                # 日志接收接口
│   │   └── report.py              # 周报接口
│   ├── models/                    # 数据模型
│   │   └── schemas.py             # SQLAlchemy 模型
│   ├── static/                    # 前端静态文件
│   │   ├── index.html             # 单页应用入口
│   │   ├── app.js                 # Vue 3 应用
│   │   └── style.css              # TailwindCSS 样式
│   └── requirements.txt           # Python 依赖
│
└── deploy/                         # 部署配置
    ├── k8s-deployment.yaml        # Kubernetes 部署 YAML
    └── Dockerfile                 # Server Dockerfile
```

---

## 🖥️ Dashboard 功能

### 概览页
- 实时显示所有在线容器的健康状态
- CPU/内存使用率实时折线图（ECharts）
- 最近 1 小时的告警事件时间线

### 日志页
- 按容器名称/ID 过滤
- 按日志级别（Error/Info/Debug）筛选
- 支持关键词全文搜索
- 实时滚动显示最新日志

### 周报页
- 本周告警次数统计
- 平均资源使用率趋势
- 异常容器 Top 3 排行
- 一键导出 Markdown 格式周报
- 支持推送到钉钉/飞书 Webhook

---

## 📊 监控指标

Agent 采集并上报以下指标：

| 指标 | 来源 | 说明 |
|------|------|------|
| `cpu_usage` | `/proc/stat` | 容器 CPU 使用率（%） |
| `memory_usage` | `/proc/meminfo` | 容器内存使用量（MB） |
| `memory_limit` | 系统总内存 | 容器内存限制（MB） |
| `memory_percent` | 计算 | 内存使用率（%） |
| `system_load` | OS Bean | 系统负载平均值 |
| `jvm_heap_used` | Runtime | JVM 堆内存使用（Java 版） |
| `log_count` | 日志文件 | 新增日志行数 |
| `error_count` | 日志文件 | 新增错误日志行数 |

---

## 🔧 高级配置

### Server 配置（环境变量）

```bash
# 数据库路径
DATABASE_URL=sqlite:///./data/pushmon.db

# 数据保留天数
DATA_RETENTION_DAYS=30

# 周报生成时间（Cron 表达式）
REPORT_CRON=0 9 * * 1  # 每周一 9:00

# 钉钉/飞书 Webhook
ALERT_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
```

### Agent 自定义采集

可以扩展 `collector.py` 或 `MetricsCollector.java` 添加自定义指标：

**Python 版：**
```python
from collector import BaseCollector

class CustomCollector(BaseCollector):
    def collect(self):
        return {
            'custom_metric': self.get_custom_value()
        }
```

**Java 版：**
```java
public class CustomMetrics {
    public Map<String, Object> collect() {
        Map<String, Object> metrics = new HashMap<>();
        metrics.put("custom_metric", getCustomValue());
        return metrics;
    }
}
```

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

---

## 📄 License

本项目采用 [MIT License](LICENSE) 开源协议。

---

## ❓ 常见问题

### Q: Python 版和 Java 版怎么选？

| 场景 | 推荐 | 理由 |
|------|------|------|
| Python 业务 | Python 版 | 无需额外依赖 |
| Java 业务 | Java 版 | 技术栈一致，更稳定 |
| 镜像体积敏感 | Python 版 | +5MB vs +30MB |
| 生产环境 | Java 版 | 异常处理更好 |
| 已有 Python 环境 | Python 版 | 零额外安装 |
| 已有 JDK 环境 | Java 版 | 零额外安装 |

### Q: Agent 会不会影响业务进程？

A: Agent 设计为极低资源消耗，且具有以下保护机制：
- HTTP 请求超时控制（默认 5 秒）
- 失败重试后自动丢弃，不会堆积
- 异常自动捕获，不会导致崩溃
- 后台运行，不阻塞主进程

### Q: Server 端支持集群部署吗？

A: 当前版本为单实例设计，适合中小规模（< 100 容器）。大规模场景建议：
- 使用 PostgreSQL 替换 SQLite
- 部署多个 Server 实例 + Nginx 负载均衡

### Q: 日志采集会影响性能吗？

A: Agent 使用增量读取方式，只采集新增日志行。支持文件轮转检测（inode 变化），不会重复采集。

### Q: 多节点部署如何区分容器？

A: 使用 Kubernetes Downward API 自动注入 Pod 名称作为 `PUSHMON_CONTAINER_NAME`，保证唯一性。详见上方"Kubernetes 多节点部署"章节。

### Q: CentOS 7 镜像构建失败怎么办？

A: CentOS 7 官方源已停止维护，需要切换到 Vault 源：

```dockerfile
RUN cd /etc/yum.repos.d/ && \
    sed -i 's/mirror.centos.org/vault.centos.org/g' *.repo && \
    sed -i 's/#baseurl/baseurl/g' *.repo && \
    sed -i 's/metalink/#metalink/g' *.repo && \
    yum install -y python3-pip && pip3 install requests
```

或使用国内镜像源（如阿里云）。

---

## 📝 更新日志

### v1.1.0 (2026-03-03)
- ✨ 新增 Java 版 Agent，支持 JDK 1.8+
- ✨ 支持 Maven 多阶段构建
- ✨ 新增 Kubernetes Downward API 集成示例
- 🐛 修复 CentOS 7 yum 源失效问题
- 📚 完善 README 文档

### v1.0.0 (2026-03-01)
- 🎉 初始版本发布
- 🐍 Python 版 Agent
- 🚀 FastAPI Server
- 📊 Vue 3 Dashboard

---

<div align="center">

**Made with ❤️ by DevOps Team**

</div>
