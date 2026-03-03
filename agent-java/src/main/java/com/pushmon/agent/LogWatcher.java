package com.pushmon.agent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 日志文件监听器
 * 支持通配符匹配多个日志文件
 */
public class LogWatcher {
    private static final Logger logger = LoggerFactory.getLogger(LogWatcher.class);
    private static final int MAX_LOG_LENGTH = 1000;
    
    private List<Path> logPaths;  // 不能用 final，因为后续要动态添加新发现的文件
    private final Map<Path, Long> filePositions;
    private final Map<Path, Long> fileInodes;
    
    // 日志级别匹配
    private static final Pattern LOG_LEVEL_PATTERN = Pattern.compile(
        "(?i)\\b(DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\\b");
    
    public LogWatcher(String logPathPattern) {
        this.filePositions = new ConcurrentHashMap<>();
        this.fileInodes = new ConcurrentHashMap<>();
        
        // 首次尝试展开路径
        this.logPaths = expandPathPattern(logPathPattern);
        
        if (logPaths.isEmpty()) {
            logger.warn("LogWatcher 初始化：未找到匹配的日志文件（可能是业务尚未启动），将在后续采集中重试");
        } else {
            logger.info("LogWatcher 初始化：监控 {} 个日志文件", logPaths.size());
        }
    }
    
    /**
     * 展开路径通配符
     */
    private List<Path> expandPathPattern(String pattern) {
        List<Path> paths = new ArrayList<>();
        String[] patterns = pattern.split(",");
        
        for (String p : patterns) {
            p = p.trim();
            if (p.isEmpty()) continue;
            
            try {
                // 检查是否包含通配符
                if (p.contains("*") || p.contains("?")) {
                    Path parent = Paths.get(p).getParent();
                    String glob = "glob:" + Paths.get(p).getFileName().toString();
                    if (parent == null) parent = Paths.get(".");
                    
                    try (DirectoryStream<Path> stream = Files.newDirectoryStream(parent, glob)) {
                        for (Path entry : stream) {
                            if (Files.isRegularFile(entry)) {
                                paths.add(entry);
                            }
                        }
                    }
                } else {
                    Path path = Paths.get(p);
                    if (Files.isRegularFile(path)) {
                        paths.add(path);
                    }
                }
            } catch (IOException e) {
                logger.warn("路径展开失败：{}", p, e);
            }
        }
        
        return paths;
    }
    
    /**
     * 采集新增日志
     */
    public List<Map<String, Object>> collect() {
        List<Map<String, Object>> entries = new ArrayList<>();
        
        // 定期刷新文件列表（可能有新文件或新目录）
        List<Path> currentPaths = new ArrayList<>();
        for (Path path : logPaths) {
            if (Files.isRegularFile(path)) {
                currentPaths.add(path);
            }
        }
        
        // 如果当前没有文件，尝试重新展开路径（可能是业务刚启动）
        if (currentPaths.isEmpty()) {
            List<Path> refreshedPaths = new ArrayList<>();
            for (Path path : logPaths) {
                // 检查父目录是否存在
                Path parent = path.getParent();
                if (parent != null && Files.isDirectory(parent)) {
                    // 父目录存在，尝试重新展开
                    refreshedPaths.addAll(expandPathPattern(path.toString()));
                }
            }
            if (!refreshedPaths.isEmpty()) {
                logPaths = refreshedPaths;
                logger.info("LogWatcher 发现新的日志文件：{} 个", refreshedPaths.size());
                return collect(); // 递归调用采集
            }
        }
        
        for (Path path : currentPaths) {
            try {
                List<Map<String, Object>> fileEntries = readFile(path);
                entries.addAll(fileEntries);
            } catch (IOException e) {
                logger.debug("读取日志文件失败：{}", path, e);
            }
        }
        
        return entries;
    }
    
    /**
     * 读取文件新增内容
     */
    private List<Map<String, Object>> readFile(Path path) throws IOException {
        List<Map<String, Object>> entries = new ArrayList<>();
        
        long currentPosition = filePositions.getOrDefault(path, 0L);
        long currentInode = getFileInode(path);
        Long storedInode = fileInodes.get(path);
        
        // 检查文件是否被轮转（inode 变化）
        if (storedInode != null && !storedInode.equals(currentInode)) {
            logger.info("检测到日志轮转：{}", path);
            currentPosition = 0;
        }
        
        fileInodes.put(path, currentInode);
        
        long fileSize = Files.size(path);
        if (fileSize <= currentPosition) {
            // 文件被截断或轮转
            if (fileSize < currentPosition) {
                logger.debug("文件被截断，从头开始读取：{}", path);
            }
            currentPosition = 0;
        }
        
        if (currentPosition >= fileSize) {
            return entries; // 没有新内容
        }
        
        try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            // 跳过已读内容
            long skipped = reader.skip(currentPosition);
            if (skipped < currentPosition) {
                logger.warn("跳过字节数不足：期望{}, 实际{}", currentPosition, skipped);
            }
            
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.trim().isEmpty()) {
                    Map<String, Object> entry = new HashMap<>();
                    entry.put("timestamp", System.currentTimeMillis());
                    entry.put("file", path.toString());
                    entry.put("message", truncate(line, MAX_LOG_LENGTH));
                    entry.put("level", extractLogLevel(line));
                    entries.add(entry);
                }
            }
            
            // 更新位置
            filePositions.put(path, Files.size(path));
        }
        
        return entries;
    }
    
    /**
     * 获取文件 inode（用于检测日志轮转）
     */
    private long getFileInode(Path path) throws IOException {
        Object attr = Files.getAttribute(path, "unix:ino");
        if (attr instanceof Long) {
            return (Long) attr;
        }
        // 非 Unix 系统，返回文件大小作为替代
        return Files.size(path);
    }
    
    /**
     * 提取日志级别
     */
    private String extractLogLevel(String message) {
        Matcher matcher = LOG_LEVEL_PATTERN.matcher(message);
        if (matcher.find()) {
            String level = matcher.group(1).toUpperCase();
            if ("WARNING".equals(level)) return "WARN";
            return level;
        }
        return "INFO"; // 默认级别
    }
    
    /**
     * 截断字符串
     */
    private String truncate(String str, int maxLen) {
        if (str.length() <= maxLen) {
            return str;
        }
        return str.substring(0, maxLen) + "...";
    }
}
