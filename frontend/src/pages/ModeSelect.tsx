import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, RefreshCw, Rocket, Sparkles, Repeat } from 'lucide-react';
import Live2DRabbit from '../components/Live2DRabbit';

const ROLE_KEY = 'sprout_role';
type Role = 'rabbit' | 'dinosaur';

function getSavedRole(): Role {
  return (localStorage.getItem(ROLE_KEY) as Role) || 'rabbit';
}
function getRoleEmoji(role: Role) { return role === 'rabbit' ? '🐰' : '🦖'; }
function getRoleLabel(role: Role) { return role === 'rabbit' ? '星空兔' : '小恐龙'; }
function getCompanionText(role: Role) { return role === 'rabbit' ? '兔兔陪你学' : '恐龙陪你学'; }

export default function ModeSelect() {
  const navigate = useNavigate();
  const [role, setRole] = useState<Role>(getSavedRole);

  const toggleRole = () => {
    const next: Role = role === 'rabbit' ? 'dinosaur' : 'rabbit';
    setRole(next);
    localStorage.setItem(ROLE_KEY, next);
  };

  const emoji = getRoleEmoji(role);
  const label = getRoleLabel(role);
  const companion = getCompanionText(role);

  return (
    <div className="w-screen h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-purple-50 to-fuchsia-50 flex flex-col py-6 px-6 md:px-10 gap-6">

      <header className="w-full max-w-[1800px] mx-auto h-20 md:h-24 shrink-0 z-50 flex items-center">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2 px-5 py-2.5 bg-white/70 backdrop-blur-2xl text-indigo-900 rounded-full font-black text-lg hover:bg-white active:scale-[0.96] transition-all cursor-pointer border border-white shadow-sm"
        >
          <ArrowLeft size={20} strokeWidth={3} /> 返回身份选择
        </button>
      </header>

      <main className="flex-1 w-full max-w-[1800px] mx-auto bg-white/40 backdrop-blur-2xl border-[6px] border-purple-300 rounded-[2.5rem] shadow-sm flex flex-col items-center justify-center p-6 xl:p-8 relative overflow-hidden">

        <div className="absolute top-8 left-16 text-6xl opacity-80 animate-[bounce_4s_infinite]">🌸</div>
        <div className="absolute top-12 right-24 text-7xl opacity-80 animate-[pulse_4s_infinite]">🌺</div>
        <div className="absolute bottom-24 left-20 text-7xl opacity-80 animate-[bounce_5s_infinite]">🌷</div>
        <div className="absolute top-1/2 left-8 text-5xl opacity-80">💮</div>
        <div className="absolute top-1/3 right-12 text-6xl opacity-80">🌼</div>

        <div className="flex flex-col items-center mb-16 relative z-10 -mt-10">
          <h1 className="text-5xl md:text-6xl font-black text-indigo-950 mb-6 tracking-widest drop-shadow-sm">
            今天想开启什么冒险？
          </h1>
          <div className="flex items-center gap-3 bg-white/60 backdrop-blur-xl px-6 py-2.5 rounded-full border-2 border-white shadow-md animate-[bounce_4s_ease-in-out_infinite]">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-purple-100 to-fuchsia-100 flex items-center justify-center text-2xl shadow-inner border-2 border-white transition-all duration-300">
              {emoji}
            </div>
            <span className="text-fuchsia-600 font-black text-base tracking-wide">{companion}</span>
          </div>
        </div>

        <div className="flex gap-10 relative z-20">
          <button
            onClick={() => navigate('/study?mode=review')}
            className="w-72 h-80 bg-white/60 backdrop-blur-2xl rounded-[2.5rem] shadow-lg border-4 border-white flex flex-col items-center justify-center cursor-pointer transition-all duration-300 hover:-translate-y-2 hover:shadow-xl hover:border-purple-200 active:scale-[0.98] group"
          >
            <div className="w-24 h-24 rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 flex items-center justify-center mb-6 shadow-inner border-4 border-white group-hover:scale-110 transition-transform duration-300">
              <RefreshCw size={40} className="text-purple-500" strokeWidth={2.5} />
            </div>
            <h2 className="text-2xl font-black text-indigo-950 mb-3 group-hover:text-purple-600 transition-colors">温故知新</h2>
            <p className="text-gray-500 font-bold text-sm bg-white/50 px-4 py-1.5 rounded-full border border-white shadow-sm">
              复习学过的知识
            </p>
          </button>

          <button
            onClick={() => navigate('/study?mode=learn')}
            className="relative w-72 h-80 bg-white/70 backdrop-blur-2xl rounded-[2.5rem] shadow-[0_15px_40px_rgba(217,70,239,0.15)] border-4 border-fuchsia-200 flex flex-col items-center justify-center cursor-pointer transition-all duration-300 hover:-translate-y-2 hover:shadow-[0_20px_50px_rgba(217,70,239,0.25)] hover:border-fuchsia-300 active:scale-[0.98] group"
          >
            <div className="absolute inset-0 rounded-[2.5rem] border-[6px] border-fuchsia-300/30 opacity-50 animate-ping pointer-events-none" style={{ animationDuration: '3s' }}></div>
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

        {/* 🌟 右下角：角色占位 + 切换按钮（垂直布局） */}
        <div className="absolute bottom-0 right-0 z-30 flex flex-col items-center gap-2">
          <div className="w-[350px] h-[350px] xl:w-[450px] xl:h-[450px] flex items-center justify-center group">
            <div className="w-full h-full rounded-full bg-gradient-to-br from-white to-fuchsia-100 border-[10px] border-white shadow-[0_15px_40px_rgba(217,70,239,0.25)] flex flex-col items-center justify-center relative">
              <span className="text-[120px] xl:text-[160px] group-hover:animate-bounce mt-4 transition-all duration-300">{emoji}</span>
              <div className="absolute -bottom-2 bg-fuchsia-100 text-fuchsia-600 px-8 py-3 rounded-full text-lg font-black shadow-lg border-2 border-white whitespace-nowrap transition-all duration-300">
                {label}
              </div>
            </div>
          </div>
          <button
            onClick={toggleRole}
            className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-yellow-200 to-purple-200 text-indigo-900 rounded-full font-black text-sm hover:scale-105 active:scale-95 transition-transform cursor-pointer border-2 border-white shadow-md"
          >
            <Repeat size={16} strokeWidth={2.5} />
            换成{role === 'rabbit' ? '🦖 小恐龙' : '🐰 星空兔'}
          </button>
        </div>

        {/* 🐱 左下角黑猫宠物（hijiki Live2D） */}
        <div className="absolute left-24 bottom-12 z-10 w-[300px] h-[300px]">
          <Live2DRabbit fallbackEmoji={emoji} />
        </div>

      </main>
    </div>
  );
}