import { useState, useEffect } from 'react';
import { Rocket, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { SessionAPI } from '../api/client';
import LanguageSwitcher from '../i18n/LanguageSwitcher';

const FALLBACK_WORDS = ['拼音', '算术', 'ABC', '科学', '古诗', '美术'];

const BALLOON_COLORS = [
  'bg-gradient-to-br from-pink-300 to-rose-400',
  'bg-gradient-to-br from-purple-300 to-fuchsia-400',
  'bg-gradient-to-br from-yellow-300 to-orange-400',
  'bg-gradient-to-br from-green-300 to-emerald-400',
  'bg-gradient-to-br from-blue-300 to-cyan-400',
  'bg-gradient-to-br from-indigo-300 to-violet-400',
];

const BALLOON_POSITIONS = [
  { x: 'left-[6%]',  y: 'top-[14%]', delay: '0s' },
  { x: 'right-[8%]', y: 'top-[18%]', delay: '1.2s' },
  { x: 'left-[12%]', y: 'bottom-[30%]', delay: '2.4s' },
  { x: 'right-[6%]', y: 'bottom-[26%]', delay: '0.8s' },
  { x: 'left-[50%]',  y: 'top-[8%]',  delay: '1.8s' },
  { x: 'right-[22%]', y: 'top-[6%]',  delay: '3s' },
];

// 精简装饰：只在屏幕上半区保留少量
const decorEmojis = [
  { emoji: '🌸', x: 'left-[3%]', y: 'top-[5%]', size: 'text-4xl' },
  { emoji: '🍃', x: 'right-[4%]', y: 'top-[8%]', size: 'text-3xl' },
  { emoji: '💮', x: 'left-[18%]', y: 'top-[3%]', size: 'text-3xl' },
  { emoji: '🌼', x: 'right-[16%]', y: 'top-[4%]', size: 'text-3xl' },
];

function pickRandom(arr: string[], count: number): string[] {
  const shuffled = [...arr].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, Math.min(count, shuffled.length));
}

export default function Home() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [words, setWords] = useState<string[]>(FALLBACK_WORDS);

  useEffect(() => {
    SessionAPI.getKnowledgeGraph()
      .then(res => {
        const topics: { title: string }[] = res.data?.topics || [];
        const titles = topics
          .map((t: { title: string }) => t.title)
          .filter((t: string) => t && t.length <= 4);
        if (titles.length >= 3) {
          setWords(pickRandom(titles, 6));
        }
      })
      .catch(() => {}); // 静默回退到静态数组
  }, []);

  const displayWords = words.length >= 3 ? pickRandom(words, 6) : FALLBACK_WORDS;

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-purple-50 to-fuchsia-50 flex items-center justify-center">
      <style>{`
        @keyframes float-balloon {
          0%, 100% { transform: translateY(0px) rotate(0deg); }
          25%  { transform: translateY(-16px) rotate(-2deg); }
          50%  { transform: translateY(-6px) rotate(1deg); }
          75%  { transform: translateY(-22px) rotate(-1deg); }
        }
        @keyframes float-emoji {
          0%, 100% { transform: translateY(0px); }
          50%  { transform: translateY(-10px); }
        }
      `}</style>

      {/* ── 知识盲盒气泡（动态数据 + hover 显字） ── */}
      {displayWords.slice(0, 6).map((word, i) => (
        <div
          key={i}
          className={`absolute ${BALLOON_POSITIONS[i].x} ${BALLOON_POSITIONS[i].y} z-0 group`}
          style={{ animation: `float-balloon 7s ease-in-out ${BALLOON_POSITIONS[i].delay} infinite` }}
        >
          <div className={`w-20 h-20 rounded-full ${BALLOON_COLORS[i]} shadow-lg border-2 border-white/70 flex items-center justify-center cursor-default`}>
            <span className="font-black text-sm text-white opacity-0 group-hover:opacity-100 transition-all duration-300 drop-shadow">
              {word}
            </span>
          </div>
        </div>
      ))}

      {/* ── 精简装饰：仅上半区 ── */}
      {decorEmojis.map((d, i) => (
        <div
          key={`decor-${i}`}
          className={`absolute ${d.x} ${d.y} ${d.size} opacity-60 select-none pointer-events-none z-0`}
          style={{ animation: `float-emoji ${4 + i * 0.7}s ease-in-out ${i * 0.5}s infinite` }}
        >
          {d.emoji}
        </div>
      ))}

      {/* ── 左下角 星空兔（放大 3x，bottom 0 确保不被裁切） ── */}
      <div className="absolute bottom-0 left-4 z-20 text-[12rem] leading-none animate-pulse hover:scale-110 transition-transform cursor-default select-none">
        🐰
      </div>

      {/* ── 右下角 小恐龙（放大 3x，bottom 0 确保不被裁切） ── */}
      <div className="absolute bottom-0 right-4 z-20 text-[12rem] leading-none animate-pulse hover:scale-110 transition-transform cursor-default select-none" style={{ animationDelay: '1.5s' }}>
        🦖
      </div>

      {/* ── 主卡片 ── */}
      <div className="relative z-10 border-[6px] border-purple-200/70 rounded-[2.5rem] bg-white/50 backdrop-blur-xl p-12 flex flex-col items-center w-[92vw] max-w-5xl shadow-2xl ring-4 ring-purple-100/40">

        <div className="absolute -top-3 right-4 z-20">
          <LanguageSwitcher />
        </div>

        <span className="absolute -top-5 -left-5 text-3xl select-none">✨</span>
        <span className="absolute -top-5 -right-5 text-3xl select-none">✨</span>
        <span className="absolute -bottom-5 -left-5 text-3xl select-none">✨</span>
        <span className="absolute -bottom-5 -right-5 text-3xl select-none">✨</span>

        <div className="text-center mb-12">
          <h1 className="text-5xl md:text-6xl font-sans font-black tracking-widest mb-4 text-transparent bg-clip-text bg-gradient-to-r from-purple-500 via-fuchsia-500 to-pink-500">
            🌟 {t('home.title')} 🎈
          </h1>
          <p className="text-gray-500 text-lg font-bold">{t('home.subtitle')}</p>
        </div>

        <div className="flex flex-col md:flex-row gap-8 justify-center relative">
          <div className="w-80 bg-white/60 backdrop-blur-md rounded-[30px] p-8 text-center shadow-lg border-t-8 border-primary border-b border-b-white/80 transition-transform hover:-translate-y-2 hover:scale-[1.02] hover:shadow-xl duration-300 relative">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-white/90 shadow-md flex items-center justify-center text-primary">
              <Rocket size={40} />
            </div>
            <h2 className="text-2xl font-bold text-dark mb-2">{t('home.kid')}</h2>
            <p className="text-gray-500 mb-8">{t('home.kidDesc')}</p>
            <button
              onClick={() => navigate('/select')}
              className="w-full py-3 px-6 bg-white/90 border-2 border-primary text-primary font-bold rounded-2xl shadow-sm hover:bg-primary hover:text-white transition-all"
            >
              {t('home.kidBtn')}
            </button>
          </div>

          <div className="w-80 bg-white/60 backdrop-blur-md rounded-[30px] p-8 text-center shadow-lg border-t-8 border-blue border-b border-b-white/80 transition-transform hover:-translate-y-2 hover:scale-[1.02] hover:shadow-xl duration-300 relative">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-white/90 shadow-md flex items-center justify-center text-blue">
              <Users size={40} />
            </div>
            <h2 className="text-2xl font-bold text-dark mb-2">{t('home.parent')}</h2>
            <p className="text-gray-500 mb-8">{t('home.parentDesc')}</p>
            <button
              onClick={() => navigate('/admin')}
              className="w-full py-3 px-6 bg-white/90 border-2 border-blue text-blue font-bold rounded-2xl shadow-sm hover:bg-blue hover:text-white transition-all"
            >
              {t('home.parentBtn')}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}