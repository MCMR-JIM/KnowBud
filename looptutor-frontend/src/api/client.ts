import axios from 'axios';
import { API_BASE } from './config';

// 统一指向后端的 FastAPI 接口地址
const API_BASE_URL = API_BASE;

// 创建一个 Axios 实例
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // 语音处理可能较慢，超时时间设为 30 秒
});

// 封装会话相关的核心接口 (对接后端 v1.3 文档)
export const SessionAPI = {
  // ================= 1. 全局状态与记忆 =================
  getState: () => apiClient.get('/session/state'),
  getEvents: (after: number = 0, limit: number = 50) => 
    apiClient.get(`/session/events?after=${after}&limit=${limit}`),

  // ================= 2. 魔法舱互动 (文字 & 语音) =================
  sendText: (text: string) => apiClient.post('/session/input/text', { text }),
  
  // 语音上传：需要包装成 FormData
  sendAudio: (audioBlob: Blob) => {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice_record.wav');
    return apiClient.post('/session/input/audio/sentence', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },

  // ================= 3. 魔法舱互动 (流式极速响应) =================
  // 获取流式播报的 stream_id
  sendTextRealtime: (text: string) => apiClient.post('/session/input/text/realtime', { text }),
  // 打断后端施法（停止播报）
  interruptStream: (streamId: string) => apiClient.post(`/session/output/audio/interrupt/${streamId}`),
  // (注：流式音频播放不需要 Axios，直接在 audio 标签的 src 里填入拼接好的 URL 即可)

  // ================= 4. 家长端控制台 =================
  // 推送复习任务
  pushReviewTopic: (topicId: string) => apiClient.post('/session/review/push', { topic_id: topicId }),
  // 开启/关闭自由探索奖励时间窗
  openExploreWindow: (minutes: number = 5) => apiClient.post('/session/explore-window/open', { minutes }),
  closeExploreWindow: () => apiClient.post('/session/explore-window/close'),

  // ================= 5. 知识图谱 (新增) =================
  getKnowledgeGraph: () => apiClient.get('/knowledge/graph'),
};

export const ResourceAPI = {
  uploadResource: (payload: {
    file: File | Blob;
    topicId: string;
    resourceName: string;
    category?: 'learn' | 'review';
  }) => {
    const formData = new FormData();
    formData.append('file', payload.file);
    formData.append('topic_id', payload.topicId);
    formData.append('resource_name', payload.resourceName);
    formData.append('category', payload.category || 'learn');
    return apiClient.post('/resource/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },
  getTopicResources: (topicId: string) => apiClient.get(`/resource/topics/${topicId}`),
  getTopicTeachingCues: (topicId: string) => apiClient.get(`/resource/topics/${topicId}/teaching-cues`),
  getResourceSegments: (resourceId: string) => apiClient.get(`/resource/${resourceId}/segments`),
};

export const KnowledgeAPI = {
  getProposals: (params?: { status?: string; trigger?: string }) => apiClient.get('/knowledge/proposals', { params }),
  approveProposal: (proposalId: string, payload: Record<string, unknown> = {}) =>
    apiClient.post(`/knowledge/proposals/${proposalId}/approve`, payload),
  rejectProposal: (proposalId: string, reason?: string) =>
    apiClient.post(`/knowledge/proposals/${proposalId}/reject`, { reason }),
};
