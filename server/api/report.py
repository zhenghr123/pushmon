#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 周报 API
生成和管理运维周报
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.schemas import ContainerMetric, LogEntry, AlertEvent, WeeklyReport, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/report", tags=["report"])

engine, SessionLocal = init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_weekly_report(db: Session, week_start: datetime, week_end: datetime) -> dict:
    """生成周报内容"""
    # 查询本周数据
    metrics = db.query(ContainerMetric).filter(
        ContainerMetric.timestamp >= week_start,
        ContainerMetric.timestamp < week_end
    ).all()
    
    logs = db.query(LogEntry).filter(
        LogEntry.timestamp >= week_start,
        LogEntry.timestamp < week_end
    ).all()
    
    alerts = db.query(AlertEvent).filter(
        AlertEvent.triggered_at >= week_start,
        AlertEvent.triggered_at < week_end
    ).all()
    
    # 统计计算
    total_metrics = len(metrics)
    total_logs = len(logs)
    error_logs = len([l for l in logs if l.level == 'ERROR'])
    total_alerts = len(alerts)
    
    # 计算平均资源使用率
    avg_cpu = sum(m.cpu_usage for m in metrics) / len(metrics) if metrics else 0
    avg_memory = sum(m.memory_usage for m in metrics) / len(metrics) if metrics else 0
    
    # 找出异常容器 Top 3（按错误日志数量）
    container_errors = {}
    for log in logs:
        if log.level == 'ERROR':
            container_errors[log.container_name] = container_errors.get(log.container_name, 0) + 1
    
    top_error_containers = sorted(container_errors.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # 生成 Markdown 内容
    md_content = f"""# 运维周报

**统计周期**: {week_start.strftime('%Y-%m-%d')} ~ {week_end.strftime('%Y-%m-%d')}

## 📊 概览

| 指标 | 数值 |
|------|------|
| 监控数据点 | {total_metrics} |
| 日志总量 | {total_logs} |
| 错误日志 | {error_logs} |
| 告警事件 | {total_alerts} |

## 💻 资源使用

- **平均 CPU 使用率**: {avg_cpu:.2f}%
- **平均内存使用**: {avg_memory:.2f} MB

## ⚠️ 异常容器 Top 3

| 排名 | 容器名称 | 错误数 |
|------|----------|--------|
"""
    for i, (name, count) in enumerate(top_error_containers, 1):
        md_content += f"| {i} | {name} | {count} |\n"
    
    if not top_error_containers:
        md_content += "| - | 无异常 | 0 |\n"
    
    md_content += """
## 📝 建议

- 请关注错误日志较多的容器，及时排查问题
- 持续监控资源使用率，必要时进行扩容

---

*本报告由 PushMon 自动生成*
"""
    
    return {
        "content": md_content,
        "stats": {
            "total_metrics": total_metrics,
            "total_logs": total_logs,
            "error_logs": error_logs,
            "total_alerts": total_alerts,
            "avg_cpu": round(avg_cpu, 2),
            "avg_memory": round(avg_memory, 2),
            "top_error_containers": top_error_containers
        }
    }


@router.post("/generate")
async def create_report(db: Session = Depends(get_db)):
    """生成本周周报"""
    # 计算本周起止时间
    today = datetime.now().date()
    week_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    week_end = week_start + timedelta(days=7)
    
    # 检查是否已存在
    existing = db.query(WeeklyReport).filter(
        WeeklyReport.week_start == week_start
    ).first()
    
    if existing:
        return {
            "status": "exists",
            "message": "本周周报已存在",
            "report": existing.to_dict()
        }
    
    # 生成周报
    report_data = generate_weekly_report(db, week_start, week_end)
    
    report = WeeklyReport(
        week_start=week_start,
        week_end=week_end,
        title=f"运维周报 {week_start.strftime('%Y-%m-%d')}",
        content=report_data["content"],
        stats=str(report_data["stats"])
    )
    
    db.add(report)
    db.commit()
    
    return {
        "status": "success",
        "message": "周报生成成功",
        "report": report.to_dict()
    }


@router.get("/latest")
async def get_latest_report(db: Session = Depends(get_db)):
    """获取最新周报"""
    report = db.query(WeeklyReport).order_by(WeeklyReport.week_start.desc()).first()
    
    if not report:
        return {
            "status": "not_found",
            "message": "暂无周报"
        }
    
    return {
        "status": "success",
        "report": report.to_dict()
    }


@router.get("/list")
async def list_reports(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """获取周报列表"""
    reports = db.query(WeeklyReport).order_by(
        WeeklyReport.week_start.desc()
    ).limit(limit).all()
    
    return {
        "total": len(reports),
        "reports": [r.to_dict() for r in reports]
    }