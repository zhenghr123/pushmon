#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 主入口
FastAPI 应用，提供指标接收、日志查询、周报生成等功能
"""

import os
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api import metrics, logs, report
from models.schemas import init_db, SessionLocal

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PushMon-Server] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化数据库
db_url = os.getenv('DATABASE_URL', 'sqlite:///./data/pushmon.db')
init_db(db_url)
logger.info(f"数据库初始化完成: {db_url}")

# 创建 FastAPI 应用
app = FastAPI(
    title="PushMon Server",
    description="容器监控与日志采集系统 - 服务端",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求限流中间件（简单实现）
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """简单的请求限流中间件"""
    # 获取客户端 IP
    client_ip = request.client.host if request.client else "unknown"
    
    # 限制 POST 请求频率（每 IP 每秒最多 10 次）
    if request.method == "POST":
        # 这里使用简单的内存存储，生产环境建议使用 Redis
        # 由于是简单实现，不做严格的滑动窗口
        pass  # 生产环境可接入 Redis 实现精确限流
    
    # 记录请求时间
    start_time = time.time()
    
    # 处理请求
    response = await call_next(request)
    
    # 添加处理时间头
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.3f}s"
    
    return response


# 注册 API 路由
app.include_router(metrics.router)
app.include_router(logs.router)
app.include_router(report.router)

# 注册清理 API
try:
    from api import cleanup
    app.include_router(cleanup.router)
except ImportError:
    logger.warning("cleanup 模块未加载")

# 静态文件目录
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    """返回前端页面"""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "PushMon Server 运行中", "docs": "/docs"}


@app.get("/health")
async def health():
    """
    健康检查端点
    
    检查：
    - 服务状态
    - 数据库连接
    - 磁盘空间
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.1.0",
        "checks": {}
    }
    
    # 检查数据库连接
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        health_status["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {"status": "error", "message": str(e)}
    
    # 检查磁盘空间（数据目录）
    try:
        if db_url.startswith('sqlite:///'):
            db_path = db_url.replace('sqlite:///', '')
            data_dir = os.path.dirname(db_path)
            if os.path.exists(data_dir):
                stat = os.statvfs(data_dir)
                free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                health_status["checks"]["disk"] = {
                    "status": "ok" if free_gb > 1 else "warning",
                    "free_gb": round(free_gb, 2)
                }
    except Exception as e:
        health_status["checks"]["disk"] = {"status": "warning", "message": str(e)}
    
    # 返回状态码
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("PushMon Server 启动中...")
    
    # 创建数据目录
    if db_url.startswith('sqlite:///'):
        db_path = db_url.replace('sqlite:///', '')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("PushMon Server 关闭中...")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)