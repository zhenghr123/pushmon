package com.pushmon.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * HTTP 发送器
 * 负责将指标和日志推送到 PushMon Server
 */
public class HttpSender {
    private static final Logger logger = LoggerFactory.getLogger(HttpSender.class);
    private static final int TIMEOUT_SECONDS = 5;
    private static final int MAX_RETRIES = 3;
    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");
    
    private final String serverUrl;
    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;
    
    // 统计信息
    private int metricsSent = 0;
    private int metricsFailed = 0;
    private int logsSent = 0;
    private int logsFailed = 0;
    
    public HttpSender(String serverUrl) {
        this.serverUrl = serverUrl.replaceAll("/$", ""); // 移除末尾斜杠
        this.httpClient = new OkHttpClient.Builder()
            .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .build();
        this.objectMapper = new ObjectMapper();
        logger.info("HttpSender 初始化：server={}", this.serverUrl);
    }
    
    /**
     * 发送指标
     */
    public void sendMetrics(Map<String, Object> metrics) {
        String url = serverUrl + "/api/metrics";
        
        for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
            try {
                String json = objectMapper.writeValueAsString(metrics);
                RequestBody body = RequestBody.create(json, JSON);
                Request request = new Request.Builder()
                    .url(url)
                    .post(body)
                    .addHeader("User-Agent", "PushMon-Agent-Java/1.0")
                    .build();
                
                try (Response response = httpClient.newCall(request).execute()) {
                    if (response.isSuccessful()) {
                        metricsSent++;
                        logger.debug("指标上报成功：{}% CPU", 
                                   metrics.getOrDefault("cpu_usage", "N/A"));
                        return;
                    } else {
                        logger.warn("指标上报失败：HTTP {}", response.code());
                    }
                }
            } catch (IOException e) {
                logger.warn("指标上报网络错误 (尝试 {}/{})", attempt, MAX_RETRIES, e);
            }
            
            // 重试前等待
            if (attempt < MAX_RETRIES) {
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
        
        metricsFailed++;
        logger.error("指标上报失败，已放弃重试");
    }
    
    /**
     * 发送日志
     */
    public void sendLogs(List<Map<String, Object>> logs) {
        if (logs.isEmpty()) {
            return;
        }
        
        String url = serverUrl + "/api/logs";
        
        Map<String, Object> logData = new java.util.HashMap<>();
        logData.put("container_name", logs.get(0).getOrDefault("container_name", "unknown"));
        logData.put("timestamp", System.currentTimeMillis());
        logData.put("count", logs.size());
        logData.put("logs", logs);
        
        for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
            try {
                String json = objectMapper.writeValueAsString(logData);
                RequestBody body = RequestBody.create(json, JSON);
                Request request = new Request.Builder()
                    .url(url)
                    .post(body)
                    .addHeader("User-Agent", "PushMon-Agent-Java/1.0")
                    .build();
                
                try (Response response = httpClient.newCall(request).execute()) {
                    if (response.isSuccessful()) {
                        logsSent += logs.size();
                        logger.debug("日志上报成功：{} 条", logs.size());
                        return;
                    } else {
                        logger.warn("日志上报失败：HTTP {}", response.code());
                    }
                }
            } catch (IOException e) {
                logger.warn("日志上报网络错误 (尝试 {}/{})", attempt, MAX_RETRIES, e);
            }
            
            // 重试前等待
            if (attempt < MAX_RETRIES) {
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
        
        logsFailed += logs.size();
        logger.warn("日志上报失败，丢弃 {} 条日志", logs.size());
    }
    
    /**
     * 获取统计信息
     */
    public Map<String, Integer> getStats() {
        Map<String, Integer> stats = new java.util.HashMap<>();
        stats.put("metrics_sent", metricsSent);
        stats.put("metrics_failed", metricsFailed);
        stats.put("logs_sent", logsSent);
        stats.put("logs_failed", logsFailed);
        return stats;
    }
}
