import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, Star, Mic, Send, HelpCircle, Loader2, Volume2 } from 'lucide-react';
import { SessionAPI } from '../api/client';
import PdfViewer from './PdfViewer';

const COMPANIONS: Record<string, string> = {
  "星空兔": "🐰",
  "小智龙": "🦖"
};

export default function KidsLearning() {
  const navigate = useNavigate();
  const apiBaseUrl = 'http://127.0.0.1:8090/v1';

  type TopicResource = {
    resource_id: string;
    resource_name: string;
    media_type: string;
    resource_url: string;
  };

  const [companion, setCompanion] = useState("星空兔");
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // ================= 🌟 从复习队列/当前主线中同步 topic，并拉取节点资源 =================
  const [todayTopic, setTodayTopic] = useState('恐龙的秘密');
  const [todayTopicId, setTodayTopicId] = useState('');
  const [topicResources, setTopicResources] = useState<TopicResource[]>([]);
  const [previewResource, setPreviewResource] = useState<TopicResource | null>(null);

  useEffect(() => {
    const syncTopic = async () => {
      try {
        const queueRes = await fetch(`${apiBaseUrl}/session/review-queue`);
        if (queueRes.ok) {
          const queueData = await queueRes.json();
          const latestItem = queueData.items?.[queueData.items.length - 1];
          if (latestItem?.topic_id) {
            setTodayTopic(latestItem.title || latestItem.topic_id);
            setTodayTopicId(latestItem.topic_id);
            return;
          }
        }

        const stateRes = await fetch(`${apiBaseUrl}/session/state`);
        if (!stateRes.ok) {
          return;
        }

        const stateData = await stateRes.json();
        const currentTopicId = stateData.learning?.current_topic_id || '';
        if (!currentTopicId) {
          return;
        }

        const currentTopic = stateData.topics?.find((topic: any) => topic.topic_id === currentTopicId);
        setTodayTopic(currentTopic?.title || currentTopicId);
        setTodayTopicId(currentTopicId);
      } catch (e) {
        // 静默失败，不影响其他功能
      }
    };

    const timer = setInterval(async () => {
      await syncTopic();
    }, 2000);

    void syncTopic();
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchTopicResources = async () => {
      if (!todayTopicId) {
        setTopicResources([]);
        setPreviewResource(null);
        return;
      }

      try {
        const res = await fetch(`${apiBaseUrl}/resource/topics/${todayTopicId}`);
        if (!res.ok) {
          return;
        }

        const data = await res.json();
        const resources = (data.resources || []) as TopicResource[];
        setTopicResources(resources);

        // 🌟 把 pdf 加入可预览白名单，并兼容后缀名判断
        const previewable = resources.find((resource) =>
          ['video', 'image', 'audio', 'pdf'].includes(resource.media_type) ||
          resource.resource_url.toLowerCase().endsWith('.pdf')
        );
        setPreviewResource(previewable || null);
      } catch (e) {
        setTopicResources([]);
        setPreviewResource(null);
      }
    };

    void fetchTopicResources();
  }, [todayTopicId]);

  const [messages, setMessages] = useState([
    { role: 'assistant', content: `小朋友你好呀！我是你的${companion}，今天我们要探索什么秘密呢？` }
  ]);

  // ================= 🎙️ 状态与引用 =================
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  // 🌟 新增：用于聊天区自动滚动的锚点引用
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // 🌟 新增：监听 messages 数组，一有新消息就自动滑到底部
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // 原生 TTS 悬停点读
  const handleHoverRead = (text: string) => {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 0.85;
    utterance.pitch = 1.1;
    window.speechSynthesis.speak(utterance);
  };

  const resolveResourceUrl = (resourceUrl: string) => {
    if (resourceUrl.startsWith('http://') || resourceUrl.startsWith('https://')) {
      return resourceUrl;
    }
    return `http://127.0.0.1:8090${resourceUrl}`;
  };

  // ================= 🎙️ 录音控制逻辑 =================
  const startRecording = async () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    window.speechSynthesis.cancel();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        handleSendAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error("麦克风权限被拒绝:", error);
      alert("星空兔需要你的麦克风权限才能听见你说话哦！");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  // ================= 🚀 发送与流式播放逻辑 =================
  const handleSendAudio = async (blob: Blob) => {
    setIsLoading(true);
    setMessages(prev => [...prev, { role: 'user', content: '🎤 正在仔细听...' }]);

    try {
      const response = await SessionAPI.sendAudio(blob);
      const { recognized_text, reply_text } = response.data;

      setMessages(prev => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1].content = `🎤 ${recognized_text || '录音好像没声音哦'}`;
        return [...newMsgs, { role: 'assistant', content: reply_text }];
      });

      handleHoverRead(reply_text);
    } catch (error) {
      console.error("语音发送失败:", error);
      setMessages(prev => [...prev, { role: 'assistant', content: '哎呀，语音魔法失效了，请再试一次！' }]);
    } finally {
      setIsLoading(false);
    }
  };

  // 🌟 新增：处理 PDF 翻页并请求 AI 知识点
  const handlePdfPageTurned = async (pageNumber: number) => {
    if (!todayTopicId) return;

    setIsLoading(true);
    try {
      // 向后端发送请求，获取该页的知识点文本
      const response = await SessionAPI.getKnowledgeByPage(todayTopicId, pageNumber);
      const knowledgeText = response.data.knowledge_text;

      if (knowledgeText) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: knowledgeText // 将知识点作为 AI 的话推送到对话框
        }]);
      }
    } catch (error) {
      console.error("获取该页知识点失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendText = async (textToSend: string) => {
    if (!textToSend.trim() || isLoading) return;

    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    window.speechSynthesis.cancel();

    setMessages(prev => [...prev, { role: 'user', content: textToSend }]);
    setInputText('');
    setIsLoading(true);

    try {
      const res = await SessionAPI.sendTextRealtime(textToSend);
      const streamId = res.data.stream_id;

      setMessages(prev => [...prev, { role: 'assistant', content: res.data.reply_text }]);

      const audioUrl = `http://127.0.0.1:8090/v1/session/output/audio/stream/${streamId}`;
      const audio = new Audio(audioUrl);
      currentAudioRef.current = audio;

      audio.onended = () => { currentAudioRef.current = null; };
      audio.play().catch(e => console.error("音频播放被拦截:", e));

    } catch (error) {
      console.error("请求后端失败:", error);
      setMessages(prev => [...prev, { role: 'assistant', content: '哎呀，网络好像断开了！' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col min-h-screen p-6 gap-6">

      {/* 顶部导航 */}
      <div className="bg-white/60 backdrop-blur-md rounded-3xl p-4 px-6 flex justify-between items-center shadow-sm border border-white/50">
        <button onClick={() => navigate('/')} className="flex items-center gap-2 text-dark hover:text-primary transition-colors font-bold">
          <ChevronLeft size={24} /> 返回大厅
        </button>
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-4 text-xl font-bold text-dark">
            <span className="flex items-center gap-1 text-secondary"><Star fill="currentColor" /> 45</span>
            <span className="text-gray-300">|</span>
            <div className="flex items-center gap-2">
              <span>伙伴:</span>
              <select value={companion} onChange={(e) => setCompanion(e.target.value)} className="bg-transparent text-2xl cursor-pointer outline-none hover:scale-110 transition-transform appearance-none text-center">
                {Object.keys(COMPANIONS).map(name => <option key={name} value={name}>{COMPANIONS[name]}</option>)}
              </select>
            </div>
          </div>
        </div>
        <div className="w-24"></div>
      </div>

      {/* 核心内容区 */}
      <div className="flex flex-1 gap-6 h-[calc(100vh-140px)]">

        {/* 左侧：视频区 */}
        <div className="flex-[6] bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 flex flex-col">
          <h3 onMouseEnter={() => handleHoverRead("今日探索：" + todayTopic)} className="text-2xl font-bold text-blue mb-4 cursor-help hover:text-primary transition-colors flex items-center gap-2 w-fit">
            今日探索：{todayTopic} <Volume2 size={20} className="opacity-50" />
          </h3>
          <div className="w-full flex-1 bg-black/5 rounded-2xl overflow-hidden flex items-center justify-center border-2 border-white/80 relative">
            {previewResource?.media_type === 'video' ? (
              <video className="w-full h-full object-cover" controls src={resolveResourceUrl(previewResource.resource_url)} />
            ) : previewResource?.media_type === 'pdf' || previewResource?.resource_url.endsWith('.pdf') ? (
              // 🌟 引入刚写好的 PdfViewer
              <PdfViewer
                url={resolveResourceUrl(previewResource.resource_url)}
                onRenderComplete={handlePdfPageTurned}
              />
            ) : previewResource?.media_type === 'image' ? (
              <img className="w-full h-full object-contain" src={resolveResourceUrl(previewResource.resource_url)} alt={previewResource.resource_name} />
            ) : previewResource?.media_type === 'audio' ? (
              <div className="w-full h-full flex items-center justify-center">
                <audio controls src={resolveResourceUrl(previewResource.resource_url)} className="w-4/5" />
              </div>
            ) : (
              <div className="text-center text-gray-500 px-6">
                <p className="text-lg font-medium">当前节点暂无可预览媒体</p>
                <p className="text-sm mt-2">下方资源列表已按知识节点同步，可直接打开文档或切换到其他素材。</p>
              </div>
            )}
          </div>
          <div className="mt-4 bg-white/70 rounded-2xl border border-white/70 p-4 max-h-48 overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-bold text-dark">节点资源</p>
              <p className="text-xs text-gray-500">{topicResources.length} 份</p>
            </div>
            {topicResources.length === 0 ? (
              <p className="text-sm text-gray-400">这个知识节点下还没有上传资源。</p>
            ) : (
              <div className="space-y-2">
                {topicResources.map((resource) => {
                  const isPreviewable = ['video', 'image', 'audio', 'pdf'].includes(resource.media_type) || resource.resource_url.toLowerCase().endsWith('.pdf');
                  return (
                    <div key={resource.resource_id} className="flex items-center justify-between bg-white rounded-xl px-3 py-2 border border-white/80">
                      <div>
                        <p className="text-sm font-medium text-dark">{resource.resource_name}</p>
                        <p className="text-xs text-gray-500 uppercase">{resource.media_type}</p>
                      </div>
                      <div className="flex gap-2">
                        {isPreviewable && (
                          <button
                            onClick={() => setPreviewResource(resource)}
                            className="text-xs px-3 py-1 rounded-full bg-sky-100 text-sky-700 hover:bg-sky-200 transition-colors"
                          >
                            预览
                          </button>
                        )}
                        <a
                          href={resolveResourceUrl(resource.resource_url)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs px-3 py-1 rounded-full bg-pink-100 text-pink-700 hover:bg-pink-200 transition-colors"
                        >
                          打开
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* 右侧：聊天互动区 */}
        <div className="flex-[4] bg-white/40 backdrop-blur-md rounded-[30px] p-5 shadow-sm border border-white/50 flex flex-col">
          <h3 className="text-xl font-bold text-primary mb-4 flex items-center gap-2">
            <span className="bg-primary/20 p-2 rounded-xl">{COMPANIONS[companion]}</span> 伙伴连线
          </h3>

          <div className="flex-1 overflow-y-auto pr-2 space-y-4 mb-4 scrollbar-hide">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className="text-2xl">{msg.role === 'user' ? '👦' : COMPANIONS[companion]}</div>
                <div
                  className={`p-4 rounded-2xl max-w-[80%] shadow-sm transition-all duration-300 relative group flex items-start gap-2 ${msg.role === 'user' ? 'bg-blue/10 text-dark rounded-tr-sm border border-blue/20' : 'bg-white text-dark rounded-tl-sm border border-white/80'
                    }`}
                >
                  <span className="flex-1">{msg.content}</span>

                  {/* 🌟 改造为手动点击朗读按钮 */}
                  {msg.role === 'assistant' && (
                    <button
                      onClick={() => handleHoverRead(msg.content)}
                      className="p-1.5 bg-gray-50 text-gray-400 hover:text-primary hover:bg-pink-50 rounded-lg transition-colors flex-shrink-0 cursor-pointer border border-transparent hover:border-pink-200"
                      title="点击朗读"
                    >
                      <Volume2 size={16} />
                    </button>
                  )}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex gap-3 flex-row">
                <div className="text-2xl">{COMPANIONS[companion]}</div>
                <div className="p-4 rounded-2xl bg-white text-dark rounded-tl-sm flex items-center gap-2"><Loader2 className="animate-spin text-primary" size={20} /><span className="text-sm">思考中...</span></div>
              </div>
            )}
            {/* 🌟 自动滚动的目标锚点 */}
            <div ref={messagesEndRef} />
          </div>

          {/* 底部输入区 */}
          <div className="flex flex-col gap-3 mt-auto">
            <div className="flex gap-2">
              <input type="text" value={inputText} onChange={(e) => setInputText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSendText(inputText)} disabled={isLoading} placeholder="或者打字告诉我..." className="flex-1 bg-white/80 border-2 border-white rounded-2xl px-4 py-3 outline-none focus:border-primary shadow-sm disabled:opacity-50" />
              <button onClick={() => handleSendText(inputText)} disabled={isLoading} className="bg-white/80 text-primary border-2 border-white hover:border-primary hover:bg-primary hover:text-white p-3 rounded-2xl transition-all shadow-sm disabled:opacity-50">
                <Send size={20} />
              </button>
            </div>

            <div className="flex gap-3">
              {/* 🌟 升级后的录音按钮：带呼吸波纹动画 */}
              <button
                onMouseDown={startRecording}
                onMouseUp={stopRecording}
                onMouseLeave={stopRecording}
                disabled={isLoading}
                className={`flex-[3] text-white font-bold py-4 rounded-2xl shadow-md transition-all duration-300 flex items-center justify-center gap-2 text-lg select-none relative overflow-hidden ${isRecording
                    ? 'bg-red-500 scale-95 shadow-[0_0_20px_rgba(239,68,68,0.6)]'
                    : 'bg-primary hover:bg-primary/90 hover:shadow-lg'
                  }`}
              >
                {isRecording && (
                  <span className="absolute inset-0 bg-white/20 animate-ping rounded-2xl"></span>
                )}
                <Mic size={24} className={isRecording ? "animate-bounce" : ""} />
                {isRecording ? '正在仔细听...' : '按住说话'}
              </button>

              <button onClick={() => handleSendText("我没听懂，能用更简单的话讲一遍吗？")} disabled={isLoading} className="flex-[1] bg-white/80 text-dark font-bold py-4 rounded-2xl shadow-sm border-2 border-white hover:border-gray-200 transition-colors flex items-center justify-center flex-col text-xs gap-1 disabled:opacity-50">
                <HelpCircle size={18} className="text-blue" />没听懂
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
