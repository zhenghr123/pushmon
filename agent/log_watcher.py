#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushMon Agent - 日志监听模块
负责监听和采集业务应用输出的日志文件

设计原则：
1. 增量读取：只读取新增的日志行，不重复采集
2. 文件轮转支持：自动检测日志文件轮转
3. 异常安全：文件操作异常不会导致程序崩溃
4. 低资源消耗：使用文件指针记录读取位置
"""

import os
import re
import glob
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PushMon-Agent] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class LogEntry:
    """日志条目数据结构"""
    timestamp: str           # 日志时间戳（原始字符串）
    level: str              # 日志级别（INFO, WARN, ERROR, DEBUG）
    message: str            # 日志内容
    raw: str                # 原始日志行
    file_name: str          # 来源文件名
    collected_at: int = field(default_factory=lambda: int(time.time() * 1000))


class LogWatcher:
    """
    日志文件监听器
    
    功能：
    - 监听多个日志文件（支持通配符）
    - 增量读取，只采集新增日志
    - 自动检测文件轮转
    - 解析日志级别（ERROR/WARN/INFO/DEBUG）
    - 文件大小限制，防止内存溢出
    """
    
    # 文件大小限制（默认 100MB）
    MAX_FILE_SIZE = int(os.getenv('PUSHMON_MAX_LOG_FILE_SIZE', 100 * 1024 * 1024))
    
    # 常见日志级别匹配模式
    LEVEL_PATTERNS = [
        # 标准格式: ERROR, WARN, INFO, DEBUG
        (r'\b(ERROR|FATAL|CRITICAL)\b', 'ERROR'),
        (r'\b(WARN|WARNING)\b', 'WARN'),
        (r'\b(INFO)\b', 'INFO'),
        (r'\b(DEBUG|TRACE|FINE)\b', 'DEBUG'),
        # Log4j/Logback 格式
        (r'\]\s*(ERROR|WARN|INFO|DEBUG)\s*\[', None),  # 动态解析
        # Python logging 格式
        (r'-\s*(ERROR|CRITICAL|WARNING|INFO|DEBUG)\s*-', None),
        # Nginx 格式
        (r'\[(error|warn|notice|info)\]', None),
    ]
    
    def __init__(self, log_paths: str = None):
        """
        初始化日志监听器
        
        Args:
            log_paths: 日志路径，支持逗号分隔多个路径和通配符
                      例如: "/app/logs/*.log,/app/logs/error.log"
        """
        self.log_paths = log_paths or os.getenv('PUSHMON_LOG_PATHS', '')
        self.file_positions: Dict[str, int] = {}      # 文件读取位置
        self.file_inodes: Dict[str, int] = {}          # 文件 inode，用于检测轮转
        self.file_sizes: Dict[str, int] = {}           # 上次文件大小
        
        if self.log_paths:
            logger.info(f"日志监听器初始化，监听路径: {self.log_paths}")
        else:
            logger.info("日志监听器初始化，未配置日志路径")
    
    def get_log_files(self) -> List[str]:
        """
        获取所有需要监听的日志文件列表
        
        Returns:
            List[str]: 日志文件路径列表
        """
        files = []
        if not self.log_paths:
            return files
        
        # 分割多个路径
        paths = [p.strip() for p in self.log_paths.split(',')]
        
        for path in paths:
            # 支持通配符
            if '*' in path or '?' in path:
                matched = glob.glob(path, recursive=True)
                files.extend(matched)
            elif os.path.isfile(path):
                files.append(path)
        
        return list(set(files))  # 去重
    
    def collect(self, max_lines: int = 1000) -> Tuple[List[LogEntry], Dict[str, int]]:
        """
        采集所有监听文件的新增日志
        
        Args:
            max_lines: 单次采集最大行数限制，防止内存溢出
        
        Returns:
            Tuple[List[LogEntry], Dict[str, int]]: (日志条目列表, 统计信息)
            统计信息包含: {'total': 总行数, 'error': 错误行数, 'files': 文件数}
        """
        entries = []
        stats = {'total': 0, 'error': 0, 'warn': 0, 'info': 0, 'debug': 0, 'files': 0}
        
        log_files = self.get_log_files()
        
        for file_path in log_files:
            try:
                file_entries, file_stats = self._collect_file(file_path, max_lines - len(entries))
                entries.extend(file_entries)
                for key in stats:
                    if key != 'files':
                        stats[key] += file_stats.get(key, 0)
                stats['files'] += 1
                
                if len(entries) >= max_lines:
                    break
                    
            except Exception as e:
                logger.warning(f"采集文件 {file_path} 失败: {e}")
        
        return entries, stats
    
    def _collect_file(self, file_path: str, max_lines: int) -> Tuple[List[LogEntry], Dict[str, int]]:
        """
        采集单个文件的新增日志
        
        Args:
            file_path: 文件路径
            max_lines: 最大行数限制
        
        Returns:
            Tuple[List[LogEntry], Dict[str, int]]: (日志条目, 统计信息)
        """
        entries = []
        stats = {'total': 0, 'error': 0, 'warn': 0, 'info': 0, 'debug': 0}
        
        # 获取文件信息
        try:
            stat = os.stat(file_path)
            current_size = stat.st_size
            current_inode = stat.st_ino
        except FileNotFoundError:
            logger.debug(f"文件不存在: {file_path}")
            return entries, stats
        
        # 检测文件轮转
        previous_inode = self.file_inodes.get(file_path)
        if previous_inode is not None and previous_inode != current_inode:
            # 文件被轮转，重置读取位置
            logger.info(f"检测到文件轮转: {file_path}")
            self.file_positions[file_path] = 0
        
        # 检测文件截断（大小变小）
        previous_size = self.file_sizes.get(file_path, 0)
        if current_size < previous_size:
            logger.info(f"检测到文件截断: {file_path}")
            self.file_positions[file_path] = 0
        
        # 获取上次读取位置
        position = self.file_positions.get(file_path, 0)
        
        # 如果位置超过当前大小，说明文件被截断或重建
        if position > current_size:
            position = 0
        
        # 读取新增内容
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(position)
                lines_read = 0
                
                for line in f:
                    if lines_read >= max_lines:
                        break
                    
                    line = line.rstrip('\n\r')
                    if not line:
                        continue
                    
                    entry = self._parse_line(line, os.path.basename(file_path))
                    entries.append(entry)
                    
                    # 统计级别
                    stats['total'] += 1
                    stats[entry.level.lower()] = stats.get(entry.level.lower(), 0) + 1
                    
                    lines_read += 1
                
                # 更新读取位置
                self.file_positions[file_path] = f.tell()
                
        except PermissionError:
            logger.warning(f"无权限读取文件: {file_path}")
        except Exception as e:
            logger.error(f"读取文件 {file_path} 异常: {e}")
        
        # 更新文件状态
        self.file_inodes[file_path] = current_inode
        self.file_sizes[file_path] = current_size
        
        return entries, stats
    
    def _parse_line(self, line: str, file_name: str) -> LogEntry:
        """
        解析单行日志
        
        Args:
            line: 日志行内容
            file_name: 来源文件名
        
        Returns:
            LogEntry: 解析后的日志条目
        """
        # 尝试解析日志级别
        level = 'INFO'  # 默认级别
        
        for pattern, level_value in self.LEVEL_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                if level_value:
                    level = level_value
                else:
                    # 从匹配组中提取级别
                    level = match.group(1).upper()
                    # 标准化级别名称
                    level_map = {
                        'CRITICAL': 'ERROR',
                        'FATAL': 'ERROR',
                        'WARNING': 'WARN',
                        'NOTICE': 'INFO',
                        'TRACE': 'DEBUG',
                        'FINE': 'DEBUG',
                    }
                    level = level_map.get(level, level)
                break
        
        # 尝试解析时间戳（常见格式）
        timestamp = ''
        
        # 格式1: 2024-01-15 10:30:45
        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if ts_match:
            timestamp = ts_match.group(1)
        else:
            # 格式2: [15/Jan/2024:10:30:45 +0800]
            ts_match = re.search(r'\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})', line)
            if ts_match:
                timestamp = ts_match.group(1)
        
        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=line,
            raw=line,
            file_name=file_name
        )
    
    def reset(self):
        """重置所有文件的读取位置"""
        self.file_positions.clear()
        self.file_inodes.clear()
        self.file_sizes.clear()
        logger.info("日志监听器已重置")


class LogAggregator:
    """
    日志聚合器
    
    功能：
    - 聚合多条日志
    - 生成摘要统计
    - 支持批量上报
    """
    
    def __init__(self, max_batch_size: int = 100):
        """
        初始化聚合器
        
        Args:
            max_batch_size: 批量上报的最大条目数
        """
        self.max_batch_size = max_batch_size
        self.pending_entries: List[LogEntry] = []
    
    def add(self, entries: List[LogEntry]):
        """
        添加日志条目到待上报队列
        
        Args:
            entries: 日志条目列表
        """
        self.pending_entries.extend(entries)
    
    def get_batch(self) -> List[LogEntry]:
        """
        获取一批待上报的日志
        
        Returns:
            List[LogEntry]: 待上报的日志条目（最多 max_batch_size 条）
        """
        batch = self.pending_entries[:self.max_batch_size]
        return batch
    
    def ack(self, count: int):
        """
        确认已上报的日志数量，从队列中移除
        
        Args:
            count: 已成功上报的日志数量
        """
        self.pending_entries = self.pending_entries[count:]
    
    def get_pending_count(self) -> int:
        """
        获取待上报日志数量
        
        Returns:
            int: 待上报日志数量
        """
        return len(self.pending_entries)
    
    def get_summary(self, entries: List[LogEntry]) -> Dict:
        """
        生成日志摘要统计
        
        Args:
            entries: 日志条目列表
        
        Returns:
            Dict: 摘要统计信息
        """
        if not entries:
            return {
                'total': 0,
                'by_level': {},
                'by_file': {},
                'sample_errors': []
            }
        
        by_level = {}
        by_file = {}
        error_samples = []
        
        for entry in entries:
            # 按级别统计
            by_level[entry.level] = by_level.get(entry.level, 0) + 1
            
            # 按文件统计
            by_file[entry.file_name] = by_file.get(entry.file_name, 0) + 1
            
            # 收集错误样本（最多 5 条）
            if entry.level == 'ERROR' and len(error_samples) < 5:
                error_samples.append(entry.message[:200])  # 截断过长的错误信息
        
        return {
            'total': len(entries),
            'by_level': by_level,
            'by_file': by_file,
            'sample_errors': error_samples
        }


# 测试入口
if __name__ == '__main__':
    import sys
    
    # 从命令行或环境变量获取日志路径
    log_path = sys.argv[1] if len(sys.argv) > 1 else os.getenv('PUSHMON_LOG_PATHS', '/var/log/*.log')
    
    watcher = LogWatcher(log_path)
    
    print(f"测试日志监听（路径: {log_path}）")
    print("按 Ctrl+C 退出...\n")
    
    try:
        while True:
            entries, stats = watcher.collect()
            if entries:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 采集到 {stats['total']} 条日志")
                print(f"  级别分布: ERROR={stats['error']}, WARN={stats['warn']}, INFO={stats['info']}, DEBUG={stats['debug']}")
                if entries:
                    print(f"  最新: {entries[0].message[:80]}...")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 无新增日志")
            
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n测试结束")