package com.pushmon.agent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.lang.management.ManagementFactory;
import java.lang.management.OperatingSystemMXBean;
import java.util.HashMap;
import java.util.Map;

/**
 * 系统指标采集器
 * 采集 CPU、内存等基础指标
 */
public class MetricsCollector {
    private static final Logger logger = LoggerFactory.getLogger(MetricsCollector.class);
    private static final long KB = 1024L;
    private static final long MB = 1024L * 1024L;
    
    private final String containerName;
    private final OperatingSystemMXBean osBean;
    
    public MetricsCollector(String containerName) {
        this.containerName = containerName;
        this.osBean = ManagementFactory.getOperatingSystemMXBean();
    }
    
    /**
     * 采集系统指标
     * @return 指标数据 Map
     */
    public Map<String, Object> collect() {
        Map<String, Object> metrics = new HashMap<>();
        metrics.put("container_name", containerName);
        metrics.put("timestamp", System.currentTimeMillis());
        
        // CPU 使用率
        try {
            double cpuUsage = getCpuUsage();
            metrics.put("cpu_usage", cpuUsage);
        } catch (Exception e) {
            logger.debug("CPU 指标采集失败", e);
            metrics.put("cpu_usage", -1);
        }
        
        // 内存使用
        try {
            Map<String, Long> memInfo = getMemoryInfo();
            metrics.put("memory_total_mb", memInfo.get("total") / MB);
            metrics.put("memory_used_mb", memInfo.get("used") / MB);
            metrics.put("memory_free_mb", memInfo.get("free") / MB);
            metrics.put("memory_usage_percent", 
                       (memInfo.get("total") > 0) ? 
                       (memInfo.get("used") * 100.0 / memInfo.get("total")) : -1);
        } catch (Exception e) {
            logger.debug("内存指标采集失败", e);
        }
        
        // 系统负载
        try {
            double loadAverage = osBean.getSystemLoadAverage();
            metrics.put("system_load", loadAverage);
        } catch (Exception e) {
            logger.debug("系统负载采集失败", e);
        }
        
        // JVM 内存
        try {
            var runtime = Runtime.getRuntime();
            metrics.put("jvm_heap_max_mb", runtime.maxMemory() / MB);
            metrics.put("jvm_heap_used_mb", (runtime.maxMemory() - runtime.freeMemory()) / MB);
        } catch (Exception e) {
            logger.debug("JVM 内存采集失败", e);
        }
        
        return metrics;
    }
    
    /**
     * 获取 CPU 使用率（从 /proc/stat）
     */
    private double getCpuUsage() throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader("/proc/stat"));
        String line = reader.readLine();
        reader.close();
        
        if (line != null && line.startsWith("cpu ")) {
            String[] parts = line.split("\\s+");
            long user = Long.parseLong(parts[1]);
            long nice = Long.parseLong(parts[2]);
            long system = Long.parseLong(parts[3]);
            long idle = Long.parseLong(parts[4]);
            
            long total = user + nice + system + idle;
            long used = user + nice + system;
            
            // 简单计算：当前使用率 = used / total
            return (total > 0) ? (used * 100.0 / total) : 0;
        }
        
        return 0;
    }
    
    /**
     * 获取内存信息（从 /proc/meminfo）
     */
    private Map<String, Long> getMemoryInfo() throws IOException {
        Map<String, Long> memInfo = new HashMap<>();
        long total = 0, free = 0, buffers = 0, cached = 0;
        
        BufferedReader reader = new BufferedReader(new FileReader("/proc/meminfo"));
        String line;
        while ((line = reader.readLine()) != null) {
            String[] parts = line.split("\\s+");
            if (parts.length >= 2) {
                long value = Long.parseLong(parts[1]) * KB;
                switch (parts[0]) {
                    case "MemTotal:":
                        total = value;
                        break;
                    case "MemFree:":
                        free = value;
                        break;
                    case "Buffers:":
                        buffers = value;
                        break;
                    case "Cached:":
                        cached = value;
                        break;
                }
            }
        }
        reader.close();
        
        long used = total - free - buffers - cached;
        memInfo.put("total", total);
        memInfo.put("used", used);
        memInfo.put("free", free);
        
        return memInfo;
    }
}
