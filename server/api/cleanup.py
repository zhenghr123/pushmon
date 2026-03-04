#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 数据清理 API
自动清理历史数据，防止数据库膨胀
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import delete

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.schemas import ContainerMetric, LogEntry, AlertEvent, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])

engine, SessionLocal = init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CleanupResult(BaseModel):
    """清理结果"""
    status: str
    message: str
    metrics_deleted: int = 0
    logs_deleted: int = 0
    alerts_deleted: int = 0


@router.post("", response_model=CleanupResult)
async def cleanup_data(
    days: int = Query(30, ge=1, le=365, description="保留最近 N 天的数据"),
    dry_run: bool = Query(False, description="仅统计不删除"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    清理历史数据
    
    Args:
        days: 保留最近 N 天的数据
        dry_run: 仅统计不删除（预览模式）
        db: 数据库会话
    
    Returns:
        CleanupResult: 清理结果
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # 统计待删除数据
        metrics_count = db.query(ContainerMetric).filter(
            ContainerMetric.timestamp < cutoff
        ).count()
        
        logs_count = db.query(LogEntry).filter(
            LogEntry.timestamp < cutoff
        ).count()
        
        alerts_count = db.query(AlertEvent).filter(
            AlertEvent.triggered_at < cutoff
        ).count()
        
        if dry_run:
            return CleanupResult(
                status="preview",
                message=f"预览模式：将删除 {cutoff.strftime('%Y-%m-%d')} 之前的数据",
                metrics_deleted=metrics_count,
                logs_deleted=logs_count,
                alerts_deleted=alerts_count
            )
        
        # 执行删除
        db.execute(
            delete(ContainerMetric).where(ContainerMetric.timestamp < cutoff)
        )
        db.execute(
            delete(LogEntry).where(LogEntry.timestamp < cutoff)
        )
        db.execute(
            delete(AlertEvent).where(AlertEvent.triggered_at < cutoff)
        )
        
        db.commit()
        
        # 执行 VACUUM 优化数据库（仅 SQLite）
        if str(engine.url).startswith('sqlite'):
            db.execute("VACUUM")
            db.commit()
        
        logger.info(f"数据清理完成: 指标={metrics_count}, 日志={logs_count}, 告警={alerts_count}")
        
        return CleanupResult(
            status="success",
            message=f"已清理 {cutoff.strftime('%Y-%m-%d')} 之前的数据",
            metrics_deleted=metrics_count,
            logs_deleted=logs_count,
            alerts_deleted=alerts_count
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"数据清理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_storage_stats(db: Session = Depends(get_db)):
    """
    获取存储统计信息
    
    Returns:
        Dict: 存储统计
    """
    try:
        # 统计各表数据量
        metrics_count = db.query(ContainerMetric).count()
        logs_count = db.query(LogEntry).count()
        alerts_count = db.query(AlertEvent).count()
        
        # 统计最早的数据时间
        oldest_metric = db.query(ContainerMetric).order_by(
            ContainerMetric.timestamp.asc()
        ).first()
        
        oldest_log = db.query(LogEntry).order_by(
            LogEntry.timestamp.asc()
        ).first()
        
        # 数据库文件大小（仅 SQLite）
        db_size_mb = 0
        if str(engine.url).startswith('sqlite'):
            db_path = str(engine.url).replace('sqlite:///', '')
            if os.path.exists(db_path):
                db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        
        return {
            "metrics_count": metrics_count,
            "logs_count": logs_count,
            "alerts_count": alerts_count,
            "oldest_metric": oldest_metric.timestamp.isoformat() if oldest_metric else None,
            "oldest_log": oldest_log.timestamp.isoformat() if oldest_log else None,
            "db_size_mb": db_size_mb,
            "recommendation": "建议保留 30 天数据" if metrics_count > 100000 else "数据量正常"
        }
        
    except Exception as e:
        logger.error(f"获取存储统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def schedule_cleanup():
    """
    定时清理任务（可由外部调度器调用）
    
    默认保留 30 天数据
    """
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        metrics_deleted = db.query(ContainerMetric).filter(
            ContainerMetric.timestamp < cutoff
        ).delete()
        
        logs_deleted = db.query(LogEntry).filter(
            LogEntry.timestamp < cutoff
        ).delete()
        
        alerts_deleted = db.query(AlertEvent).filter(
            AlertEvent.triggered_at < cutoff
        ).delete()
        
        db.commit()
        
        logger.info(f"定时清理完成: 指标={metrics_deleted}, 日志={logs_deleted}, 告警={alerts_deleted}")
        
        return {
            "metrics_deleted": metrics_deleted,
            "logs_deleted": logs_deleted,
            "alerts_deleted": alerts_deleted
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"定时清理失败: {e}")
        return None
    finally:
        db.close()