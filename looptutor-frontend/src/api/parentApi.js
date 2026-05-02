// src/api/parentApi.js
import axios from 'axios';

// 创建一个 Axios 实例，集中管理基础配置
const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8090', // 后端服务地址
  headers: {
    'Content-Type': 'application/json',
  },
  // 可以根据需要添加 timeout: 5000 等配置
});

/**
 * 1. 家长端任务推送功能 (Review Push)
 * API: POST /v1/session/review/push
 */
export const pushTaskToChild = async (topicId) => {
  try {
    // Axios 的 post 方法：第一个参数是路径，第二个是 body
    const response = await apiClient.post('/v1/session/review/push', { 
      topic_id: topicId 
    });
    // Axios 会自动将响应体放在 response.data 中
    return response.data; 
  } catch (error) {
    console.error("推送任务失败:", error);
    throw error;
  }
};

/**
 * 2. 家长端资源调用结果 (获取复习队列)
 * API: GET /v1/session/review-queue
 */
export const fetchReviewQueue = async () => {
  try {
    const response = await apiClient.get('/v1/session/review-queue');
    return response.data; 
  } catch (error) {
    console.error("获取复习队列失败:", error);
    throw error;
  }
};

/**
 * 3. 图表数据接口对接 (知识图谱与掌握度)
 * API: GET /v1/knowledge/graph 和 GET /v1/session/mastery
 */
export const fetchChartData = async () => {
  try {
    // 使用 Promise.all 并发请求掌握度和知识图谱数据，提升加载速度
    const [masteryRes, graphRes] = await Promise.all([
      apiClient.get('/v1/session/mastery'),
      apiClient.get('/v1/knowledge/graph')
    ]);

    return {
      mastery: masteryRes.data,
      graph: graphRes.data
    };
  } catch (error) {
    console.error("获取图表数据失败:", error);
    throw error;
  }
};