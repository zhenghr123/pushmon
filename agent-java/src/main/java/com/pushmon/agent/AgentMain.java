package com.pushmon.agent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * PushMon Agent - Java 版主入口
 * 轻量级容器监控探针，采集系统指标和日志，推送到中央服务端
 * 
 * 环境变量配置：
 * - PUSHMON_SERVER_URL: Server 端地址（必填）
 * - PUSHMON_CONTAINER_NAME: 容器名称标识（默认 hostname）
 * - PUSHMON_LOG_PATHS: 日志路径，逗号分隔，支持通配符
 * - PUSHMON_INTERVAL: 上报间隔（秒），默认 10
 */
public class AgentMain {
    private static final Logger logger = LoggerFactory.getLogger(AgentMain.class);
    
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private final MetricsCollector metricsCollector;
    private final LogWatcher logWatcher;
    private final HttpSender httpSender;
    private final int interval;
    
    public AgentMain() {
        String serverUrl = System.getenv("PUSHMON_SERVER_URL");
        String containerName = System.getenv("PUSHMON_CONTAINER_NAME");
        if (containerName == null || containerName.isEmpty()) {
            containerName = System.getenv("HOSTNAME");
        }
        String logPaths = System.getenv("PUSHMON_LOG_PATHS");
        
        String intervalStr = System.getenv("PUSHMON_INTERVAL");
        this.interval = (intervalStr != null) ? Integer.parseInt(intervalStr) : 10;
        
        if (serverUrl == null || serverUrl.isEmpty()) {
            throw new IllegalArgumentException("PUSHMON_SERVER_URL 环境变量未设置");
        }
        
        this.httpSender = new HttpSender(serverUrl);
        this.metricsCollector = new MetricsCollector(containerName);
        this.logWatcher = (logPaths != null && !logPaths.isEmpty()) ? new LogWatcher(logPaths) : null;
        
        logger.info("PushMon Agent 启动：server={}, container={}, interval={}s", 
                   serverUrl, containerName, interval);
    }
    
    public void start() {
        // 定时采集指标
        scheduler.scheduleAtFixedRate(() -> {
            try {
                var metrics = metricsCollector.collect();
                httpSender.sendMetrics(metrics);
            } catch (Exception e) {
                logger.error("指标采集失败", e);
            }
        }, 0, interval, TimeUnit.SECONDS);
        
        // 定时采集日志
        if (logWatcher != null) {
            scheduler.scheduleAtFixedRate(() -> {
                try {
                    var logs = logWatcher.collect();
                    if (!logs.isEmpty()) {
                        httpSender.sendLogs(logs);
                    }
                } catch (Exception e) {
                    logger.error("日志采集失败", e);
                }
            }, 0, 5, TimeUnit.SECONDS);
        }
        
        // 注册关闭钩子
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            logger.info("Agent 正在关闭...");
            scheduler.shutdown();
            try {
                if (!scheduler.awaitTermination(5, TimeUnit.SECONDS)) {
                    scheduler.shutdownNow();
                }
            } catch (InterruptedException e) {
                scheduler.shutdownNow();
            }
        }));
        
        logger.info("PushMon Agent 运行中...");
    }
    
    public static void main(String[] args) {
        try {
            new AgentMain().start();
            // 保持主线程运行
            Thread.currentThread().join();
        } catch (IllegalArgumentException e) {
            logger.error("配置错误：{}", e.getMessage());
            System.exit(1);
        } catch (Exception e) {
            logger.error("Agent 启动失败", e);
            System.exit(1);
        }
    }
}
