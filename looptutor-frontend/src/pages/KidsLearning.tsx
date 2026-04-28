import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, Star, Mic, Send, HelpCircle, Loader2, Volume2 } from 'lucide-react';
import { SessionAPI } from '../api/client';

const COMPANIONS: Record<string, string> = {
  "星空兔": "🐰",
  "小智龙": "🦖"
};

export default function KidsLearning() {
  const navigate = useNavigate();
  
  const [companion, setCompanion] = useState("星空兔");
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // ================= 🌟 新增：自动拉取家长推送的内容（只加了这一段，其他都没动） =================
  const [todayTopic, setTodayTopic] = useState('恐龙的秘密');
  useEffect(() => {
    // 每2秒自动刷新一次，家长推送后立刻显示
    const timer = setInterval(async () => {
      try {
        const res = await fetch("http://127.0.0.1:8090/v1/session/review-queue");
        const data = await res.json();
        if (data.topics && data.topics.length > 0) {
          // 取最新推送的内容，更新标题
          setTodayTopic(data.topics[data.topics.length - 1]);
        }
      } catch (e) {
        // 静默失败，不影响其他功能
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);
  // ================= 🌟 新增结束 =================

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
          {/* ================= 🌟 只改了这一行：把硬编码的标题改成动态的 ================= */}
          <h3 onMouseEnter={() => handleHoverRead("今日探索：" + todayTopic)} className="text-2xl font-bold text-blue mb-4 cursor-help hover:text-primary transition-colors flex items-center gap-2 w-fit">
            今日探索：{todayTopic} <Volume2 size={20} className="opacity-50" />
          </h3>
          {/* ================= 🌟 修改结束 ================= */}
          <div className="w-full flex-1 bg-black/5 rounded-2xl overflow-hidden flex items-center justify-center border-2 border-white/80">
            <video className="w-full h-full object-cover" controls src="https://www.w3schools.com/html/mov_bbb.mp4" />
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
                  onMouseEnter={() => handleHoverRead(msg.content)}
                  className={`p-4 rounded-2xl max-w-[80%] shadow-sm cursor-help transition-all duration-300 relative group ${
                    msg.role === 'user' ? 'bg-blue/10 text-dark rounded-tr-sm border border-blue/20 hover:bg-blue/20' : 'bg-white text-dark rounded-tl-sm border border-white/80 hover:bg-yellow-50 hover:border-yellow-200'
                  }`}
                >
                  {msg.content}
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
                className={`flex-[3] text-white font-bold py-4 rounded-2xl shadow-md transition-all duration-300 flex items-center justify-center gap-2 text-lg select-none relative overflow-hidden ${
                  isRecording 
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