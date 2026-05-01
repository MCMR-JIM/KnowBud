import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, Star, Mic, Send, HelpCircle, Loader2, Volume2 } from 'lucide-react';
import { SessionAPI } from '../api/client';
// 引入新组件
import DynamicMediaBoard from '../components/DynamicMediaBoard';

const COMPANIONS: Record<string, string> = {
  "星空兔": "🐰",
  "小智龙": "🦖"
};

export default function KidsLearning() {
  const navigate = useNavigate();
  const [companion, setCompanion] = useState("星空兔");
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: `小朋友你好呀！我是你的${companion}，今天我们要探索什么秘密呢？` }
  ]);

  // 控制媒体区状态
  const [mediaConfig, setMediaConfig] = useState<{type: 'video' | 'iframe' | 'whiteboard', url?: string}>({
    type: 'whiteboard' 
  });

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  // 🌟 新增：轮询后端事件指令
  useEffect(() => {
    let lastEventId = 0;
    const pollEvents = async () => {
      try {
        const res = await SessionAPI.getEvents(lastEventId);[cite: 2]
        const events = res.data.events || [];
        if (events.length > 0) {
          events.forEach((event: any) => {
            // 解析后端 session_backend 下发的资源指令
            if (event.kind === 'resource_push') {
              setMediaConfig({
                type: event.payload.resource_type,
                url: event.payload.url
              });
            }
            lastEventId = event.event_id;
          });
        }
      } catch (error) {
        console.error("获取后端事件失败:", error);
      }
    };

    const timer = setInterval(pollEvents, 3000); // 每3秒轮询一次[cite: 2]
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // 修改后的点读函数：仅由按钮触发
  const handleManualRead = (text: string) => {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 0.85;
    window.speechSynthesis.speak(utterance);
  };

  // ... (startRecording, stopRecording, handleSendAudio, handleSendText 逻辑保持不变) ...

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
              <select value={companion} onChange={(e) => setCompanion(e.target.value)} className="bg-transparent text-2xl cursor-pointer outline-none appearance-none text-center">
                {Object.keys(COMPANIONS).map(name => <option key={name} value={name}>{COMPANIONS[name]}</option>)}
              </select>
            </div>
          </div>
        </div>
        <div className="w-24"></div>
      </div>

      {/* 核心内容区 */}
      <div className="flex flex-1 gap-6 h-[calc(100vh-140px)]">
        
        {/* 左侧：媒体区缩小为 flex-[4] (资源为辅)[cite: 1] */}
        <div className="flex-[4] bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 flex flex-col">
          <DynamicMediaBoard type={mediaConfig.type} url={mediaConfig.url} />
        </div>

        {/* 右侧：聊天互动区扩大为 flex-[6] (聊天为主)[cite: 1] */}
        <div className="flex-[6] bg-white/40 backdrop-blur-md rounded-[30px] p-5 shadow-sm border border-white/50 flex flex-col">
          <h3 className="text-xl font-bold text-primary mb-4 flex items-center gap-2">
            <span className="bg-primary/20 p-2 rounded-xl">{COMPANIONS[companion]}</span> 伙伴连线
          </h3>
          
          <div className="flex-1 overflow-y-auto pr-2 space-y-4 mb-4 scrollbar-hide">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className="text-2xl">{msg.role === 'user' ? '👦' : COMPANIONS[companion]}</div>
                <div 
                  className={`p-4 rounded-2xl max-w-[80%] shadow-sm relative group transition-all ${
                    msg.role === 'user' ? 'bg-blue/10 text-dark rounded-tr-sm border border-blue/20' : 'bg-white text-dark rounded-tl-sm border border-white/80'
                  }`}
                >
                  {msg.content}

                  {/* 🌟 优化后的播放按钮：仅在老师消息旁显示[cite: 1] */}
                  {msg.role === 'assistant' && (
                    <button 
                      onClick={() => handleManualRead(msg.content)}[cite: 1]
                      className="absolute -right-10 top-1/2 -translate-y-1/2 p-2 bg-white/80 rounded-full shadow-sm text-primary opacity-0 group-hover:opacity-100 transition-opacity hover:bg-primary hover:text-white"
                      title="朗读这段话"
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
            <div ref={messagesEndRef} />
          </div>

          {/* 底部输入区保持原有结构 */}
          <div className="flex flex-col gap-3 mt-auto">
            {/* ... 原有 input 和 录音按钮逻辑 ... */}
          </div>
        </div>
      </div>
    </div>
  );
}