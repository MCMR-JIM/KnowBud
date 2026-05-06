import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, BookOpen, Search, Smile, Mic, Send, Zap } from 'lucide-react';
import PdfViewer from '../components/PdfViewer';
import CelebrationModal from '../components/CelebrationModal';

// ---------------- 模块四：巨大化的左下角用户卡片 ----------------
const UserProgressCard = () => (
  <div className="flex items-center gap-5 bg-gradient-to-r from-purple-500 to-indigo-500 p-5 pr-10 rounded-3xl shadow-xl border-4 border-white/30 pointer-events-auto hover:-translate-y-2 transition-all cursor-pointer">
    <div className="w-20 h-20 rounded-full bg-white flex items-center justify-center text-5xl shadow-inner transform hover:scale-110 transition-transform">
      🐰
    </div>
    <div className="flex flex-col">
      <div className="flex items-center gap-3">
        <span className="text-white font-black text-3xl drop-shadow-md">能量: 15</span>
        <Zap size={28} className="text-yellow-300 fill-yellow-300 drop-shadow-md animate-pulse" />
      </div>
      <span className="text-purple-100 text-lg font-bold mt-1 opacity-90">今日已学 15 分钟</span>
    </div>
  </div>
);
// ---------------- 模块五：左侧常驻知识地图入口 ----------------
// ---------------- 模块五：巨大化、童趣化的知识地图入口 ----------------
const KnowledgeMapWidget = () => (
  <div className="flex flex-col items-center bg-white/95 backdrop-blur-md p-6 rounded-[2rem] shadow-[0_10px_30px_rgba(0,0,0,0.1)] border-4 border-indigo-100 pointer-events-auto hover:shadow-[0_15px_40px_rgba(99,102,241,0.2)] hover:-translate-y-2 transition-all cursor-pointer group">
    {/* 图标放大至 5xl，容器变大 */}
    <div className="w-24 h-24 bg-gradient-to-br from-indigo-50 to-purple-100 rounded-full flex items-center justify-center text-5xl mb-4 group-hover:scale-110 group-hover:rotate-6 transition-transform shadow-inner border-4 border-white">
      🗺️
    </div>
    {/* 文字加大加粗 */}
    <span className="text-indigo-900 font-black text-xl tracking-widest drop-shadow-sm">知识星图</span>
    {/* 状态标签变大，增加呼吸动画 */}
    <div className="mt-3 bg-green-100 text-green-700 text-sm px-4 py-1.5 rounded-full font-black border-2 border-green-200 animate-pulse">
      探索中...
    </div>
  </div>
);

// ---------------- 模块三：巨大化右侧 AI 互动答题卡片 ----------------
interface InteractionCardProps {
  state: any;
  onSend: (t: string) => void;
  onSelect: (o: string) => void;
}

const InteractionCard = ({ state, onSend, onSelect }: InteractionCardProps) => {
  const [inputText, setInputText] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => { setIsPlaying(false); }, [state.message]);

  const handleSendClick = () => {
    if (inputText.trim()) {
      onSend(inputText);
      setInputText(''); 
    }
  };

  return (
    // 🌟 卡片宽度从 280 爆改成 420px，圆角 24px，投影加深
    <div className="w-[420px] bg-white rounded-[24px] shadow-[0_16px_50px_rgb(0,0,0,0.15)] border-2 border-indigo-50 flex flex-col pointer-events-auto h-fit max-h-[85vh] overflow-hidden">
      
      {/* 顶部形象区 */}
      <div className="p-6 border-b-2 border-gray-50 flex items-center justify-between bg-indigo-50/30">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-white flex items-center justify-center text-4xl shadow-md border-2 border-indigo-100">
            {state.type === 'feedback' ? '🎉' : '🐰'}
          </div>
          <span className="font-black text-[#333333] text-2xl tracking-tight">星空兔</span>
        </div>
        
        {/* 语音按钮巨大化 */}
        <button 
          onClick={() => setIsPlaying(!isPlaying)}
          className={`w-12 h-12 rounded-full flex items-center justify-center cursor-pointer transition-all ${isPlaying ? 'bg-indigo-200 text-indigo-700 animate-pulse' : 'bg-white text-gray-400 hover:bg-indigo-50 hover:text-indigo-500 shadow-sm border border-gray-100'}`}
        >
          {isPlaying ? '⏸️' : '🔊'}
        </button>
      </div>

      {/* 对话区 */}
      <div className="flex-1 p-6 overflow-y-auto">
        {state.type !== 'none' && (
          <div className={`relative p-6 rounded-3xl rounded-tl-none border-2 mb-6 ${state.type === 'feedback' ? 'bg-orange-50 border-orange-200' : 'bg-[#F8F9FA] border-gray-100'}`}>
            <div className={`absolute top-0 -left-3 w-0 h-0 border-t-[12px] ${state.type === 'feedback' ? 'border-t-orange-50' : 'border-t-[#F8F9FA]'} border-l-[12px] border-l-transparent`}></div>
            <p className={`text-xl leading-[1.6] font-bold ${state.type === 'feedback' ? 'text-orange-600' : 'text-[#333333]'}`}>
              {state.message}
            </p>
          </div>
        )}

        {/* 选项按钮巨大化 */}
        {(state.type === 'choice' && state.options) && (
          <div className="flex flex-col gap-4">
            {state.options.map((opt: string) => (
              <button
                key={opt}
                onClick={() => onSelect(opt)}
                className="w-full py-5 px-6 rounded-2xl bg-white border-2 border-gray-100 text-[#333333] text-xl font-black shadow-sm hover:bg-orange-50 hover:border-orange-300 hover:text-orange-600 hover:-translate-y-1 active:scale-[0.98] active:bg-orange-500 active:text-white transition-all text-left flex items-center cursor-pointer"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 底部输入区 */}
      <div className="p-6 bg-white border-t-2 border-gray-50 flex flex-col gap-4">
        <div className="flex items-center gap-3 bg-gray-50 rounded-full px-5 py-3 border-2 border-gray-100 focus-within:border-indigo-300 transition-colors">
          <Smile size={28} className="text-gray-400 cursor-pointer hover:text-orange-500 transition-colors" />
          <input 
            type="text" 
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSendClick()}
            placeholder="打字告诉兔兔..."
            className="flex-1 bg-transparent text-lg outline-none text-[#333333] font-medium"
          />
          <Send onClick={handleSendClick} size={28} className={`cursor-pointer transition-colors hover:scale-110 ${inputText ? 'text-orange-500' : 'text-gray-300'}`} />
        </div>
        
        {/* 麦克风大按钮 */}
        <button className="w-full py-5 bg-[#F97316] text-white rounded-full font-black text-xl shadow-[0_8px_20px_rgba(249,115,22,0.3)] hover:shadow-[0_12px_25px_rgba(249,115,22,0.4)] hover:-translate-y-1 active:scale-[0.98] transition-all flex items-center justify-center gap-3 cursor-pointer">
          <Mic size={24} /> 按住说话
        </button>
      </div>
    </div>
  );
};

// ---------------- 主容器 ----------------
export default function StudyRoom() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const mode = searchParams.get('mode');

  const [interactionState, setInteractionState] = useState<any>({ type: 'none', message: '' });
  const [showCelebration, setShowCelebration] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [answeredPages, setAnsweredPages] = useState<number[]>([]);

  const mockCheckpoints: Record<number, any> = {
    2: { type: 'choice', message: '小朋友，三角龙有几个角呢？快选一个吧！', options: ['A. 1个', 'B. 2个', 'C. 3个', 'D. 没有角'] },
    4: { type: 'short_answer', message: '恐龙好神奇！打字或者语音告诉我，你最喜欢哪种恐龙呀？' }
  };

  const handlePageChange = (p: number) => {
    setCurrentPage(p);
    if (mockCheckpoints[p] && !answeredPages.includes(p)) {
      setInteractionState(mockCheckpoints[p]);
    } else {
      setInteractionState({ type: 'none', message: '' });
    }
  };

  const triggerSuccessFeedback = () => {
    setAnsweredPages(prev => [...prev, currentPage]);
    setInteractionState({ type: 'feedback', message: '答对啦！你真是个小天才！🚀' });
    setTimeout(() => setInteractionState({ type: 'none', message: '' }), 2500);
  };

  return (
    // 🌟 全局淡紫色渐变背景
    <div className="w-screen h-screen overflow-hidden relative bg-gradient-to-b from-[#F5F3FF] to-white flex flex-col">
      
      {/* 🌟 模块一：霸气的顶部通栏导航 (高度增至 h-24 / 96px) */}
      <header className="h-24 bg-white/90 backdrop-blur-md border-b-2 border-gray-100 flex items-center justify-between px-10 z-50 shadow-sm shrink-0">
        <div className="flex items-center gap-6">
          <button 
            onClick={() => navigate('/select')}
            className="flex items-center gap-3 px-6 py-3 bg-gray-50 text-[#333333] rounded-full font-black text-xl hover:bg-gray-200 active:scale-[0.96] transition-all cursor-pointer border border-transparent hover:border-gray-300 shadow-sm"
          >
            <ArrowLeft size={24} strokeWidth={3} /> 返回大厅
          </button>
          <button className="flex items-center gap-3 px-6 py-3 bg-indigo-50 text-indigo-600 rounded-full font-black text-xl hover:bg-indigo-100 active:scale-[0.96] transition-all cursor-pointer border border-transparent hover:border-indigo-200 shadow-sm">
            <BookOpen size={24} strokeWidth={3} /> 温故知新
          </button>
        </div>

        <div className="flex items-center gap-8">
          <div className="p-3 text-gray-400 hover:text-indigo-500 hover:bg-indigo-50 rounded-full cursor-pointer transition-colors">
            <Search size={32} strokeWidth={2.5} />
          </div>
          {/* 测试弹窗的按钮保留在头像旁边 */}
          <button onClick={() => setShowCelebration(true)} className="px-5 py-2.5 bg-yellow-400 text-yellow-900 font-bold rounded-full text-lg hover:scale-105 transition-transform shadow-md cursor-pointer">
            🏆 结课测试
          </button>
          <div className="w-14 h-14 rounded-full bg-orange-100 flex items-center justify-center text-orange-600 font-black text-2xl cursor-pointer shadow-sm border-2 border-orange-200 hover:scale-110 transition-transform">
            Li
          </div>
        </div>
      </header>

      {/* 主展示区 */}
      <main className="flex-1 relative flex items-center justify-center p-8 overflow-hidden">
        
        {/* 🌟 核心魔法：限制 PDF 容器的最大宽度，绝不让它挤压两侧的 UI 卡片 */}
        <div className="w-full h-full max-w-[55%] xl:max-w-[60%] relative z-10 flex items-center justify-center mx-auto">
          <PdfViewer 
            url="/test.pdf" 
            onRenderComplete={handlePageChange} 
          />
        </div>

        {/* 🌟 右侧 AI 互动区 */}
        <div className="absolute right-12 top-1/2 -translate-y-1/2 z-20">
          <InteractionCard 
            state={interactionState} 
            onSend={() => triggerSuccessFeedback()} 
            onSelect={() => triggerSuccessFeedback()} 
          />
        </div>

        {/* 🌟 模块五：左侧知识地图挂件 (位于屏幕左侧垂直居中偏上) */}
        <div className="absolute left-12 top-1/3 -translate-y-1/2 z-20">
          <KnowledgeMapWidget />
        </div>

       

        {/* 🌟 左下角用户卡片 */}
        <div className="absolute bottom-12 left-12 z-20">
          <UserProgressCard />
        </div>
      </main>

      {showCelebration && <CelebrationModal subjectName="恐龙科普" onClose={() => navigate('/select')} />}
    </div>
  );
}