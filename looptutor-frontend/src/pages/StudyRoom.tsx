import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, BookOpen, Search, Smile, Mic, Send, Zap, Loader2, Volume2, Check, MessageCircle } from 'lucide-react';
import PdfViewer from '../components/PdfViewer';
import CelebrationModal from '../components/CelebrationModal';
import { SessionAPI } from '../api/client';
import { useAppDialog } from '../components/AppDialog';

// ---------------- 模块一：左下角纯净版数据卡片 (与兔头分离) ----------------
const UserStatsCard = () => (
  <div className="w-full flex flex-col items-center justify-center gap-3 bg-white/60 backdrop-blur-xl p-6 rounded-[2.5rem] shadow-lg border-2 border-white pointer-events-auto hover:-translate-y-1 transition-all cursor-pointer">
    <div className="flex items-center gap-2">
      <Zap size={32} className="text-fuchsia-400 fill-fuchsia-400 animate-pulse shrink-0" />
      <span className="text-indigo-950 font-black text-3xl tracking-tight">15 能量</span>
    </div>
    <div className="bg-white/60 px-4 py-1.5 rounded-full border border-white shadow-sm mt-1">
      <span className="text-gray-600 text-sm font-bold">今日已学 15 分钟</span>
    </div>
  </div>
);

// ---------------- 模块二：左侧知识星图 ----------------
interface KnowledgeNode { id: string; title: string; status: 'completed' | 'current' | 'locked'; icon: string; }

const InlineKnowledgeMap = ({ nodes }: { nodes: KnowledgeNode[] }) => (
  <div className="w-full flex flex-col items-center bg-white/60 backdrop-blur-xl p-8 rounded-[2.5rem] shadow-lg border-2 border-white pointer-events-auto">
    <div className="bg-purple-100 text-purple-800 px-5 py-2 rounded-full font-black text-sm mb-6 flex items-center gap-2 border border-purple-200">
      🗺️ 探索星图
    </div>
    
    <div className="flex flex-col items-center relative w-full">
      {nodes.map((node, index) => {
        const isCompleted = node.status === 'completed';
        const isCurrent = node.status === 'current';

        return (
          <div key={node.id} className="flex flex-col items-center w-full">
            <div className="relative group flex justify-center w-full">
              <div className={`w-[72px] h-[72px] rounded-full flex items-center justify-center text-3xl border-4 z-10 relative transition-all duration-300 ${
                isCompleted 
                  ? 'bg-indigo-100 border-indigo-300 text-indigo-600 shadow-[0_0_15px_rgba(99,102,241,0.3)]' 
                  : isCurrent
                  ? 'bg-gradient-to-tr from-purple-400 to-fuchsia-400 border-white text-white shadow-[0_0_20px_rgba(217,70,239,0.6)] animate-pulse'
                  : 'bg-gray-100 border-gray-200 grayscale opacity-60'
              }`}>
                {isCompleted ? <Check size={36} strokeWidth={4} /> : node.icon}
              </div>
              
              {isCurrent && (
                <div className="absolute left-[65%] top-1/2 -translate-y-1/2 bg-fuchsia-100 text-fuchsia-600 px-3 py-1.5 rounded-full text-xs font-black shadow-sm whitespace-nowrap border border-fuchsia-200 z-20">
                  当前位置
                </div>
              )}
            </div>

            <span className={`mt-3 font-black text-base text-center ${
              isCompleted ? 'text-indigo-600' : isCurrent ? 'text-fuchsia-600' : 'text-gray-400'
            }`}>
              {node.title}
            </span>

            {index < nodes.length - 1 && (
              <div className={`w-1.5 h-8 my-2 rounded-full transition-colors duration-300 ${
                isCompleted ? 'bg-indigo-300 shadow-[0_0_10px_rgba(99,102,241,0.4)]' : 'bg-gray-200/80'
              }`} />
            )}
          </div>
        );
      })}
    </div>
  </div>
);

// ---------------- 模块三：右侧 AI 互动答题卡片 (配合上方占位) ----------------
interface InteractionCardProps {
  state: any; onSend: (t: string) => void; onSelect: (o: string) => void;
  isLoading: boolean; isRecording: boolean; onStartRecord: () => void; onStopRecord: () => void; onPlayVoice: (text: string) => void;
}

const InteractionCard = ({ state, onSend, onSelect, isLoading, isRecording, onStartRecord, onStopRecord, onPlayVoice }: InteractionCardProps) => {
  const [inputText, setInputText] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => { setIsPlaying(false); }, [state.message]);
  const handleSendClick = () => { if (inputText.trim() && !isLoading) { onSend(inputText); setInputText(''); } };

  return (
    // 🌟 配合上方的兔头，这里采用 flex-1 填满剩余高度，让对话框显得更完整
    <div className="w-full flex-1 min-h-0 bg-white/70 backdrop-blur-2xl rounded-[2.5rem] shadow-lg border-2 border-white flex flex-col pointer-events-auto overflow-hidden">
      
      {/* 去掉兔头后的清爽 Header */}
      <div className="p-5 border-b-2 border-white/50 flex items-center justify-between bg-gradient-to-r from-purple-50/50 to-fuchsia-50/50">
        <div className="flex items-center gap-2 pl-2">
          <MessageCircle className="text-purple-500" size={24} />
          <span className="font-black text-indigo-950 text-xl tracking-tight">星空兔伴学</span>
        </div>
      </div>

      <div className="flex-1 p-6 overflow-y-auto custom-scrollbar">
        {state.type !== 'none' && (
          <div className={`relative p-6 rounded-3xl rounded-tl-none border-2 mb-6 shadow-sm ${state.type === 'feedback' ? 'bg-fuchsia-50 border-fuchsia-200' : 'bg-white/80 border-purple-100'}`}>
            <div className={`absolute top-0 -left-3 w-0 h-0 border-t-[12px] ${state.type === 'feedback' ? 'border-t-fuchsia-50' : 'border-t-white'} border-l-[12px] border-l-transparent`}></div>
            <div className="flex justify-between items-start gap-4">
              <p className={`text-xl leading-[1.6] font-bold flex-1 ${state.type === 'feedback' ? 'text-fuchsia-600' : 'text-indigo-900'}`}>{state.message}</p>
              <button 
                type="button"
                onClick={() => {
                  setIsPlaying(!isPlaying);
                  if (!isPlaying && state.message) onPlayVoice(state.message);
                  else window.speechSynthesis.cancel();
                }}
                className={`shrink-0 w-12 h-12 rounded-full flex items-center justify-center cursor-pointer transition-all shadow-sm ${isPlaying ? 'bg-purple-500 text-white animate-pulse' : 'bg-white text-purple-500 hover:bg-purple-50 border-2 border-purple-100'}`}
              >
                {isPlaying ? <Loader2 className="animate-spin" size={24} /> : <Volume2 size={24} strokeWidth={2.5} />}
              </button>
            </div>
          </div>
        )}

        {isLoading && (
           <div className="flex items-center gap-3 text-purple-500 font-bold mb-4 ml-2 bg-purple-50 w-fit px-4 py-2 rounded-full shadow-sm">
             <Loader2 className="animate-spin" size={20} /> 星空兔正在思考...
           </div>
        )}

        {(state.type === 'choice' && state.options) && !isLoading && (
          <div className="flex flex-col gap-4">
            {state.options.map((opt: string) => (
              <button
                key={opt} type="button" onClick={() => onSelect(opt)}
                className="w-full py-5 px-6 rounded-2xl bg-white/80 border-2 border-purple-50 text-indigo-900 text-xl font-black shadow-sm hover:bg-purple-50 hover:border-purple-300 hover:text-purple-700 hover:-translate-y-1 active:scale-[0.98] active:bg-purple-500 active:text-white transition-all text-left cursor-pointer"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="p-6 bg-white/50 backdrop-blur-md border-t-2 border-white flex flex-col gap-4">
        <div className="flex items-center gap-3 bg-white/80 rounded-2xl px-5 py-4 border-2 border-purple-50 focus-within:border-purple-300 transition-colors">
          <Smile size={28} className="text-purple-300 cursor-pointer hover:text-purple-500" />
          <input 
            type="text" value={inputText} onChange={(e) => setInputText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleSendClick(); } }}
            disabled={isLoading} placeholder="打字告诉兔兔..."
            className="flex-1 min-w-0 bg-transparent text-lg outline-none text-indigo-900 font-medium disabled:opacity-50"
          />
          <Send onClick={handleSendClick} size={28} className={`shrink-0 cursor-pointer transition-colors hover:scale-110 ${inputText && !isLoading ? 'text-purple-500' : 'text-purple-200'}`} />
        </div>
        
        <button 
          type="button" onMouseDown={onStartRecord} onMouseUp={onStopRecord} onMouseLeave={onStopRecord} disabled={isLoading}
          className={`w-full py-5 text-white rounded-2xl font-black text-xl hover:-translate-y-1 active:scale-[0.98] transition-all flex items-center justify-center gap-3 cursor-pointer relative overflow-hidden disabled:opacity-50 ${isRecording ? 'bg-fuchsia-400 shadow-[0_0_25px_rgba(232,121,249,0.6)]' : 'bg-gradient-to-r from-purple-400 to-fuchsia-500 shadow-lg hover:shadow-xl'}`}
        >
          {isRecording && <span className="absolute inset-0 bg-white/20 animate-ping rounded-2xl"></span>}
          <Mic size={26} className={isRecording ? "animate-bounce" : ""} /> 
          {isRecording ? '正在仔细听...' : '按住说话'}
        </button>
      </div>
    </div>
  );
};

// ---------------- 主容器 ----------------
export default function StudyRoom() {
  const navigate = useNavigate();
  const appDialog = useAppDialog();

  const [interactionState, setInteractionState] = useState<any>({ type: 'none', message: '' });
  const [showCelebration, setShowCelebration] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [answeredPages, setAnsweredPages] = useState<number[]>([]);

  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  const mockBackendTreeNodes = [
    { id: '1', title: '恐龙时代', status: 'completed', icon: '🦕' },
    { id: '2', title: '火山爆发', status: 'current', icon: '🌋' },
    { id: '3', title: '陨石撞击', status: 'locked', icon: '☄️' }
  ];

  const handleHoverRead = (text: string) => {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 0.85;
    utterance.pitch = 1.1;
    window.speechSynthesis.speak(utterance);
  };

  const handleSendText = async (textToSend: string) => {
    if (!textToSend.trim() || isLoading) return;
    if (currentAudioRef.current) { currentAudioRef.current.pause(); currentAudioRef.current = null; }
    window.speechSynthesis.cancel();
    setIsLoading(true);
    setInteractionState({ type: 'none', message: '' });

    try {
      const res = await SessionAPI.sendTextRealtime(textToSend);
      setInteractionState({ type: 'feedback', message: res.data.reply_text });
      handleHoverRead(res.data.reply_text);
      if (!answeredPages.includes(currentPage)) setAnsweredPages(prev => [...prev, currentPage]);
    } catch (error) {
      setInteractionState({ type: 'feedback', message: '哎呀，网络好像断开了！' });
    } finally {
      setIsLoading(false);
    }
  };

  const startRecording = async () => {
    if (currentAudioRef.current) { currentAudioRef.current.pause(); currentAudioRef.current = null; }
    window.speechSynthesis.cancel();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        handleSendAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };
      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      await appDialog.alert("星空兔需要你的麦克风权限才能听见你说话哦！", { title: '需要麦克风权限', intent: 'warning' });
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleSendAudio = async (blob: Blob) => {
    setIsLoading(true);
    setInteractionState({ type: 'none', message: '' });
    try {
      const response = await SessionAPI.sendAudio(blob);
      setInteractionState({ type: 'feedback', message: response.data.reply_text });
      handleHoverRead(response.data.reply_text);
      if (!answeredPages.includes(currentPage)) setAnsweredPages(prev => [...prev, currentPage]);
    } catch (error) {
      setInteractionState({ type: 'feedback', message: '哎呀，语音魔法失效了，请再试一次！' });
    } finally {
      setIsLoading(false);
    }
  };

  const mockCheckpoints: Record<number, any> = {
    2: { type: 'choice', message: '小朋友，三角龙有几个角呢？快选一个吧！', options: ['A. 1个', 'B. 2个', 'C. 3个', 'D. 没有角'] },
    4: { type: 'short_answer', message: '恐龙好神奇！打字或者语音告诉我，你最喜欢哪种恐龙呀？' }
  };

  const handlePageChange = async (p: number) => {
    setCurrentPage(p);
    if (answeredPages.includes(p)) { setInteractionState({ type: 'none', message: '' }); return; }
    if (mockCheckpoints[p]) {
      setInteractionState(mockCheckpoints[p]);
      handleHoverRead(mockCheckpoints[p].message);
    } else {
      setInteractionState({ type: 'none', message: '' });
    }
  };

  return (
    // 🌟 全局加入统一内边距，确保边缘呼吸感
    <div className="w-screen h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-purple-50 to-fuchsia-50 flex flex-col py-6 px-6 md:px-10 gap-6">
      
      {/* 🌟 1. 严格统一宽度：导航栏与主界面完全对齐 */}
      <header className="w-full max-w-[1800px] mx-auto h-20 md:h-24 bg-white/50 backdrop-blur-2xl border-2 border-white/70 rounded-3xl flex items-center justify-between px-8 shadow-sm shrink-0 z-50">
        <div className="flex items-center gap-6">
          <button 
            type="button" onClick={() => navigate(-1)} 
            className="flex items-center gap-2 px-5 py-2.5 bg-white/70 text-indigo-900 rounded-full font-black text-lg hover:bg-white active:scale-[0.96] transition-all cursor-pointer border border-white shadow-sm"
          >
            <ArrowLeft size={20} strokeWidth={3} /> 返回上一页
          </button>
          <button type="button" className="flex items-center gap-2 px-5 py-2.5 bg-purple-100 text-purple-700 rounded-full font-black text-lg hover:bg-purple-200 active:scale-[0.96] transition-all cursor-pointer border border-purple-200 shadow-sm">
            <BookOpen size={20} strokeWidth={3} /> 温故知新
          </button>
        </div>

        <div className="flex items-center gap-6">
          <div className="p-3 text-purple-300 hover:text-purple-600 hover:bg-purple-50 rounded-full cursor-pointer transition-colors">
            <Search size={28} strokeWidth={2.5} />
          </div>
          <button type="button" onClick={() => setShowCelebration(true)} className="px-6 py-2.5 bg-gradient-to-r from-purple-500 to-fuchsia-500 text-white font-bold rounded-full text-lg hover:scale-105 transition-transform shadow-md cursor-pointer border-2 border-purple-300">
            🏆 结课测试
          </button>
          <div className="w-12 h-12 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 font-black text-xl cursor-pointer shadow-sm border-2 border-purple-200 hover:scale-110 transition-transform">
            Li
          </div>
        </div>
      </header>

      {/* 🌟 主界面大框 (与上方 Header 使用同等 max-w 对齐) */}
      <main className="flex-1 w-full max-w-[1800px] mx-auto bg-white/40 backdrop-blur-2xl border-2 border-white/60 rounded-[2.5rem] shadow-sm flex flex-row items-stretch justify-between p-6 xl:p-8 gap-6 xl:gap-8 relative overflow-hidden">
        
        {/* 左侧列：纯净进度树 + 数据卡片 */}
        <div className="w-[280px] xl:w-[320px] shrink-0 flex flex-col gap-6 justify-center z-20 h-full">
          <InlineKnowledgeMap nodes={mockBackendTreeNodes as any} />
          <UserStatsCard />
        </div>

        {/* 中间列：PDF阅读区 (享受了被释放出来的巨大空间) */}
        <div className="flex-1 h-full relative z-10 bg-white/30 rounded-3xl border border-white/50 p-4 shadow-inner flex items-center justify-center min-w-[400px]">
          <PdfViewer url="/test.pdf" onRenderComplete={handlePageChange} />
        </div>

        {/* 🌟 2. 右侧列：巨大 Live2D 预留位 + 聊天对话框 */}
        <div className="w-[360px] xl:w-[420px] shrink-0 flex flex-col items-center justify-end z-20 gap-6 h-full relative">
          
          {/* 未来的数字人占位 (带悬浮动画和发光底座) */}
          <div className="w-36 h-36 xl:w-44 xl:h-44 shrink-0 rounded-full bg-gradient-to-br from-white to-fuchsia-100 border-4 border-white shadow-[0_15px_40px_rgba(217,70,239,0.25)] flex items-center justify-center text-6xl xl:text-7xl relative z-30 transform transition-transform hover:scale-105 animate-[bounce_4s_ease-in-out_infinite]">
            🐰
            <div className="absolute -bottom-3 bg-fuchsia-100 text-fuchsia-600 px-4 py-1.5 rounded-full text-xs font-black shadow-sm border border-white whitespace-nowrap">
              Live2D 待接入
            </div>
          </div>

          <InteractionCard 
            state={interactionState} isLoading={isLoading} isRecording={isRecording}
            onStartRecord={startRecording} onStopRecord={stopRecording} onPlayVoice={handleHoverRead}
            onSend={(text) => handleSendText(text)} onSelect={(option) => handleSendText(option)} 
          />
        </div>
      </main>

      {showCelebration && <CelebrationModal subjectName="恐龙科普" onClose={() => navigate('/select')} />}
    </div>
  );
}
