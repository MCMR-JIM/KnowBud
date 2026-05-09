import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, AlertCircle, Clock, Video, Info } from 'lucide-react';
import { API_BASE } from '../api/config';
import { KnowledgeAPI, ResourceAPI } from '../api/client';
import SettingsPanel from '../components/SettingsPanel';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const apiBaseUrl = API_BASE;
  // 核心状态
  const [activeTab, setActiveTab] = useState('task');
  const [resourceName, setResourceName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedUploadTopicId, setSelectedUploadTopicId] = useState('');
  const [selectedPushTopicId, setSelectedPushTopicId] = useState('');
  const [uploadCategory, setUploadCategory] = useState<'learn' | 'review'>('learn');
  const [knowledgeTopics, setKnowledgeTopics] = useState<{ topicId: string; title: string }[]>([]);
  const [lastUploadSummary, setLastUploadSummary] = useState<{
    resourceId: string;
    mediaType: string;
    segmentCount: number;
    classifiedCount: number;
    proposedCount: number;
    unclassifiedCount: number;
    parseFailedCount: number;
    unsupportedCount: number;
  } | null>(null);

  // 后端真实数据
  const [learningData, setLearningData] = useState({
    todayStar: 0,
    todayStarIncrease: 0,
    focusTime: 0,
    questionActiveness: '待获取',
    progressData: [] as { day: string, score: number }[],
    radarData: {
      questionActiveness: 0,
      focus: 0,
      thinking: 0,
      logic: 0,
      knowledge: 0
    }
  });
  const [knowledgePoints, setKnowledgePoints] = useState<{ id: number, topicId: string, name: string, lastReview: string, resourceCount: number }[]>([]);
  const [graphProposals, setGraphProposals] = useState<any[]>([]);
  const [reviewingProposalId, setReviewingProposalId] = useState('');
  const [engineLogs, setEngineLogs] = useState<string[]>([]);
  const [dataLoading, setDataLoading] = useState(false);
  // 知识图谱状态
  const [graphNodes, setGraphNodes] = useState<any[]>([]);
  const [selectedNode, setSelectedNode] = useState<any | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // 页面加载时自动获取后端数据
  useEffect(() => {
    fetchAllData();
  }, [activeTab]);

  // ================= 🌟 最终版：完整显示周一到周日七天，100%真实计算 =================
  const fetchAllData = async () => {
    setDataLoading(true);
    try {
      // 1. 获取当前状态
      const stateRes = await fetch(`${apiBaseUrl}/session/state`);
      let stateData: any = null;
      if (stateRes.ok) {
        stateData = await stateRes.json();
      }

      // 2. 获取所有事件历史，用于计算真实数据
      const eventsRes = await fetch(`${apiBaseUrl}/session/events`);
      let eventsData: any = null;
      if (eventsRes.ok) {
        eventsData = await eventsRes.json();
      }

      const graphRes = await fetch(`${apiBaseUrl}/knowledge/graph`);
      if (graphRes.ok) {
        const graphData = await graphRes.json();
        // 原来的处理逻辑
        const topics = (graphData.topics || []).map((topic: any) => ({
          topicId: topic.topic_id,
          title: topic.title,
        }));
        setKnowledgeTopics(topics);
        setSelectedUploadTopicId((prev) => topics.some((topic: { topicId: string }) => topic.topicId === prev) ? prev : (topics[0]?.topicId || ''));
        setSelectedPushTopicId((prev) => topics.some((topic: { topicId: string }) => topic.topicId === prev) ? prev : (topics[0]?.topicId || ''));
        
        // 【新增】保存完整的知识图谱节点，供右侧渲染使用
        setGraphNodes(graphData.topics || []);
        setGraphProposals((graphData.proposals || []).filter((proposal: any) => proposal.trigger === 'resource_ingest' && proposal.status === 'proposed'));
      }

      // ================= 真实计算开始 =================
      if (stateData && eventsData) {
        const events = eventsData.events || [];
        const today = new Date().toDateString();
        
        // 筛选今日事件
        const todayEvents = events.filter((event: any) => 
          new Date(event.ts).toDateString() === today
        );

        // 计算今日新增星星
        let todayIncrease = 0;
        const scoreEvents = todayEvents.filter((e: any) => e.kind === 'score_change');
        scoreEvents.forEach((e: any) => {
          todayIncrease += e.payload.delta || 0;
        });

        // 计算专注时长（基于今日事件的时间跨度）
        let focusMinutes = 0;
        if (todayEvents.length > 0) {
          const firstEvent = new Date(todayEvents[0].ts);
          const lastEvent = new Date(todayEvents[todayEvents.length - 1].ts);
          focusMinutes = Math.floor((lastEvent.getTime() - firstEvent.getTime()) / 1000 / 60);
          if (focusMinutes < 0) focusMinutes = 0;
          if (focusMinutes === 0 && todayEvents.length > 0) focusMinutes = 5; // 至少5分钟
        }

        // 计算提问积极性（基于今日用户输入次数）
        const userInputCount = todayEvents.filter((e: any) => 
          e.kind === 'user_input' || e.kind === 'user_audio'
        ).length;
        let activenessLabel = '良好';
        if (userInputCount >= 10) activenessLabel = '极佳';
        else if (userInputCount >= 5) activenessLabel = '良好';
        else if (userInputCount >= 1) activenessLabel = '一般';
        else activenessLabel = '待观察';

        // ================= 🌟 最终修复：完整显示周一到周日七天，再也不会少任何一天 =================
        // 固定显示完整一周七天
        const weekDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
        // 初始化所有七天，默认得分0，确保100%显示，不会丢失任何一天
        const dailyScores: Record<string, number> = {
          '周一': 0,
          '周二': 0,
          '周三': 0,
          '周四': 0,
          '周五': 0,
          '周六': 0,
          '周日': 0
        };

        // 🌟 100%正确的周几映射：JS里getDay() 0=周日，1=周一，2=周二，3=周三，4=周四，5=周五，6=周六
        events.forEach((event: any) => {
          if (event.kind === 'score_change') {
            const eventDate = new Date(event.ts);
            const eventDayNum = eventDate.getDay();
            // 把数字精准转成对应的周几名称
            let dayName = '';
            if (eventDayNum === 1) dayName = '周一';
            else if (eventDayNum === 2) dayName = '周二';
            else if (eventDayNum === 3) dayName = '周三';
            else if (eventDayNum === 4) dayName = '周四';
            else if (eventDayNum === 5) dayName = '周五';
            else if (eventDayNum === 6) dayName = '周六';
            else if (eventDayNum === 0) dayName = '周日'; // 周日完整启用

            // 统计所有七天的得分
            if (dayName && dailyScores.hasOwnProperty(dayName)) {
              dailyScores[dayName] += event.payload.delta || 0;
            }
          }
        });

        // 转换为固定顺序的数组，确保周一到周日顺序不变
        const progressData = weekDays.map(day => ({
          day,
          score: Math.max(0, dailyScores[day])
        }));

        // 计算雷达图数据（基于现有数据估算）
        const consecutiveCorrect = stateData.learning?.consecutive_correct || 0;
        const radarData = {
          questionActiveness: Math.min(100, userInputCount * 10),
          focus: Math.min(100, focusMinutes * 2),
          thinking: Math.min(100, (consecutiveCorrect * 20) + 20),
          logic: Math.min(100, (consecutiveCorrect * 15) + 30),
          knowledge: Math.min(100, (stateData.learning?.total_score || 0) / 2)
        };

        // 更新状态
        setLearningData({
          todayStar: stateData.learning?.total_score || 0,
          todayStarIncrease: todayIncrease,
          focusTime: focusMinutes,
          questionActiveness: activenessLabel,
          progressData,
          radarData
        });
      }

      // 3. 获取错题本数据
      const reviewRes = await fetch(`${apiBaseUrl}/session/review-queue`);
      if (reviewRes.ok) {
        const reviewData = await reviewRes.json();
        setKnowledgePoints(
          (reviewData.items || []).map((item: any, idx: number) => ({
            id: idx + 1,
            topicId: item.topic_id,
            name: item.title,
            lastReview: new Date().toLocaleString(),
            resourceCount: item.resource_count || 0,
          })) || []
        );
      }

      // 4. 获取引擎日志
      if (eventsData) {
        setEngineLogs(
          eventsData.events?.slice(-20).map((event: any) => 
            `[${new Date(event.ts).toLocaleTimeString()}] ${event.kind}: ${JSON.stringify(event.payload)}`
          ) || []
        );
      }
    } catch (error) {
      console.error("获取数据失败", error);
    } finally {
      setDataLoading(false);
    }
  };

  // 雷达图渲染（基于真实数据）
  const renderRadarChart = () => {
    const { questionActiveness, focus, thinking, logic, knowledge } = learningData.radarData;
    // 归一化到0-60像素
    const scale = (val: number) => (val / 100) * 60;
    
    const points = [
      [75, 75 - scale(questionActiveness)],
      [75 + scale(focus) * 0.87, 75 + scale(focus) * 0.5],
      [75 + scale(thinking) * 0.5, 75 + scale(thinking) * 0.87],
      [75 - scale(logic) * 0.5, 75 + scale(logic) * 0.87],
      [75 - scale(knowledge) * 0.87, 75 + scale(knowledge) * 0.5],
    ];

    return (
      <svg width="150" height="150" viewBox="0 0 150 150">
        {/* 背景圈 */}
        {[0.2, 0.4, 0.6, 0.8, 1].map((scale, i) => (
          <polygon
            key={i}
            points={[
              [75, 75 - 60 * scale],
              [75 + 52 * scale, 75 + 30 * scale],
              [75 + 30 * scale, 75 + 60 * scale],
              [75 - 30 * scale, 75 + 60 * scale],
              [75 - 52 * scale, 75 + 30 * scale],
            ].map(p => p.join(',')).join(' ')}
            fill="none"
            stroke="#e5e7eb"
            strokeWidth="1"
          />
        ))}
        {/* 轴 */}
        {[0, 72, 144, 216, 288].map((angle, i) => {
          const rad = (angle * Math.PI) / 180;
          return (
            <line
              key={i}
              x1="75"
              y1="75"
              x2={75 + 60 * Math.sin(rad)}
              y2={75 - 60 * Math.cos(rad)}
              stroke="#e5e7eb"
              strokeWidth="1"
            />
          );
        })}
        {/* 真实数据多边形 */}
        <polygon
          points={points.map(p => p.join(',')).join(' ')}
          fill="rgba(236, 72, 153, 0.3)"
          stroke="#ec4899"
          strokeWidth="2"
        />
        {/* 轴标签 */}
        <text x="75" y="10" fontSize="8" textAnchor="middle" fill="#6b7280">提问积极性</text>
        <text x="135" y="78" fontSize="8" textAnchor="middle" fill="#6b7280">专注度</text>
        <text x="100" y="140" fontSize="8" textAnchor="middle" fill="#6b7280">思考响应性</text>
        <text x="15" y="78" fontSize="8" textAnchor="middle" fill="#6b7280">逻辑理解力</text>
        <text x="40" y="45" fontSize="8" textAnchor="middle" fill="#6b7280">知识掌握度</text>
      </svg>
    );
  };

  // 文件校验逻辑
  const validateAndSetFile = (file: File) => {
    // 支持学习场景常用格式
    const allowedTypes = [
      'video/mp4', 'video/mpeg', 'video/avi', 'video/mov', 'video/quicktime',
      'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/mp4', 'audio/aac', 'audio/ogg',
      'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
      'application/pdf', 'text/plain',
      'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ];
    const allowedExtensions = ['.mp4', '.mpeg', '.avi', '.mov', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.doc', '.docx', '.ppt', '.pptx'];
    const lowerName = file.name.toLowerCase();
    const isAllowed = allowedTypes.includes(file.type) || allowedExtensions.some((ext) => lowerName.endsWith(ext));

    if (!isAllowed) {
      alert("仅支持视频、音频、图片、PDF、Word、PPT、TXT等学习常用格式");
      return false;
    }

    if (file.size > 500 * 1024 * 1024) {
      alert("文件大小不能超过 500MB");
      return false;
    }

    setUploadFile(file);
    setResourceName(file.name.split('.')[0]);
    setLastUploadSummary(null);
    return true;
  };

  // 点击选择文件
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    validateAndSetFile(file);
  };

  // 拖拽事件
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    validateAndSetFile(file);
  };

  // 提交文件上传
  const handleUploadSubmit = async () => {
    if (!uploadFile || !resourceName.trim() || !selectedUploadTopicId) {
      alert("请选择知识节点、文件并填写资源名称");
      return;
    }

    setUploading(true);
    try {
      const res = await ResourceAPI.uploadResource({
        file: uploadFile,
        topicId: selectedUploadTopicId,
        resourceName,
        category: uploadCategory,
      });

      const resource = res.data?.resource;
      const resourceId = resource?.resource_id;
      const segmentRes = resourceId ? await ResourceAPI.getResourceSegments(resourceId) : null;
      const segments = segmentRes?.data?.segments || resource?.segments || [];
      setLastUploadSummary({
        resourceId: resourceId || '',
        mediaType: resource?.media_type || '',
        segmentCount: segments.length,
        classifiedCount: segments.filter((segment: any) => segment.status === 'classified').length,
        proposedCount: segments.filter((segment: any) => segment.status === 'proposed').length,
        unclassifiedCount: segments.filter((segment: any) => segment.status === 'unclassified').length,
        parseFailedCount: segments.filter((segment: any) => segment.status === 'parse_failed').length,
        unsupportedCount: segments.filter((segment: any) => segment.status === 'unsupported').length,
      });

      alert("✅ 资源上传成功，已绑定到知识节点");
      setUploadFile(null);
      setResourceName("");
      fetchAllData();
    } catch (error) {
      console.error("上传失败", error);
      alert("❌ 无法连接后端上传服务");
    } finally {
      setUploading(false);
    }
  };

  // 任务推送功能
  const handlePushTask = async () => {
    if (!selectedPushTopicId) {
      alert("请先选择要推送的知识节点！");
      return;
    }
    setIsLoading(true);
    try {
      const res = await fetch(`${apiBaseUrl}/session/review/push`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic_id: selectedPushTopicId })
      });
      if (res.ok) {
        alert("✅ 任务已成功推送至魔法舱！");
        fetchAllData();
      } else {
        alert("❌ 推送失败，请检查后端服务是否启动");
      }
    } catch (error) {
      console.error(error);
      alert("❌ 无法连接后端服务");
    } finally {
      setIsLoading(false);
    }
  };

  const handleApproveProposal = async (proposal: any) => {
    setReviewingProposalId(proposal.proposal_id);
    try {
      await KnowledgeAPI.approveProposal(proposal.proposal_id, {
        title: proposal.title,
        summary: proposal.summary,
        parent_node_ids: proposal.parent_node_ids,
        edge_type: proposal.edge_type,
        tags: ['parent-approved'],
        reason: '家长确认 AI 建议节点',
      });
      alert('✅ 已新增知识节点，并回挂相关资源片段');
      await fetchAllData();
    } catch (error) {
      console.error(error);
      alert('❌ 审核失败，请检查后端服务');
    } finally {
      setReviewingProposalId('');
    }
  };

  const handleRejectProposal = async (proposal: any) => {
    setReviewingProposalId(proposal.proposal_id);
    try {
      await KnowledgeAPI.rejectProposal(proposal.proposal_id, '家长拒绝该新增节点');
      alert('已拒绝该知识节点建议');
      await fetchAllData();
    } catch (error) {
      console.error(error);
      alert('❌ 拒绝失败，请检查后端服务');
    } finally {
      setReviewingProposalId('');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 to-pink-50 p-6">
      {/* 顶部导航 */}
      <div className="max-w-5xl mx-auto mb-6">
        <div className="bg-white/80 backdrop-blur rounded-2xl p-4 shadow-sm flex justify-between items-center">
          <button 
            onClick={() => navigate('/')}
            className="flex items-center gap-2 text-gray-700 hover:text-gray-900 cursor-pointer"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            <span className="text-lg font-medium">返回大厅</span>
          </button>
          <h1 className="text-lg font-semibold">家长控制台</h1>
          <div className="w-8"></div>
        </div>
      </div>

      {/* 标签页导航 */}
      <div className="max-w-5xl mx-auto mb-6 bg-white/80 backdrop-blur rounded-2xl shadow-sm">
        <div className="flex border-b border-gray-100">
          <button
            onClick={() => setActiveTab('task')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'task' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📁 任务配置
          </button>
          <button
            onClick={() => setActiveTab('report')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'report' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📊 AI 学情报告
          </button>
          <button
            onClick={() => setActiveTab('mistake')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'mistake' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📝 错题本与回放
          </button>
          <button
            onClick={() => setActiveTab('debug')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'debug' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            ⚙️ 系统调试
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'settings' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            🔧 设置
          </button>
        </div>
      </div>

      {/* 标签页内容 */}
      <div className="max-w-5xl mx-auto">
        {/* 1. 任务配置 */}
        {activeTab === 'task' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-pink-500 mb-4">上传今日学习资源</h2>
              <p className="text-xs text-gray-400 mb-2">教学媒体文件（支持视频/音频/图片/PDF/Word/PPT/TXT，单文件最大500MB）</p>
              
              <div 
                onClick={() => document.getElementById('file-upload')?.click()}
                onDragEnter={handleDragEnter}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded-lg p-8 mb-4 text-center cursor-pointer transition-all duration-200 ${
                  isDragging 
                    ? 'border-pink-400 bg-pink-50' 
                    : 'border-gray-200 hover:border-pink-300'
                }`}
              >
                <input
                  id="file-upload"
                  type="file"
                  accept="video/*,audio/*,image/*,.pdf,.txt,.doc,.docx,.ppt,.pptx"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                {uploadFile ? (
                  <div>
                    <p className="text-sm font-medium text-pink-600">已选择：{uploadFile.name}</p>
                    <p className="text-xs text-gray-400 mt-1">大小：{(uploadFile.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm text-gray-500">点击选择文件，或拖拽文件到此处</p>
                    {isDragging && <p className="text-sm text-pink-500 mt-2 font-medium">松开鼠标即可上传</p>}
                  </div>
                )}
              </div>

              <div className="mb-4">
                <label className="text-sm text-gray-500 mb-1 block">知识节点</label>
                <select
                  value={selectedUploadTopicId}
                  onChange={(e) => setSelectedUploadTopicId(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-200"
                >
                  <option value="">请选择知识节点</option>
                  {knowledgeTopics.map((topic) => (
                    <option key={topic.topicId} value={topic.topicId}>{topic.title}</option>
                  ))}
                </select>
              </div>
              <div className="mb-4">
                <label className="text-sm text-gray-500 mb-1 block">资源名称</label>
                <input
                  type="text"
                  value={resourceName}
                  onChange={(e) => setResourceName(e.target.value)}
                  placeholder="请输入资源名称"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-200"
                />
              </div>
              <div className="mb-4">
                <label className="text-sm text-gray-500 mb-1 block">资源用途</label>
                <select
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value as 'learn' | 'review')}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-200"
                >
                  <option value="learn">主线学习资源</option>
                  <option value="review">复习资源并加入队列</option>
                </select>
              </div>
              <button
                onClick={handleUploadSubmit}
                disabled={uploading || !uploadFile}
                className="bg-pink-100 text-pink-600 px-4 py-2 rounded-lg text-sm hover:bg-pink-200 transition-colors cursor-pointer disabled:opacity-50"
              >
                {uploading ? "上传中..." : "保存配置并生成题库"}
              </button>
              {lastUploadSummary && (
                <div className="mt-4 rounded-lg border border-pink-100 bg-pink-50 p-3 text-xs text-gray-700 space-y-1">
                  <p className="font-medium text-pink-600">文档处理结果</p>
                  <p>资源 ID：{lastUploadSummary.resourceId}</p>
                  <p>类型：{lastUploadSummary.mediaType || 'unknown'}</p>
                  <p>分段总数：{lastUploadSummary.segmentCount}</p>
                  <p>已归类：{lastUploadSummary.classifiedCount}，候选提案：{lastUploadSummary.proposedCount}</p>
                  <p>未归类：{lastUploadSummary.unclassifiedCount}，解析失败：{lastUploadSummary.parseFailedCount}，暂不支持：{lastUploadSummary.unsupportedCount}</p>
                </div>
              )}
            </div>

            <div>
              <h2 className="text-lg font-semibold text-gray-700 mb-4">派发学习任务</h2>
              <div className="mb-3">
                <label className="text-sm text-gray-500 mb-1 block">知识节点</label>
                <select
                  value={selectedPushTopicId}
                  onChange={(e) => setSelectedPushTopicId(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-200"
                >
                  <option value="">请选择知识节点</option>
                  {knowledgeTopics.map((topic) => (
                    <option key={topic.topicId} value={topic.topicId}>{topic.title}</option>
                  ))}
                </select>
              </div>
              <button
                onClick={handlePushTask}
                disabled={isLoading}
                className="w-full py-3 bg-gray-800 text-white font-bold rounded-lg disabled:opacity-50 cursor-pointer hover:bg-gray-700 transition-colors"
              >
                {isLoading ? "推送中..." : "推送至魔法舱"}
              </button>
            </div>

            <div className="border-t border-gray-100 pt-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-lg font-semibold text-gray-700">AI 建议新增知识点</h2>
                  <p className="text-xs text-gray-400 mt-1">来自资源切片入库，确认后会加入知识图谱并回挂相关资源。</p>
                </div>
                <span className="text-xs px-3 py-1 rounded-full bg-blue-50 text-blue-600 border border-blue-100">
                  {graphProposals.length} 条待审核
                </span>
              </div>

              {graphProposals.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-400 text-center">
                  暂无待审核的知识节点建议。
                </div>
              ) : (
                <div className="space-y-3">
                  {graphProposals.slice(0, 5).map((proposal) => (
                    <div key={proposal.proposal_id} className="rounded-xl border border-blue-100 bg-white p-4 shadow-sm">
                      <div className="flex justify-between gap-4">
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-gray-800">{proposal.title}</p>
                          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{proposal.summary || proposal.reason}</p>
                          <p className="text-xs text-blue-500 mt-2">
                            父节点：{(proposal.parent_node_ids || []).join(', ') || '待系统补齐'} · 关系：{proposal.edge_type}
                          </p>
                        </div>
                        <div className="flex flex-col gap-2 shrink-0">
                          <button
                            onClick={() => handleApproveProposal(proposal)}
                            disabled={reviewingProposalId === proposal.proposal_id}
                            className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 disabled:opacity-50"
                          >
                            确认新增
                          </button>
                          <button
                            onClick={() => handleRejectProposal(proposal)}
                            disabled={reviewingProposalId === proposal.proposal_id}
                            className="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-medium hover:bg-gray-200 disabled:opacity-50"
                          >
                            拒绝
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 2. AI 学情报告（完整显示周一到周日七天） */}
        {activeTab === 'report' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
            {dataLoading ? (
              <div className="text-center py-10 text-gray-500">加载真实学情数据中...</div>
            ) : (
              <>
                <div className="grid grid-cols-3 gap-6 mb-6">
                  <div>
                    <p className="text-sm text-gray-500">今日获智智慧星</p>
                    <p className="text-2xl font-bold">
                      {learningData.todayStar} 
                      {learningData.todayStarIncrease > 0 && (
                        <span className="text-sm text-green-500 ml-2">↑ +{learningData.todayStarIncrease}</span>
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">当前专注时长</p>
                    <p className="text-2xl font-bold">
                      {learningData.focusTime} 分钟
                      {learningData.focusTime > 0 && (
                        <span className="text-sm text-green-500 ml-2">↑ 今日学习中</span>
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">提问积极性</p>
                    <p className="text-2xl font-bold">
                      {learningData.questionActiveness}
                      <span className="text-xs text-gray-400 ml-2">基于今日互动</span>
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-6">
                  {/* 完整显示周一到周日的柱状图 */}
                  <div>
                    <p className="text-sm font-medium mb-3">近期积分获取趋势</p>
                    <div className="flex items-end justify-around h-40">
                      {learningData.progressData.map((item, i) => (
                        <div key={i} className="flex flex-col items-center">
                          <div 
                            className="w-8 bg-sky-400 rounded-t transition-all duration-500" 
                            style={{ height: `${Math.max(10, item.score)}px` }}
                          ></div>
                          <span className="text-xs mt-2 text-gray-500">{item.day}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* 真实雷达图 */}
                  <div>
                    <p className="text-sm font-medium mb-3">AI 多维学情诊断雷达</p>
                    <div className="flex justify-center">
                      {renderRadarChart()}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* 3. 错题本与回放 (已重构版) */}
        {activeTab === 'mistake' && (
          <div className="flex flex-col md:flex-row gap-6 h-[600px]">
            
            {/* 左侧：智能错题流 (重构排版) */}
            <div className="flex-[4] bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm flex flex-col h-full border-t-4 border-pink-400">
              <div className="flex items-center gap-2 mb-2">
                <BookOpen className="text-pink-500" size={24} />
                <h2 className="text-xl font-bold text-gray-800">智能错题流</h2>
              </div>
              <p className="text-xs text-gray-500 mb-6 pb-4 border-b border-gray-100">
                系统依据 FSM 状态机自动抓取，拒绝无效刷题
              </p>
              
              <div className="flex-1 overflow-y-auto space-y-4 pr-2 scrollbar-hide">
                {dataLoading ? (
                  <div className="text-center py-6 text-gray-400 animate-pulse">正在从底层读取错题本...</div>
                ) : knowledgePoints.length === 0 ? (
                  <div className="text-center py-10 bg-gray-50 rounded-xl border border-dashed border-gray-200">
                    <span className="text-4xl block mb-2">🏆</span>
                    <p className="text-gray-500 font-medium">太棒了，暂无错题记录！</p>
                  </div>
                ) : (
                  knowledgePoints.map((kp) => (
                    <div key={kp.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                      <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-gradient-to-b from-pink-300 to-pink-500"></div>
                      <div className="flex justify-between items-start mb-3">
                        <h3 className="font-bold text-gray-800 text-base">{kp.name}</h3>
                        <span className="bg-pink-50 text-pink-600 text-xs px-2 py-1 rounded-md font-medium flex items-center gap-1">
                          <AlertCircle size={12} /> 待攻克
                        </span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-2 mb-4">
                        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 p-2 rounded-lg">
                          <Video size={14} className="text-blue-400" />
                          <span>相关视频: <strong className="text-gray-700">{kp.resourceCount}</strong></span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 p-2 rounded-lg">
                          <Clock size={14} className="text-orange-400" />
                          <span className="truncate" title={kp.lastReview}>首错: {kp.lastReview.split(' ')[0]}</span>
                        </div>
                      </div>
                      
                      <button 
                        onClick={async () => {
                          try {
                            await fetch(`${apiBaseUrl}/session/review/push`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ topic_id: kp.topicId })
                            });
                            alert("✅ 任务已推送到孩子的魔法舱！");
                          } catch (e) {
                            alert("❌ 推送失败，请检查网络");
                          }
                        }}
                        className="w-full py-2.5 bg-gray-900 text-white text-sm font-bold rounded-lg hover:bg-pink-500 transition-colors cursor-pointer"
                      >
                        ⚡ 立即派发重测任务
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* 右侧：全局知识图谱 (新增) */}
            <div className="flex-[6] bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm flex flex-col h-full border-t-4 border-blue-400 relative">
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="text-xl font-bold text-gray-800">全局知识拓扑图</h2>
                  <p className="text-xs text-gray-500 mt-1">点击知识节点查看详细掌握度</p>
                </div>
                <div className="bg-blue-50 text-blue-600 px-3 py-1 rounded-full text-xs font-medium border border-blue-100">
                  全自动生成
                </div>
              </div>

              {/* 画布区域 */}
              <div className="flex-1 bg-gray-50/50 border border-gray-100 rounded-xl overflow-auto p-8 relative flex items-center justify-center">
                {graphNodes.length === 0 ? (
                  <p className="text-gray-400">图谱生成中...</p>
                ) : (
                  <div className="flex flex-col items-center gap-8 relative">
                    {/* 一条贯穿的连接主线 */}
                    <div className="absolute top-10 bottom-10 w-1 bg-gradient-to-b from-blue-300 via-pink-300 to-purple-300 z-0"></div>
                    
                    {graphNodes.map((node, idx) => (
                      <div 
                        key={node.topic_id}
                        onClick={() => {
                          setSelectedNode(node);
                          setIsModalOpen(true);
                        }}
                        className="relative z-10 flex flex-col items-center cursor-pointer group"
                      >
                        <div className={`w-16 h-16 rounded-full flex items-center justify-center shadow-md border-4 transition-transform group-hover:scale-110 ${
                          idx === 0 ? 'bg-blue-100 border-blue-400 text-blue-700' :
                          idx === graphNodes.length - 1 ? 'bg-purple-100 border-purple-400 text-purple-700' :
                          'bg-white border-gray-300 text-gray-600'
                        }`}>
                          <span className="font-bold">{idx + 1}</span>
                        </div>
                        <div className="bg-white px-4 py-1.5 rounded-full shadow-sm border border-gray-200 mt-2 text-sm font-bold text-gray-700 group-hover:border-blue-400 group-hover:text-blue-600 transition-colors">
                          {node.title}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* 弹窗组件 (Modal) */}
            {isModalOpen && selectedNode && (
              <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
                  <div className="bg-gradient-to-r from-blue-500 to-blue-600 p-6 text-white relative">
                    <button 
                      onClick={() => setIsModalOpen(false)}
                      className="absolute top-4 right-4 text-white/70 hover:text-white cursor-pointer"
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                    </button>
                    <div className="flex items-center gap-3">
                      <div className="bg-white/20 p-2 rounded-lg">
                        <Info size={24} />
                      </div>
                      <div>
                        <p className="text-blue-100 text-xs font-medium uppercase tracking-wider">Node Details</p>
                        <h2 className="text-2xl font-bold">{selectedNode.title}</h2>
                      </div>
                    </div>
                  </div>
                  
                  <div className="p-6 space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="bg-gray-50 p-4 rounded-xl border border-gray-100 text-center">
                        <p className="text-xs text-gray-500 mb-1">绑定学习资源</p>
                        <p className="text-3xl font-black text-gray-800">{selectedNode.resources?.length || 0}</p>
                      </div>
                      <div className="bg-pink-50 p-4 rounded-xl border border-pink-100 text-center">
                        <p className="text-xs text-pink-600 mb-1">累积错题数</p>
                        <p className="text-3xl font-black text-pink-600">{knowledgePoints.find(k => k.topicId === selectedNode.topic_id) ? '1' : '0'}</p>
                      </div>
                    </div>
                    
                    <div className="bg-blue-50/50 border border-blue-100 p-4 rounded-xl">
                      <h4 className="text-sm font-bold text-gray-700 mb-2 flex items-center gap-2">
                        <Clock size={16} className="text-blue-500" /> 近期动态
                      </h4>
                      <p className="text-sm text-gray-600">
                        {knowledgePoints.find(k => k.topicId === selectedNode.topic_id) 
                          ? `最后出错时间: ${knowledgePoints.find(k => k.topicId === selectedNode.topic_id)?.lastReview}`
                          : "目前掌握良好，暂无报错记录。"}
                      </p>
                    </div>
                  </div>
                  
                  <div className="p-4 bg-gray-50 border-t border-gray-100 text-right">
                    <button 
                      onClick={() => setIsModalOpen(false)}
                      className="px-6 py-2 bg-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-300 transition-colors cursor-pointer"
                    >
                      关闭
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 4. 系统调试 */}
        {activeTab === 'debug' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-700 mb-4">引擎决策日志</h2>
            <p className="text-xs text-gray-400 mb-4">直接读取 logs/ 目录下的数据</p>
            {dataLoading ? (
              <div className="text-center py-6 text-gray-500">加载日志中...</div>
            ) : (
              <div className="bg-gray-900 rounded-lg p-4 font-mono text-xs text-green-400 mb-6 max-h-60 overflow-y-auto">
                {engineLogs.length === 0 ? (
                  <p>[INFO] 暂无日志数据，等待系统事件...</p>
                ) : (
                  engineLogs.map((log, i) => <p key={i}>{log}</p>)
                )}
              </div>
            )}
            <div className="bg-red-50 rounded-lg p-4 border border-red-200">
              <p className="text-sm text-red-600 font-medium mb-2">⚠️ 危险操作区</p>
              <p className="text-xs text-gray-500 mb-3">这里的操作将直接影响底层状态，无法撤销。</p>
              <button 
                onClick={async () => {
                  if(window.confirm("确定要清空本地上下文状态吗？此操作无法撤销！")) {
                    try {
                      await fetch(`${apiBaseUrl}/session/reset`, { method: "POST" });
                      alert("✅ 已清空本地上下文状态");
                      fetchAllData();
                    } catch (e) {
                      alert("❌ 操作失败");
                    }
                  }
                }}
                className="bg-white text-gray-700 border border-gray-200 px-3 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer"
              >
                清空本地上下文状态
              </button>
            </div>
          </div>
        )}
        {/* 5. 设置 */}
        {activeTab === 'settings' && <SettingsPanel />}
      </div>
    </div>
  );
}
