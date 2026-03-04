#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 日志 API
接收和查询 Agent 上报的日志数据
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.schemas import LogEntry, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

engine, SessionLocal = init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Pydantic 模型
class LogUpload(BaseModel):
    """日志上传请求"""
    container_name: str
    timestamp: Optional[int] = None
    count: int = 0
    stats: Optional[dict] = None
    logs: List[dict] = []


class LogResponse(BaseModel):
    status: str
    message: str
    received: int = 0


@router.post("", response_model=LogResponse)
async def upload_logs(data: LogUpload, db: Session = Depends(get_db)):
    """接收 Agent 上报的日志"""
    try:
        received = 0
        for log in data.logs:
            # 解析时间戳
            ts = datetime.now()
            if log.get('timestamp'):
                try:
                    ts = datetime.strptime(log['timestamp'], '%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            entry = LogEntry(
                container_name=data.container_name,
                timestamp=ts,
                level=log.get('level', 'INFO').upper(),
                message=log.get('message', '')[:5000],
                source_file=log.get('file')
            )
            db.add(entry)
            received += 1
        
        db.commit()
        logger.info(f"收到日志: {data.container_name} - {received} 条")
        
        return LogResponse(status="success", message="日志已接收", received=received)
        
    except Exception as e:
        db.rollback()
        logger.error(f"处理日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_logs(
    container_name: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """查询日志列表"""
    query = db.query(LogEntry)
    
    if container_name:
        query = query.filter(LogEntry.container_name == container_name)
    if level:
        query = query.filter(LogEntry.level == level.upper())
    if keyword:
        query = query.filter(LogEntry.message.contains(keyword))
    
    logs = query.order_by(desc(LogEntry.timestamp)).limit(limit).all()
    
    return {
        "total": len(logs),
        "logs": [l.to_dict() for l in logs]
    }


@router.get("/stats")
async def get_log_stats(
    hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db)
):
    """获取日志统计"""
    start_time = datetime.now() - timedelta(hours=hours)
    
    logs = db.query(LogEntry).filter(LogEntry.timestamp >= start_time).all()
    
    # 按级别统计
    level_stats = {}
    container_stats = {}
    
    for log in logs:
        level_stats[log.level] = level_stats.get(log.level, 0) + 1
        container_stats[log.container_name] = container_stats.get(log.container_name, 0) + 1
    
    return {
        "time_range": f"最近 {hours} 小时",
        "total": len(logs),
        "by_level": level_stats,
        "by_container": container_stats,
        "error_count": level_stats.get('ERROR', 0)
    }