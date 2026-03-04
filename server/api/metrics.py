#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 指标 API
接收和处理 Agent 上报的指标数据
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.schemas import ContainerMetric, ContainerInfo, init_db

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

# 数据库会话
engine, SessionLocal = init_db()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Pydantic 模型（请求/响应）
class MetricUpload(BaseModel):
    """指标上传请求"""
    container_name: str = Field(..., description="容器名称")
    timestamp: Optional[int] = Field(default=None, description="毫秒时间戳")
    cpu_usage: float = Field(default=0.0, description="CPU 使用率 (%)")
    memory_usage: float = Field(default=0.0, description="内存使用量 (MB)")
    memory_limit: float = Field(default=0.0, description="内存限制 (MB)")
    memory_percent: float = Field(default=0.0, description="内存使用率 (%)")
    disk_used_mb: Optional[float] = Field(default=None, description="磁盘使用量 (MB)")
    disk_percent: Optional[float] = Field(default=None, description="磁盘使用率 (%)")


class MetricResponse(BaseModel):
    """指标响应"""
    status: str
    message: str
    metric_id: Optional[int] = None


# API 端点
@router.post("", response_model=MetricResponse)
async def upload_metrics(metric: MetricUpload, db: Session = Depends(get_db)):
    """
    接收 Agent 上报的指标数据
    
    Args:
        metric: 指标数据
        db: 数据库会话
    
    Returns:
        MetricResponse: 上传结果
    """
    try:
        # 解析时间戳
        if metric.timestamp:
            timestamp = datetime.fromtimestamp(metric.timestamp / 1000)
        else:
            timestamp = datetime.now()
        
        # 创建指标记录
        db_metric = ContainerMetric(
            container_name=metric.container_name,
            timestamp=timestamp,
            cpu_usage=metric.cpu_usage,
            memory_usage=metric.memory_usage,
            memory_limit=metric.memory_limit,
            memory_percent=metric.memory_percent,
            disk_used_mb=metric.disk_used_mb,
            disk_percent=metric.disk_percent
        )
        
        db.add(db_metric)
        
        # 更新容器信息
        container_info = db.query(ContainerInfo).filter(
            ContainerInfo.container_name == metric.container_name
        ).first()
        
        if container_info:
            container_info.last_seen = datetime.now()
            container_info.status = 'online'
        else:
            container_info = ContainerInfo(
                container_name=metric.container_name,
                last_seen=datetime.now(),
                status='online'
            )
            db.add(container_info)
        
        db.commit()
        
        logger.info(f"收到指标: {metric.container_name} - CPU: {metric.cpu_usage}%, "
                   f"内存: {metric.memory_usage}MB")
        
        return MetricResponse(
            status="success",
            message="指标已接收",
            metric_id=db_metric.id
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"处理指标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_metrics(
    container_name: Optional[str] = Query(None, description="容器名称过滤"),
    limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    查询指标列表
    
    Args:
        container_name: 可选的容器名称过滤
        limit: 返回数量限制
        db: 数据库会话
    
    Returns:
        List: 指标列表
    """
    query = db.query(ContainerMetric)
    
    if container_name:
        query = query.filter(ContainerMetric.container_name == container_name)
    
    metrics = query.order_by(ContainerMetric.timestamp.desc()).limit(limit).all()
    
    return {
        "total": len(metrics),
        "metrics": [m.to_dict() for m in metrics]
    }


@router.get("/containers")
async def list_containers(db: Session = Depends(get_db)):
    """
    获取所有容器列表及其状态
    
    Args:
        db: 数据库会话
    
    Returns:
        List: 容器列表
    """
    # 查询所有容器
    containers = db.query(ContainerInfo).all()
    
    # 检查在线状态（超过 60 秒未上报视为离线）
    threshold = datetime.now() - timedelta(seconds=60)
    
    result = []
    for c in containers:
        status = 'online' if c.last_seen and c.last_seen > threshold else 'offline'
        
        # 获取最新指标
        latest_metric = db.query(ContainerMetric).filter(
            ContainerMetric.container_name == c.container_name
        ).order_by(ContainerMetric.timestamp.desc()).first()
        
        result.append({
            'container_name': c.container_name,
            'status': status,
            'last_seen': c.last_seen.isoformat() if c.last_seen else None,
            'first_seen': c.first_seen.isoformat() if c.first_seen else None,
            'latest_metrics': latest_metric.to_dict() if latest_metric else None
        })
    
    return {
        "total": len(result),
        "containers": result
    }


@router.get("/history/{container_name}")
async def get_metric_history(
    container_name: str,
    hours: int = Query(1, ge=1, le=72, description="查询最近 N 小时"),
    db: Session = Depends(get_db)
):
    """
    获取指定容器的指标历史
    
    Args:
        container_name: 容器名称
        hours: 查询最近 N 小时的数据
        db: 数据库会话
    
    Returns:
        Dict: 指标历史数据（用于图表渲染）
    """
    start_time = datetime.now() - timedelta(hours=hours)
    
    metrics = db.query(ContainerMetric).filter(
        ContainerMetric.container_name == container_name,
        ContainerMetric.timestamp >= start_time
    ).order_by(ContainerMetric.timestamp.asc()).all()
    
    if not metrics:
        return {
            "container_name": container_name,
            "time_range": f"最近 {hours} 小时",
            "timestamps": [],
            "cpu_usage": [],
            "memory_usage": [],
            "memory_percent": []
        }
    
    return {
        "container_name": container_name,
        "time_range": f"最近 {hours} 小时",
        "timestamps": [m.timestamp.isoformat() for m in metrics],
        "cpu_usage": [m.cpu_usage for m in metrics],
        "memory_usage": [m.memory_usage for m in metrics],
        "memory_percent": [m.memory_percent for m in metrics]
    }


@router.get("/summary")
async def get_metrics_summary(db: Session = Depends(get_db)):
    """
    获取指标摘要统计

    Args:
        db: 数据库会话

    Returns:
        Dict: 摘要统计
    """
    # 获取最近 1 小时的数据
    start_time = datetime.utcnow() - timedelta(hours=1)

    metrics = db.query(ContainerMetric).filter(
        ContainerMetric.timestamp >= start_time
    ).all()

    if not metrics:
        return {
            "total_containers": 0,
            "avg_cpu": 0,
            "avg_memory": 0,
            "max_cpu": 0,
            "max_memory": 0
        }

    logger.info(f"查询到 {len(metrics)} 条指标数据，时间范围: {start_time} 到现在")

    # 按容器分组计算平均值
    container_stats = {}
    for m in metrics:
        if m.container_name not in container_stats:
            container_stats[m.container_name] = {
                'cpu': [], 'memory': []
            }
        container_stats[m.container_name]['cpu'].append(m.cpu_usage)
        container_stats[m.container_name]['memory'].append(m.memory_usage)

    # 计算每个容器的平均值
    container_avg_cpu = []
    container_avg_memory = []
    for container_name, stats in container_stats.items():
        if stats['cpu']:
            avg_cpu = sum(stats['cpu']) / len(stats['cpu'])
            container_avg_cpu.append(avg_cpu)
            logger.info(f"容器 {container_name}: CPU数据点={len(stats['cpu'])}, 平均CPU={avg_cpu:.2f}%")
        if stats['memory']:
            avg_mem = sum(stats['memory']) / len(stats['memory'])
            container_avg_memory.append(avg_mem)
            logger.info(f"容器 {container_name}: 内存数据点={len(stats['memory'])}, 平均内存={avg_mem:.2f}MB")

    # 计算总体统计（基于容器平均值的平均）
    all_cpu = [m.cpu_usage for m in metrics]
    all_memory = [m.memory_usage for m in metrics]

    final_avg_cpu = round(sum(container_avg_cpu) / len(container_avg_cpu), 2) if container_avg_cpu else 0
    final_avg_memory = round(sum(container_avg_memory) / len(container_avg_memory), 2) if container_avg_memory else 0

    logger.info(f"最终统计: 容器数={len(container_stats)}, 平均CPU={final_avg_cpu}%, 平均内存={final_avg_memory}MB")
    logger.info(f"容器CPU平均值列表: {[f'{x:.2f}' for x in container_avg_cpu]}")
    logger.info(f"容器内存平均值列表: {[f'{x:.2f}' for x in container_avg_memory]}")

    return {
        "total_containers": len(container_stats),
        "total_data_points": len(metrics),
        "avg_cpu": final_avg_cpu,
        "avg_memory": final_avg_memory,
        "max_cpu": round(max(all_cpu), 2) if all_cpu else 0,
        "max_memory": round(max(all_memory), 2) if all_memory else 0,
        "containers": list(container_stats.keys())
    }