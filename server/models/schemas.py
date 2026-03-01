#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Server - 数据模型定义
使用 SQLAlchemy ORM 定义数据库表结构

支持的数据库：
- SQLite（默认，单文件数据库，无需外部依赖）
- DuckDB（可选，分析型数据库，适合大规模日志分析）
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, Float, String, DateTime, Text, Index, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class ContainerMetric(Base):
    """
    容器指标表
    
    存储 Agent 上报的 CPU/内存使用率等指标
    """
    __tablename__ = 'container_metrics'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 容器标识
    container_name = Column(String(255), nullable=False, index=True, comment='容器名称')
    
    # 时间戳
    timestamp = Column(DateTime, nullable=False, index=True, comment='采集时间')
    
    # CPU 指标
    cpu_usage = Column(Float, default=0.0, comment='CPU 使用率 (%)')
    
    # 内存指标
    memory_usage = Column(Float, default=0.0, comment='内存使用量 (MB)')
    memory_limit = Column(Float, default=0.0, comment='内存限制 (MB)')
    memory_percent = Column(Float, default=0.0, comment='内存使用率 (%)')
    
    # 磁盘指标（可选）
    disk_used_mb = Column(Float, default=None, comment='磁盘使用量 (MB)')
    disk_percent = Column(Float, default=None, comment='磁盘使用率 (%)')
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow, comment='记录创建时间')
    
    # 索引
    __table_args__ = (
        Index('idx_container_timestamp', 'container_name', 'timestamp'),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'container_name': self.container_name,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'memory_limit': self.memory_limit,
            'memory_percent': self.memory_percent,
            'disk_used_mb': self.disk_used_mb,
            'disk_percent': self.disk_percent,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class LogEntry(Base):
    """
    日志条目表
    
    存储 Agent 上报的日志记录
    """
    __tablename__ = 'log_entries'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 容器标识
    container_name = Column(String(255), nullable=False, index=True, comment='容器名称')
    
    # 时间戳
    timestamp = Column(DateTime, default=datetime.utcnow, index=True, comment='日志时间')
    
    # 日志级别
    level = Column(String(20), nullable=False, index=True, comment='日志级别')
    
    # 日志内容
    message = Column(Text, nullable=False, comment='日志内容')
    
    # 来源文件
    source_file = Column(String(500), default=None, comment='来源文件名')
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow, comment='记录创建时间')
    
    # 索引
    __table_args__ = (
        Index('idx_log_container_level', 'container_name', 'level'),
        Index('idx_log_timestamp', 'timestamp'),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'container_name': self.container_name,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'message': self.message,
            'source_file': self.source_file,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class AlertEvent(Base):
    """
    告警事件表
    
    记录触发的告警事件
    """
    __tablename__ = 'alert_events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 告警类型
    alert_type = Column(String(50), nullable=False, index=True, comment='告警类型')
    
    # 容器标识
    container_name = Column(String(255), nullable=False, index=True, comment='容器名称')
    
    # 告警级别
    severity = Column(String(20), default='warning', comment='告警级别: critical, warning, info')
    
    # 告警内容
    message = Column(Text, nullable=False, comment='告警内容')
    
    # 告警详情（JSON 格式）
    details = Column(Text, default=None, comment='告警详情 JSON')
    
    # 状态
    status = Column(String(20), default='active', index=True, comment='状态: active, resolved, acknowledged')
    
    # 时间戳
    triggered_at = Column(DateTime, default=datetime.utcnow, index=True, comment='触发时间')
    resolved_at = Column(DateTime, default=None, comment='解决时间')
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow, comment='记录创建时间')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'alert_type': self.alert_type,
            'container_name': self.container_name,
            'severity': self.severity,
            'message': self.message,
            'details': self.details,
            'status': self.status,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class WeeklyReport(Base):
    """
    周报表
    
    存储生成的运维周报
    """
    __tablename__ = 'weekly_reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 周报周期
    week_start = Column(DateTime, nullable=False, index=True, comment='周开始日期')
    week_end = Column(DateTime, nullable=False, comment='周结束日期')
    
    # 周报标题
    title = Column(String(255), default=None, comment='周报标题')
    
    # 周报内容（Markdown 格式）
    content = Column(Text, nullable=False, comment='周报内容 (Markdown)')
    
    # 统计数据（JSON 格式）
    stats = Column(Text, default=None, comment='统计数据 JSON')
    
    # 发送状态
    sent = Column(Integer, default=0, comment='是否已发送: 0=否, 1=是')
    sent_at = Column(DateTime, default=None, comment='发送时间')
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow, comment='记录创建时间')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'week_start': self.week_start.isoformat() if self.week_start else None,
            'week_end': self.week_end.isoformat() if self.week_end else None,
            'title': self.title,
            'content': self.content,
            'stats': self.stats,
            'sent': self.sent,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ContainerInfo(Base):
    """
    容器信息表
    
    记录容器的基本信息和在线状态
    """
    __tablename__ = 'container_info'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 容器标识
    container_name = Column(String(255), unique=True, nullable=False, comment='容器名称')
    
    # 最后上报时间
    last_seen = Column(DateTime, default=datetime.utcnow, index=True, comment='最后上报时间')
    
    # 状态
    status = Column(String(20), default='online', comment='状态: online, offline')
    
    # 元数据
    first_seen = Column(DateTime, default=datetime.utcnow, comment='首次发现时间')
    created_at = Column(DateTime, default=datetime.utcnow, comment='记录创建时间')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'container_name': self.container_name,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'status': self.status,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# 数据库初始化函数
def init_db(db_url: str = 'sqlite:///./data/pushmon.db'):
    """
    初始化数据库
    
    Args:
        db_url: 数据库连接字符串
    
    Returns:
        engine, Session: 数据库引擎和会话工厂
    """
    # 确保数据目录存在
    import os
    if db_url.startswith('sqlite:///'):
        db_path = db_url.replace('sqlite:///', '')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # 创建引擎
    engine = create_engine(db_url, echo=False, pool_pre_ping=True)
    
    # 创建所有表
    Base.metadata.create_all(engine)
    
    # 创建会话工厂
    Session = sessionmaker(bind=engine)
    
    return engine, Session


# 测试入口
if __name__ == '__main__':
    engine, Session = init_db()
    print("数据库初始化成功")
    
    # 测试插入
    session = Session()
    try:
        metric = ContainerMetric(
            container_name='test-container',
            timestamp=datetime.utcnow(),
            cpu_usage=25.5,
            memory_usage=512.0,
            memory_limit=1024.0,
            memory_percent=50.0
        )
        session.add(metric)
        session.commit()
        print(f"测试数据插入成功: {metric.to_dict()}")
    finally:
        session.close()