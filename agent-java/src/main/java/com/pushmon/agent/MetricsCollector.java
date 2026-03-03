package com.pushmon.agent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.lang.management.ManagementFactory;
import java.lang.management.OperatingSystemMXBean;
import java.util.HashMap;
import java.util.Map;

/**
 * 系统指标采集器
 * 基于 Cgroup 采集容器的 CPU、内存等指标（K8s 环境准确监控）
 */
public class MetricsCollector {
    private static final Logger logger = LoggerFactory.getLogger(MetricsCollector.class);
    private static final long KB = 1024L;
    private static final long MB = 1024L * 1024L;
    private static final long NS_PER_SECOND = 1000000000L;
    
    // Cgroup v1 路径
    private static final String CGROUP_MEMORY_USAGE = "/sys/fs/cgroup/memory/memory.usage_in_bytes";
    private static final String CGROUP_MEMORY_LIMIT = "/sys/fs/cgroup/memory/memory.limit_in_bytes";
    private static final String CGROUP_CPU_USAGE = "/sys/fs/cgroup/cpuacct/cpuacct.usage";
    private static final String CGROUP_CPU_QUOTA = "/sys/fs/cgroup/cpu/cpu.cfs_quota_us";
    private static final String CGROUP_CPU_PERIOD = "/sys/fs/cgroup/cpu/cpu.cfs_period_us";
    
    // Cgroup v2 路径（备选）
    private static final String CGROUP2_MEMORY_CURRENT = "/sys/fs/cgroup/memory.current";
    private static final String CGROUP2_MEMORY_MAX = "/sys/fs/cgroup/memory.max";
    private static final String CGROUP2_CPU_STAT = "/sys/fs/cgroup/cpu.stat";
    
    private final String containerName;
    private final OperatingSystemMXBean osBean;
    
    // CPU 计算所需的状态
    private long lastCpuUsage = 0;
    private long lastTime = 0;
    
    public MetricsCollector(String containerName) {
        this.containerName = containerName;
        this.osBean = ManagementFactory.getOperatingSystemMXBean();
        // 初始化 CPU 基准值
        initCpuBaseline();
    }
    
    /**
     * 初始化 CPU 基准值（首次启动时调用）
     */
    private void initCpuBaseline() {
        try {
            lastCpuUsage = readCgroupCpuUsage();
            lastTime = System.nanoTime();
        } catch (Exception e) {
            logger.debug("初始化 CPU 基准值失败", e);
        }
    }
    
    /**
     * 采集系统指标
     * @return 指标数据 Map
     */
    public Map<String, Object> collect() {
        Map<String, Object> metrics = new HashMap<>();
        metrics.put("container_name", containerName);
        metrics.put("timestamp", System.currentTimeMillis());
        
        // CPU 使用率（基于 cgroup）
        try {
            double cpuUsage = getCpuUsagePercent();
            metrics.put("cpu_usage", cpuUsage);
        } catch (Exception e) {
            logger.debug("CPU 指标采集失败", e);
            metrics.put("cpu_usage", -1);
        }
        
        // 内存使用（基于 cgroup）
        try {
            Map<String, Long> memInfo = getCgroupMemoryInfo();
            metrics.put("memory_used_mb", memInfo.get("used") / MB);
            metrics.put("memory_limit_mb", memInfo.get("limit") / MB);
            metrics.put("memory_usage_percent", 
                       (memInfo.get("limit") > 0 && memInfo.get("limit") < 9223372036854771712L) ? 
                       (memInfo.get("used") * 100.0 / memInfo.get("limit")) : -1);
        } catch (Exception e) {
            logger.debug("内存指标采集失败", e);
        }
        
        // CPU 配额（核数）
        try {
            double cpuQuota = getCpuQuota();
            metrics.put("cpu_quota", cpuQuota);
        } catch (Exception e) {
            logger.debug("CPU 配额采集失败", e);
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
            Runtime runtime = Runtime.getRuntime();
            metrics.put("jvm_heap_max_mb", runtime.maxMemory() / MB);
            metrics.put("jvm_heap_used_mb", (runtime.maxMemory() - runtime.freeMemory()) / MB);
        } catch (Exception e) {
            logger.debug("JVM 内存采集失败", e);
        }
        
        return metrics;
    }
    
    /**
     * 获取 CPU 使用率百分比（基于 cgroup cpuacct）
     * 计算方法：(Δcpuacct.usage / Δtime) * 100 / cpu_quota
     */
    private double getCpuUsagePercent() throws IOException {
        long currentCpuUsage = readCgroupCpuUsage();
        long currentTime = System.nanoTime();
        
        // 计算差值
        long deltaCpu = currentCpuUsage - lastCpuUsage;
        long deltaTime = currentTime - lastTime;
        
        // 更新基准值
        lastCpuUsage = currentCpuUsage;
        lastTime = currentTime;
        
        // 获取 CPU 配额（核数）
        double cpuQuota = getCpuQuota();
        if (cpuQuota <= 0) {
            cpuQuota = 1.0; // 无限制时按 1 核计算
        }
        
        // 计算使用率百分比
        // cpuacct.usage 单位是纳秒，deltaTime 也是纳秒
        // cpuUsage = (deltaCpu / deltaTime) * 100 / cpuQuota
        if (deltaTime > 0) {
            double cpuPercent = (deltaCpu * 100.0) / (deltaTime * cpuQuota);
            return Math.min(cpuPercent, 100.0 * cpuQuota); // 不超过配额上限
        }
        
        return 0;
    }
    
    /**
     * 读取 cgroup CPU 使用时间（纳秒）
     * 支持 cgroup v1 和 v2
     */
    private long readCgroupCpuUsage() throws IOException {
        // 尝试 cgroup v1
        File v1File = new File(CGROUP_CPU_USAGE);
        if (v1File.exists()) {
            BufferedReader reader = new BufferedReader(new FileReader(v1File));
            String line = reader.readLine();
            reader.close();
            if (line != null) {
                return Long.parseLong(line.trim());
            }
        }
        
        // 尝试 cgroup v2
        File v2File = new File(CGROUP2_CPU_STAT);
        if (v2File.exists()) {
            BufferedReader reader = new BufferedReader(new FileReader(v2File));
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("usage_usec")) {
                    String[] parts = line.split("\\s+");
                    if (parts.length >= 2) {
                        reader.close();
                        // 微秒转纳秒
                        return Long.parseLong(parts[1]) * 1000L;
                    }
                }
            }
            reader.close();
        }
        
        // 降级方案：从 /proc/stat 读取
        return readProcStatCpu();
    }
    
    /**
     * 从 /proc/stat 读取 CPU 时间（降级方案）
     */
    private long readProcStatCpu() throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader("/proc/stat"));
        String line = reader.readLine();
        reader.close();
        
        if (line != null && line.startsWith("cpu ")) {
            String[] parts = line.split("\\s+");
            long user = Long.parseLong(parts[1]);
            long nice = Long.parseLong(parts[2]);
            long system = Long.parseLong(parts[3]);
            // 单位是毫秒，转纳秒
            return (user + nice + system) * 1000000L;
        }
        
        return 0;
    }
    
    /**
     * 获取 CPU 配额（核数）
     * @return CPU 核数，无限制时返回 -1
     */
    private double getCpuQuota() throws IOException {
        // 尝试 cgroup v1
        File quotaFile = new File(CGROUP_CPU_QUOTA);
        File periodFile = new File(CGROUP_CPU_PERIOD);
        
        if (quotaFile.exists() && periodFile.exists()) {
            BufferedReader quotaReader = new BufferedReader(new FileReader(quotaFile));
            BufferedReader periodReader = new BufferedReader(new FileReader(periodFile));
            
            String quotaStr = quotaReader.readLine();
            String periodStr = periodReader.readLine();
            
            quotaReader.close();
            periodReader.close();
            
            if (quotaStr != null && periodStr != null) {
                long quota = Long.parseLong(quotaStr.trim());
                long period = Long.parseLong(periodStr.trim());
                
                // quota = -1 表示无限制
                if (quota < 0) {
                    return -1;
                }
                
                return (double) quota / period;
            }
        }
        
        return 1.0; // 默认 1 核
    }
    
    /**
     * 获取 cgroup 内存信息
     * @return Map<used, limit> 单位：字节
     */
    private Map<String, Long> getCgroupMemoryInfo() throws IOException {
        Map<String, Long> memInfo = new HashMap<>();
        
        // 尝试 cgroup v1
        File usageFileV1 = new File(CGROUP_MEMORY_USAGE);
        File limitFileV1 = new File(CGROUP_MEMORY_LIMIT);
        
        if (usageFileV1.exists() && limitFileV1.exists()) {
            BufferedReader usageReader = new BufferedReader(new FileReader(usageFileV1));
            BufferedReader limitReader = new BufferedReader(new FileReader(limitFileV1));
            
            String usageStr = usageReader.readLine();
            String limitStr = limitReader.readLine();
            
            usageReader.close();
            limitReader.close();
            
            if (usageStr != null && limitStr != null) {
                memInfo.put("used", Long.parseLong(usageStr.trim()));
                memInfo.put("limit", Long.parseLong(limitStr.trim()));
                return memInfo;
            }
        }
        
        // 尝试 cgroup v2
        File usageFileV2 = new File(CGROUP2_MEMORY_CURRENT);
        File limitFileV2 = new File(CGROUP2_MEMORY_MAX);
        
        if (usageFileV2.exists()) {
            BufferedReader usageReader = new BufferedReader(new FileReader(usageFileV2));
            String usageStr = usageReader.readLine();
            usageReader.close();
            
            if (usageStr != null) {
                memInfo.put("used", Long.parseLong(usageStr.trim()));
            }
        }
        
        if (limitFileV2.exists()) {
            BufferedReader limitReader = new BufferedReader(new FileReader(limitFileV2));
            String limitStr = limitReader.readLine();
            limitReader.close();
            
            if (limitStr != null && !"max".equals(limitStr.trim())) {
                memInfo.put("limit", Long.parseLong(limitStr.trim()));
            } else {
                // 无限制时使用 available
                memInfo.put("limit", 9223372036854771712L);
            }
        }
        
        // 降级方案：从 /proc/meminfo 读取
        if (!memInfo.containsKey("used")) {
            Map<String, Long> procMem = getProcMemInfo();
            memInfo.put("used", procMem.get("used"));
            if (!memInfo.containsKey("limit")) {
                memInfo.put("limit", procMem.get("total"));
            }
        }
        
        return memInfo;
    }
    
    /**
     * 从 /proc/meminfo 读取内存信息（降级方案）
     */
    private Map<String, Long> getProcMemInfo() throws IOException {
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
        
        return memInfo;
    }
}
