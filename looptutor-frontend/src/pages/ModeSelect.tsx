import { useNavigate } from 'react-router-dom';
import { ArrowLeft, RefreshCw, Rocket, Sparkles } from 'lucide-react';

export default function ModeSelect() {
  const navigate = useNavigate();

  return (
    // 🌟 全局背景：1:1 复刻学习界面的极淡紫渐变
    <div className="w-screen h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-purple-50 to-fuchsia-50 flex flex-col items-center justify-center p-8 relative">
      
      {/* 🌟 返回按钮：1:1 复刻学习界面的毛玻璃样式 */}
      <button 
        onClick={() => navigate('/')} 
        className="absolute top-8 left-10 flex items-center gap-2 px-6 py-3 bg-white/60 backdrop-blur-2xl text-indigo-900 rounded-full font-black text-lg hover:bg-white active:scale-[0.96] transition-all cursor-pointer border-2 border-white shadow-sm"
      >
        <ArrowLeft size={20} strokeWidth={3} /> 返回身份选择
      </button>

      {/* 🌟 标题与 IP 情感连贯 */}
      <div className="flex flex-col items-center mb-16 relative z-10">
        <h1 className="text-4xl md:text-5xl font-black text-indigo-950 mb-6 tracking-tight drop-shadow-sm">
          今天想开启什么冒险？
        </h1>
        {/* 悬浮的星空兔小标签 */}
        <div className="flex items-center gap-3 bg-white/60 backdrop-blur-xl px-6 py-2.5 rounded-full border-2 border-white shadow-md animate-[bounce_4s_ease-in-out_infinite]">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-purple-100 to-fuchsia-100 flex items-center justify-center text-2xl shadow-inner border-2 border-white">
            🐰
          </div>
          <span className="text-fuchsia-600 font-black text-base tracking-wide">兔兔陪你学</span>
        </div>
      </div>
      
      {/* 🌟 选择卡片区 (毛玻璃拟态 + 交互动画同步) */}
      <div className="flex gap-10 relative z-10">
        
        {/* 卡片1：温故知新 (常规态) */}
        <button
          onClick={() => navigate('/study?mode=review')}
          className="w-72 h-80 bg-white/60 backdrop-blur-2xl rounded-[2.5rem] shadow-lg border-4 border-white flex flex-col items-center justify-center cursor-pointer transition-all duration-300 hover:-translate-y-2 hover:shadow-xl hover:border-purple-200 active:scale-[0.98] group"
        >
          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 flex items-center justify-center mb-6 shadow-inner border-4 border-white group-hover:scale-110 transition-transform duration-300">
            <RefreshCw size={40} className="text-purple-500" strokeWidth={2.5} />
          </div>
          <h2 className="text-2xl font-black text-indigo-950 mb-3 group-hover:text-purple-600 transition-colors">温故知新</h2>
          <p className="text-gray-500 font-bold text-sm bg-white/50 px-4 py-1.5 rounded-full border border-white shadow-sm">复习昨天学过的知识</p>
        </button>

        {/* 卡片2：探索新世界 (强推荐态) */}
        <button
          onClick={() => navigate('/study?mode=learn')}
          className="relative w-72 h-80 bg-white/70 backdrop-blur-2xl rounded-[2.5rem] shadow-[0_15px_40px_rgba(217,70,239,0.15)] border-4 border-fuchsia-200 flex flex-col items-center justify-center cursor-pointer transition-all duration-300 hover:-translate-y-2 hover:shadow-[0_20px_50px_rgba(217,70,239,0.25)] hover:border-fuchsia-300 active:scale-[0.98] group"
        >
          {/* 🌟 推荐态底层呼吸光晕 (极其微弱的透明外扩闪烁) */}
          <div className="absolute inset-0 rounded-[2.5rem] border-[6px] border-fuchsia-300/30 opacity-50 animate-ping" style={{ animationDuration: '3s' }}></div>
          
          {/* 推荐角标 */}
          <div className="absolute -top-4 right-4 bg-gradient-to-r from-purple-400 to-fuchsia-500 text-white px-4 py-1.5 rounded-full font-black text-xs shadow-md border-2 border-white flex items-center gap-1 z-20">
            <Sparkles size={14} /> 推荐
          </div>

          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-purple-100 to-fuchsia-100 flex items-center justify-center mb-6 shadow-inner border-4 border-white group-hover:scale-110 transition-transform duration-300 relative z-10">
            <Rocket size={40} className="text-fuchsia-500" strokeWidth={2.5} />
          </div>
          <h2 className="text-2xl font-black text-indigo-950 mb-3 group-hover:text-fuchsia-600 transition-colors relative z-10">探索新世界</h2>
          <p className="text-gray-500 font-bold text-sm bg-white/70 px-4 py-1.5 rounded-full border border-white shadow-sm relative z-10">学习家长发送的新卷轴</p>
        </button>

      </div>
    </div>
  );
}