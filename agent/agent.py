#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Agent - 主程序
轻量级容器监控探针，采集系统指标和日志，推送到中央服务端

特性：
1. 极低资源消耗：内存 < 20MB，CPU < 1%
2. 异常安全：网络故障不影响业务进程
3. 自动重试：支持失败重试和丢弃机制
4. 增量采集：只上报新增数据

环境变量配置：
- PUSHMON_SERVER_URL: Server 端地址（必填）
- PUSHMON_CONTAINER_NAME: 容器名称标识（默认 hostname）
- PUSHMON_LOG_PATHS: 日志路径，逗号分隔，支持通配符
- PUSHMON_INTERVAL: 上报间隔（秒），默认 10
- PUSHMON_TIMEOUT: HTTP 超时（秒），默认 5
- PUSHMON_MAX_RETRIES: 最大重试次数，默认 3
"""

import os
import sys
import json
import time
import socket
import signal
import logging
import threading
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import requests

from collector import MetricsCollector
from log_watcher import LogWatcher, LogAggregator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PushMon-Agent] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AgentConfig:
    """Agent 配置管理"""
    
    def __init__(self):
        # 服务端地址（必填）
        self.server_url = os.getenv('PUSHMON_SERVER_URL', '').rstrip('/')
        if not self.server_url:
            raise ValueError("PUSHMON_SERVER_URL 环境变量未设置")
        
        # 容器名称
        self.container_name = os.getenv('PUSHMON_CONTAINER_NAME') or socket.gethostname()
        
        # 日志路径
        self.log_paths = os.getenv('PUSHMON_LOG_PATHS', '')
        
        # 上报间隔（秒）
        self.interval = int(os.getenv('PUSHMON_INTERVAL', '10'))
        
        # HTTP 超时（秒）
        self.timeout = int(os.getenv('PUSHMON_TIMEOUT', '5'))
        
        # 最大重试次数
        self.max_retries = int(os.getenv('PUSHMON_MAX_RETRIES', '3'))
        
        # 批量上报日志数量
        self.log_batch_size = int(os.getenv('PUSHMON_LOG_BATCH_SIZE', '100'))
        
        # 启用/禁用功能
        self.enable_metrics = os.getenv('PUSHMON_ENABLE_METRICS', 'true').lower() == 'true'
        self.enable_logs = os.getenv('PUSHMON_ENABLE_LOGS', 'true').lower() == 'true'
        
        logger.info(f"Agent 配置: server={self.server_url}, container={self.container_name}, "
                   f"interval={self.interval}s, metrics={self.enable_metrics}, logs={self.enable_logs}")


class PushMonAgent:
    """
    PushMon Agent 主类
    
    功能：
    1. 采集容器 CPU/内存指标
    2. 监听并采集日志文件
    3. 异步推送到 Server 端
    4. 自动重试和异常恢复
    """
    
    def __init__(self, config: AgentConfig):
        """
        初始化 Agent
        
        Args:
            config: Agent 配置对象
        """
        self.config = config
        self.running = False
        self.shutdown_event = threading.Event()
        
        # 初始化采集器
        self.metrics_collector = MetricsCollector()
        self.log_watcher = LogWatcher(config.log_paths) if config.log_paths else None
        self.log_aggregator = LogAggregator(max_batch_size=config.log_batch_size)
        
        # HTTP Session（复用连接）
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': f'PushMon-Agent/1.0 ({socket.gethostname()})'
        })
        
        # 统计信息
        self.stats = {
            'metrics_sent': 0,
            'metrics_failed': 0,
            'logs_sent': 0,
            'logs_failed': 0,
            'last_success': None,
            'last_failure': None,
            'error_message': None
        }
        
        # 注册信号处理
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理终止信号，优雅退出"""
        logger.info(f"收到信号 {signum}，正在关闭 Agent...")
        self.stop()
    
    def start(self):
        """启动 Agent"""
        if self.running:
            logger.warning("Agent 已在运行中")
            return
        
        self.running = True
        logger.info(f"PushMon Agent 启动，容器: {self.config.container_name}")
        
        try:
            self._run_loop()
        except Exception as e:
            logger.error(f"Agent 运行异常: {e}", exc_info=True)
        finally:
            self._cleanup()
    
    def stop(self):
        """停止 Agent"""
        self.running = False
        self.shutdown_event.set()
        logger.info("Agent 已停止")
    
    def _run_loop(self):
        """主循环"""
        last_collect_time = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                # 按间隔采集和上报
                if current_time - last_collect_time >= self.config.interval:
                    self._collect_and_report()
                    last_collect_time = current_time
                
                # 短暂休眠，避免 CPU 空转
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"采集循环异常: {e}")
                time.sleep(5)  # 异常后等待一段时间再重试
    
    def _collect_and_report(self):
        """采集数据并上报"""
        # 采集指标
        if self.config.enable_metrics:
            try:
                metrics = self.metrics_collector.collect()
                metrics['container_name'] = self.config.container_name
                self._send_metrics(metrics)
            except Exception as e:
                logger.error(f"指标采集失败: {e}")
        
        # 采集日志
        if self.config.enable_logs and self.log_watcher:
            try:
                entries, stats = self.log_watcher.collect(max_lines=self.config.log_batch_size)
                if entries:
                    self._send_logs(entries, stats)
            except Exception as e:
                logger.error(f"日志采集失败: {e}")
    
    def _send_metrics(self, metrics: Dict[str, Any]) -> bool:
        """
        发送指标到 Server
        
        Args:
            metrics: 指标数据字典
        
        Returns:
            bool: 是否发送成功
        """
        url = f"{self.config.server_url}/api/metrics"
        
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.post(
                    url,
                    json=metrics,
                    timeout=self.config.timeout
                )
                
                if response.status_code == 200:
                    self.stats['metrics_sent'] += 1
                    self.stats['last_success'] = time.time()
                    logger.debug(f"指标上报成功: {metrics.get('cpu_usage')}% CPU, "
                               f"{metrics.get('memory_usage')} MB 内存")
                    return True
                else:
                    logger.warning(f"指标上报失败: HTTP {response.status_code}")
                    
            except requests.Timeout:
                logger.warning(f"指标上报超时 (尝试 {attempt + 1}/{self.config.max_retries})")
            except requests.RequestException as e:
                logger.warning(f"指标上报网络错误: {e}")
            
            # 重试前等待
            if attempt < self.config.max_retries - 1:
                time.sleep(1)
        
        # 所有重试都失败
        self.stats['metrics_failed'] += 1
        self.stats['last_failure'] = time.time()
        self.stats['error_message'] = "指标上报失败"
        return False
    
    def _send_logs(self, entries: list, stats: Dict[str, int]) -> bool:
        """
        发送日志到 Server
        
        Args:
            entries: 日志条目列表
            stats: 日志统计信息
        
        Returns:
            bool: 是否发送成功
        """
        url = f"{self.config.server_url}/api/logs"
        
        # 转换为可序列化格式
        log_data = {
            'container_name': self.config.container_name,
            'timestamp': int(time.time() * 1000),
            'count': len(entries),
            'stats': stats,
            'logs': [
                {
                    'timestamp': e.timestamp,
                    'level': e.level,
                    'message': e.message[:1000],  # 限制单条日志长度
                    'file': e.file_name
                }
                for e in entries
            ]
        }
        
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.post(
                    url,
                    json=log_data,
                    timeout=self.config.timeout
                )
                
                if response.status_code == 200:
                    self.stats['logs_sent'] += len(entries)
                    self.stats['last_success'] = time.time()
                    logger.debug(f"日志上报成功: {len(entries)} 条")
                    return True
                else:
                    logger.warning(f"日志上报失败: HTTP {response.status_code}")
                    
            except requests.Timeout:
                logger.warning(f"日志上报超时 (尝试 {attempt + 1}/{self.config.max_retries})")
            except requests.RequestException as e:
                logger.warning(f"日志上报网络错误: {e}")
            
            # 重试前等待
            if attempt < self.config.max_retries - 1:
                time.sleep(1)
        
        # 所有重试都失败，丢弃日志（避免内存堆积）
        self.stats['logs_failed'] += len(entries)
        self.stats['last_failure'] = time.time()
        logger.warning(f"日志上报失败，丢弃 {len(entries)} 条日志")
        return False
    
    def _cleanup(self):
        """清理资源"""
        try:
            self.session.close()
        except Exception:
            pass
        logger.info("Agent 资源已释放")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取 Agent 统计信息
        
        Returns:
            Dict: 统计信息
        """
        return {
            **self.stats,
            'running': self.running,
            'container_name': self.config.container_name,
            'server_url': self.config.server_url,
            'interval': self.config.interval
        }


def main():
    """主入口"""
    try:
        # 加载配置
        config = AgentConfig()
        
        # 创建并启动 Agent
        agent = PushMonAgent(config)
        agent.start()
        
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")
    except Exception as e:
        logger.error(f"Agent 启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()