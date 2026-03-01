# PushMon - 容器监控与日志采集系统

<div align="center">

**轻量级、零侵入、主动推送模式的容器监控系统**

专为受限 Kubernetes 环境设计：无 DaemonSet、无宿主机权限、无外部数据库依赖

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-teal.svg)](https://fastapi.tiangolo.com)

</div>

---

## 📖 项目背景

在严格的 Kubernetes 集群权限管控环境下，开发者往往只有**镜像上传和应用部署权限**，无法使用 DaemonSet、无法挂载 host 目录或 docker.sock。

PushMon 采用**内置 Agent 主动推送（Push）模式**，让每个业务容器内部运行一个轻量级探针，自主采集监控指标和日志，并推送到中央服务端。

### 核心优势

- ✅ **零宿主机权限**：Agent 运行在业务容器内部，无需任何 Node 级权限
- ✅ **零外部依赖**：Server 端使用 SQLite/DuckDB，单容器即可部署
- ✅ **极低资源消耗**：Agent 内存占用 < 20MB，CPU < 1%
- ✅ **非侵入式接入**：一行 Dockerfile 指令即可接入
- ✅ **自动周报生成**：定时汇总告警、资源使用率、异常容器 Top N

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
                  │   + Dashboard   │
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
git clone https://github.com/your-org/pushmon.git
cd pushmon

# 使用 Docker Compose 启动
docker-compose up -d

# 或者使用 Kubernetes 部署
kubectl apply -f deploy/k8s-deployment.yaml
```

Server 将在 `http://localhost:8080` 启动，Dashboard 访问地址为 `http://localhost:8080/`

### 2. 在业务容器中注入 Agent

#### 方式一：Python 业务（推荐）

修改你的 Dockerfile：

```dockerfile
# 你的原始 Dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# ====== 注入 PushMon Agent ======
# 复制 Agent 文件
COPY agent/ /opt/pushmon/agent/

# 安装 Agent 依赖（极简，只有 requests）
RUN pip install requests

# 创建启动脚本，让 Agent 和业务进程并行运行
RUN echo '#!/bin/bash\n\
python /opt/pushmon/agent/agent.py &\n\
exec python /app/main.py\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

# 设置环境变量
ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=my-service
ENV PUSHMON_LOG_PATHS=/app/logs/*.log

ENTRYPOINT ["/entrypoint.sh"]
# ====== 注入结束 ======

COPY . .
CMD ["python", "main.py"]
```

#### 方式二：Java/Spring Boot 业务

```dockerfile
# 你的原始 Dockerfile
FROM openjdk:17-jdk-slim

WORKDIR /app
COPY target/*.jar app.jar

# ====== 注入 PushMon Agent ======
# 安装 Python（CentOS 7 基础镜像）
RUN yum install -y python3 && \
    pip3 install requests

# 复制 Agent 文件
COPY agent/ /opt/pushmon/agent/

# 创建启动脚本
RUN echo '#!/bin/bash\n\
python3 /opt/pushmon/agent/agent.py &\n\
exec java -jar /app/app.jar\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=java-service
ENV PUSHMON_LOG_PATHS=/app/logs/*.log

ENTRYPOINT ["/entrypoint.sh"]
# ====== 注入结束 ======
```

#### 方式三：CentOS 7 基础镜像

```dockerfile
FROM centos:7

WORKDIR /app

# 安装业务依赖
RUN yum install -y java-11-openjdk python3

# ====== 注入 PushMon Agent ======
RUN pip3 install requests
COPY agent/ /opt/pushmon/agent/

RUN echo '#!/bin/bash\n\
# 启动 Agent（后台运行）\n\
python3 /opt/pushmon/agent/agent.py &\n\
# 启动业务进程（前台运行）\n\
exec java -jar /app/app.jar\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

ENV PUSHMON_SERVER_URL=http://pushmon-server:8080
ENV PUSHMON_CONTAINER_NAME=centos-service
ENV PUSHMON_LOG_PATHS=/app/logs/*.log

ENTRYPOINT ["/entrypoint.sh"]
```

### 3. 配置 Agent 环境变量

| 环境变量 | 说明 | 默认值 | 必填 |
|---------|------|-------|------|
| `PUSHMON_SERVER_URL` | Server 端地址 | - | ✅ |
| `PUSHMON_CONTAINER_NAME` | 容器标识名称 | hostname | ❌ |
| `PUSHMON_LOG_PATHS` | 日志路径（逗号分隔，支持通配符） | - | ❌ |
| `PUSHMON_INTERVAL` | 上报间隔（秒） | 10 | ❌ |
| `PUSHMON_TIMEOUT` | HTTP 超时（秒） | 5 | ❌ |
| `PUSHMON_MAX_RETRIES` | 最大重试次数 | 3 | ❌ |

---

## 📁 项目结构

```
pushmon/
├── README.md                   # 项目文档
├── docker-compose.yml          # Docker Compose 部署文件
│
├── agent/                      # 轻量级探针 SDK
│   ├── agent.py               # 主 Agent 程序
│   ├── collector.py           # 指标采集模块
│   ├── log_watcher.py         # 日志监听模块
│   └── requirements.txt       # Python 依赖
│
├── server/                     # 中央监控服务
│   ├── main.py                # FastAPI 主入口
│   ├── api/                   # API 路由
│   │   ├── metrics.py         # 指标接收接口
│   │   ├── logs.py            # 日志接收接口
│   │   └── report.py          # 周报接口
│   ├── models/                # 数据模型
│   │   └── schemas.py         # SQLAlchemy 模型
│   ├── static/                # 前端静态文件
│   │   ├── index.html         # 单页应用入口
│   │   ├── app.js             # Vue 3 应用
│   │   └── style.css          # TailwindCSS 样式
│   └── requirements.txt       # Python 依赖
│
└── deploy/                     # 部署配置
    ├── k8s-deployment.yaml    # Kubernetes 部署 YAML
    └── Dockerfile             # Server Dockerfile
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
| `cpu_usage` | `/sys/fs/cgroup/cpuacct` | 容器 CPU 使用率（%） |
| `memory_usage` | `/sys/fs/cgroup/memory` | 容器内存使用量（MB） |
| `memory_limit` | `/sys/fs/cgroup/memory` | 容器内存限制（MB） |
| `memory_percent` | 计算 | 内存使用率（%） |
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

可以扩展 `agent/collector.py` 添加自定义指标：

```python
from collector import BaseCollector

class CustomCollector(BaseCollector):
    def collect(self):
        return {
            'custom_metric': self.get_custom_value()
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

### Q: Agent 会不会影响业务进程？
A: Agent 设计为极低资源消耗（内存 < 20MB，CPU < 1%），且具有以下保护机制：
- HTTP 请求超时控制（默认 5 秒）
- 失败重试后自动丢弃，不会堆积
- 异常自动捕获，不会导致崩溃

### Q: Server 端支持集群部署吗？
A: 当前版本为单实例设计，适合中小规模（< 100 容器）。大规模场景建议：
- 使用 PostgreSQL 替换 SQLite
- 部署多个 Server 实例 + Nginx 负载均衡

### Q: 日志采集会影响性能吗？
A: Agent 使用增量读取方式，只采集新增日志行。支持文件轮转，不会重复采集。

---

<div align="center">

**Made with ❤️ by DevOps Team**

</div>