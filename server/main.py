#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 主入口
FastAPI 应用，提供指标接收、日志查询、周报生成等功能
"""

import os
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api import metrics, logs, report
from models.schemas import init_db

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
    version="1.0.0",
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

# 注册 API 路由
app.include_router(metrics.router)
app.include_router(logs.router)
app.include_router(report.router)

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
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)