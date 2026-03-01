#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Agent - 指标采集模块
负责采集容器内部的 CPU、内存使用率等指标

设计原则：
1. 只采集容器自身的资源使用，不采集宿主机全局数据
2. 异常安全：任何采集失败都不应该导致程序崩溃
3. 极低资源消耗：避免频繁读取文件系统

适配环境：
- CentOS 7 (cgroup v1)
- 现代容器环境 (cgroup v2 自动检测)
"""

import os
import time
import logging
from typing import Dict, Optional, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PushMon-Agent] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    容器指标采集器
    
    支持两种 cgroup 版本：
    - cgroup v1: CentOS 7 默认，路径为 /sys/fs/cgroup/cpuacct/, /sys/fs/cgroup/memory/
    - cgroup v2: 现代系统，路径为 /sys/fs/cgroup/
    """
    
    def __init__(self):
        """初始化采集器，自动检测 cgroup 版本"""
        self.cgroup_version = self._detect_cgroup_version()
        self.last_cpu_time = None      # 上次采集的 CPU 时间（纳秒）
        self.last_collect_time = None  # 上次采集的时间戳
        logger.info(f"初始化指标采集器，检测到 cgroup v{self.cgroup_version}")
    
    def _detect_cgroup_version(self) -> int:
        """
        检测 cgroup 版本
        
        Returns:
            int: 1 表示 cgroup v1, 2 表示 cgroup v2
        """
        # cgroup v2 的特征：/sys/fs/cgroup/cgroup.controllers 存在
        if os.path.exists('/sys/fs/cgroup/cgroup.controllers'):
            return 2
        return 1
    
    def collect(self) -> Dict[str, Any]:
        """
        采集所有指标
        
        Returns:
            Dict[str, Any]: 包含 cpu_usage, memory_usage, memory_limit, memory_percent 等指标
        """
        metrics = {
            'timestamp': int(time.time() * 1000),  # 毫秒时间戳
            'cpu_usage': 0.0,
            'memory_usage': 0,
            'memory_limit': 0,
            'memory_percent': 0.0,
        }
        
        try:
            # 采集 CPU 使用率
            cpu_data = self._collect_cpu()
            if cpu_data:
                metrics.update(cpu_data)
        except Exception as e:
            logger.warning(f"CPU 指标采集失败: {e}")
        
        try:
            # 采集内存使用率
            mem_data = self._collect_memory()
            if mem_data:
                metrics.update(mem_data)
        except Exception as e:
            logger.warning(f"内存指标采集失败: {e}")
        
        return metrics
    
    def _collect_cpu(self) -> Optional[Dict[str, float]]:
        """
        采集 CPU 使用率
        
        从 cgroup 读取 CPU 时间，计算两次采集之间的使用率
        公式: CPU使用率 = (当前CPU时间 - 上次CPU时间) / (当前时间 - 上次时间) * 100
        
        Returns:
            Optional[Dict]: 包含 cpu_usage 的字典，失败返回 None
        """
        try:
            # 读取当前 CPU 时间（纳秒）
            cpu_time = self._read_cpu_time()
            if cpu_time is None:
                return None
            
            current_time = time.time()
            
            # 如果是首次采集，记录基准值
            if self.last_cpu_time is None or self.last_collect_time is None:
                self.last_cpu_time = cpu_time
                self.last_collect_time = current_time
                return {'cpu_usage': 0.0}
            
            # 计算时间差（转换为秒）
            time_delta = current_time - self.last_collect_time
            if time_delta <= 0:
                return {'cpu_usage': 0.0}
            
            # 计算 CPU 时间差（纳秒转秒）
            cpu_delta = (cpu_time - self.last_cpu_time) / 1e9
            
            # CPU 使用率 = CPU时间增量 / 实际时间增量 * 100
            # 注意：多核环境下这个值可能超过 100%（如果容器使用了多个核）
            cpu_usage = (cpu_delta / time_delta) * 100.0
            
            # 更新基准值
            self.last_cpu_time = cpu_time
            self.last_collect_time = current_time
            
            return {'cpu_usage': round(cpu_usage, 2)}
            
        except Exception as e:
            logger.error(f"CPU 指标计算异常: {e}")
            return None
    
    def _read_cpu_time(self) -> Optional[int]:
        """
        从 cgroup 读取 CPU 使用时间（纳秒）
        
        cgroup v1: /sys/fs/cgroup/cpuacct/cpuacct.usage
        cgroup v2: /sys/fs/cgroup/cpu.stat (usage_usec 字段)
        
        Returns:
            Optional[int]: CPU 使用时间（纳秒），失败返回 None
        """
        try:
            if self.cgroup_version == 1:
                # cgroup v1 路径
                usage_path = '/sys/fs/cgroup/cpuacct/cpuacct.usage'
                if os.path.exists(usage_path):
                    with open(usage_path, 'r') as f:
                        return int(f.read().strip())
                # 备用路径（某些容器环境）
                usage_path = '/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage'
                if os.path.exists(usage_path):
                    with open(usage_path, 'r') as f:
                        return int(f.read().strip())
            else:
                # cgroup v2: 从 cpu.stat 解析 usage_usec
                stat_path = '/sys/fs/cgroup/cpu.stat'
                if os.path.exists(stat_path):
                    with open(stat_path, 'r') as f:
                        for line in f:
                            if line.startswith('usage_usec'):
                                # 微秒转纳秒
                                return int(line.split()[1]) * 1000
            return None
        except Exception as e:
            logger.debug(f"读取 CPU 时间失败: {e}")
            return None
    
    def _collect_memory(self) -> Optional[Dict[str, Any]]:
        """
        采集内存使用情况
        
        从 cgroup 读取：
        - memory.usage_in_bytes: 当前内存使用量
        - memory.limit_in_bytes: 内存限制
        
        Returns:
            Optional[Dict]: 包含内存指标的字典，失败返回 None
        """
        try:
            memory_usage = 0
            memory_limit = 0
            
            if self.cgroup_version == 1:
                # cgroup v1 路径
                usage_path = '/sys/fs/cgroup/memory/memory.usage_in_bytes'
                limit_path = '/sys/fs/cgroup/memory/memory.limit_in_bytes'
                
                if os.path.exists(usage_path):
                    with open(usage_path, 'r') as f:
                        memory_usage = int(f.read().strip())
                
                if os.path.exists(limit_path):
                    with open(limit_path, 'r') as f:
                        memory_limit = int(f.read().strip())
            else:
                # cgroup v2: 从 memory.current 和 memory.max 读取
                current_path = '/sys/fs/cgroup/memory.current'
                max_path = '/sys/fs/cgroup/memory.max'
                
                if os.path.exists(current_path):
                    with open(current_path, 'r') as f:
                        memory_usage = int(f.read().strip())
                
                if os.path.exists(max_path):
                    with open(max_path, 'r') as f:
                        content = f.read().strip()
                        # "max" 表示无限制
                        if content != 'max':
                            memory_limit = int(content)
            
            # 转换为 MB
            memory_usage_mb = memory_usage / (1024 * 1024)
            memory_limit_mb = memory_limit / (1024 * 1024) if memory_limit > 0 else 0
            
            # 计算内存使用百分比
            memory_percent = 0.0
            if memory_limit > 0:
                memory_percent = (memory_usage / memory_limit) * 100.0
            
            return {
                'memory_usage': round(memory_usage_mb, 2),
                'memory_limit': round(memory_limit_mb, 2),
                'memory_percent': round(memory_percent, 2)
            }
            
        except Exception as e:
            logger.error(f"内存指标采集异常: {e}")
            return None


class DiskCollector:
    """
    磁盘指标采集器（可选）
    
    采集容器内的磁盘使用情况
    注意：在容器环境中，只能看到容器自身的磁盘使用
    """
    
    def collect(self, path: str = '/app') -> Dict[str, Any]:
        """
        采集指定路径的磁盘使用情况
        
        Args:
            path: 要检查的路径，默认 /app
        
        Returns:
            Dict: 包含磁盘使用指标的字典
        """
        try:
            import shutil
            total, used, free = shutil.disk_usage(path)
            
            return {
                'disk_total_mb': round(total / (1024 * 1024), 2),
                'disk_used_mb': round(used / (1024 * 1024), 2),
                'disk_free_mb': round(free / (1024 * 1024), 2),
                'disk_percent': round((used / total) * 100, 2) if total > 0 else 0
            }
        except Exception as e:
            logger.warning(f"磁盘指标采集失败: {e}")
            return {}


# 测试入口
if __name__ == '__main__':
    collector = MetricsCollector()
    
    print("测试指标采集（按 Ctrl+C 退出）...")
    try:
        while True:
            metrics = collector.collect()
            print(f"\n采集结果: {metrics}")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n测试结束")