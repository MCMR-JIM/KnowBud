import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import * as echarts from 'echarts';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const apiBaseUrl = 'http://localhost:8090/v1';
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
  const [engineLogs, setEngineLogs] = useState<string[]>([]);
  const [dataLoading, setDataLoading] = useState(false);

  const radarRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);

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
        const topics = (graphData.topics || []).map((topic: any) => ({
          topicId: topic.topic_id,
          title: topic.title,
        }));
        setKnowledgeTopics(topics);
        setSelectedUploadTopicId((prev) => topics.some((topic: { topicId: string }) => topic.topicId === prev) ? prev : (topics[0]?.topicId || ''));
        setSelectedPushTopicId((prev) => topics.some((topic: { topicId: string }) => topic.topicId === prev) ? prev : (topics[0]?.topicId || ''));
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

  useEffect(() => {
    if(!radarRef.current || !barRef.current) return;
    const radarChart = echarts.init(radarRef.current);
    const barChart = echarts.init(barRef.current);

    radarChart.setOption({
      radar: {
        radius: '65%',
        indicator: [
          { name: '提问积极性', max: 100 },
          { name: '专注度', max: 100 },
          { name: '思考响应性', max: 100 },
          { name: '逻辑理解力', max: 100 },
          { name: '知识掌握度', max: 100 }
        ]
      },
      series: [{
        type: 'radar',
        data: [{
          value: [learningData.radarData.questionActiveness, learningData.radarData.focus, learningData.radarData.thinking, learningData.radarData.logic, learningData.radarData.knowledge],
          areaStyle: { opacity: 0.3 },
          itemStyle: { color: '#ec4899' }
        }]
      }]
    });

    barChart.setOption({
      xAxis: { data: learningData.progressData.map(item => item.day) },
      yAxis: {},
      series: [{
        type: 'bar',
        itemStyle: { color: '#38bdf8' },
        data: learningData.progressData.map(item => item.score)
      }]
    });

    return () => {
      radarChart.dispose();
      barChart.dispose();
    }
  }, [learningData]);

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
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("topic_id", selectedUploadTopicId);
      formData.append("resource_name", resourceName);
      formData.append("category", uploadCategory);

      const res = await fetch(`${apiBaseUrl}/resource/upload`, {
        method: "POST",
        body: formData
      });

      if (res.ok) {
        alert("✅ 资源上传成功，已绑定到知识节点");
        setUploadFile(null);
        setResourceName("");
        fetchAllData();
      } else {
        alert("❌ 上传失败，请检查后端接口");
      }
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
          <h1 className="text-lg font-semibold flex items-center gap-2">🤖 家长控制台</h1>
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
                  <div>
                    <p className="text-sm font-medium mb-3">近期积分获取趋势</p>
                    <div ref={barRef} className="h-40"></div>
                  </div>
                  <div>
                    <p className="text-sm font-medium mb-3">AI 多维学情诊断雷达</p>
                    <div ref={radarRef} className="h-40"></div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* 3. 错题本与回放 */}
        {activeTab === 'mistake' && (
          <div className="grid grid-cols-2 gap-6">
            <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-pink-500 mb-4">📚 AI 智能错题本</h2>
              <p className="text-xs text-gray-400 mb-4">系统依据 FSM 状态机，自动抓取未掌握的知识点。</p>
              {dataLoading ? (
                <div className="text-center py-6 text-gray-500">加载错题数据中...</div>
              ) : knowledgePoints.length === 0 ? (
                <div className="text-center py-6 text-gray-400">暂无错题数据，孩子表现很棒！</div>
              ) : (
                <div className="space-y-3">
                  {knowledgePoints.map((kp) => (
                    <div key={kp.id} className="bg-gray-50 rounded-lg p-3">
                      <p className="text-sm font-medium">{kp.name}</p>
                      <p className="text-xs text-gray-500 mt-1">节点资源数：{kp.resourceCount}</p>
                      <p className="text-xs text-gray-400">首次出错时间：{kp.lastReview}</p>
                      <button 
                        onClick={async () => {
                          try {
                            await fetch(`${apiBaseUrl}/session/review/push`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ topic_id: kp.topicId })
                            });
                            alert("✅ 已再次推送提问");
                          } catch (e) {
                            alert("❌ 推送失败");
                          }
                        }}
                        className="mt-2 text-xs text-blue-500 cursor-pointer hover:underline"
                      >
                        再次推送提问
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-700 mb-4">🎙️ 交互原声与回放库</h2>
              <div className="text-center py-6 text-gray-400">
                回放功能需对接后端音频存储接口
              </div>
            </div>
          </div>
        )}

        {/* 4. 系统调试 */}
        {activeTab === 'debug' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-700 mb-4">⚙️ 系统调试控制台</h2>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="bg-gray-50 p-3 rounded-lg">
                <p className="text-xs text-gray-500">运行状态</p>
                <p className="text-green-600 font-medium">运行中 ✅</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-lg">
                <p className="text-xs text-gray-500">当前智慧星</p>
                <p className="text-blue-600 font-medium">{learningData.todayStar}</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-lg">
                <p className="text-xs text-gray-500">日志条数</p>
                <p className="text-purple-600 font-medium">{engineLogs.length}</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-lg">
                <p className="text-xs text-gray-500">错题数量</p>
                <p className="text-pink-600 font-medium">{knowledgePoints.length}</p>
              </div>
            </div>

            <div className="bg-gray-900 rounded-lg p-4 font-mono text-xs text-green-400 max-h-60 overflow-y-auto">
              {engineLogs.length === 0 ? <p className="text-gray-400">暂无日志</p> : engineLogs.map((log, i) => <p key={i}>{log}</p>)}
            </div>

            <div className="mt-4 p-4 bg-red-50 rounded-lg border border-red-200">
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
      </div>
    </div>
  );
}