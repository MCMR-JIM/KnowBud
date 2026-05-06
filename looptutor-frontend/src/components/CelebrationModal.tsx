import { useState, useEffect } from 'react';

interface CelebrationModalProps {
  subjectName: string; // 比如：数学、自然科学
  onClose: () => void;
}

export default function CelebrationModal({ subjectName, onClose }: CelebrationModalProps) {
  const [showTree, setShowTree] = useState(false);

  // 模拟撒花 2.5 秒后，浮现知识树网络
  useEffect(() => {
    const timer = setTimeout(() => setShowTree(true), 2500);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-md transition-opacity duration-500 pointer-events-auto">
      
      {/* 阶段 1：撒花动画 (纯 CSS 模拟) */}
      {!showTree && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none overflow-hidden animate-pulse">
          <div className="text-9xl animate-bounce mb-8">🎉🏆✨</div>
          <h2 className="text-4xl font-black text-white text-center drop-shadow-lg">
            太棒啦！卷轴学习完成！
          </h2>
        </div>
      )}

      {/* 阶段 2：知识树网络面板 */}
      <div className={`bg-white/95 backdrop-blur-xl w-[850px] h-[550px] rounded-[3rem] shadow-2xl border-8 border-indigo-100 p-10 flex flex-col transition-all duration-1000 transform ${showTree ? 'translate-y-0 opacity-100 scale-100' : 'translate-y-20 opacity-0 scale-95'}`}>
        
        <h2 className="text-3xl font-black text-indigo-900 text-center mb-12">
          你点亮了【{subjectName}】的新节点！
        </h2>

        {/* 树状网络展示区 */}
        <div className="flex-1 flex items-center justify-center gap-6 relative px-8">
          
          {/* 节点 1：本次点亮 (高亮+发光) */}
          <div className="flex flex-col items-center z-10 relative">
            <div className="w-28 h-28 rounded-full bg-gradient-to-tr from-yellow-300 to-orange-400 shadow-[0_0_40px_rgba(253,224,71,0.8)] border-4 border-white flex items-center justify-center text-5xl transform hover:scale-110 transition-transform cursor-pointer">
              🦖
            </div>
            <span className="mt-4 font-bold text-orange-600 text-xl">恐龙时代</span>
            {/* 节点气泡提示 */}
            <div className="absolute -top-12 bg-yellow-100 text-yellow-800 px-4 py-1.5 rounded-full text-sm font-bold animate-bounce shadow-md">
              本次点亮！
            </div>
          </div>

          {/* 连接线 */}
          <div className="w-24 h-3 bg-gradient-to-r from-orange-400 to-gray-200 rounded-full z-0 shadow-inner"></div>

          {/* 节点 2：待解锁 (灰色) */}
          <div className="flex flex-col items-center z-10 opacity-60 hover:opacity-100 transition-opacity">
            <div className="w-24 h-24 rounded-full bg-gray-100 border-4 border-white shadow-md flex items-center justify-center text-4xl grayscale">
              🌋
            </div>
            <span className="mt-4 font-bold text-gray-500 text-lg">火山爆发</span>
          </div>

          {/* 连接线 */}
          <div className="w-24 h-3 bg-gray-200 rounded-full z-0 shadow-inner"></div>

          {/* 节点 3：待解锁 (灰色) */}
          <div className="flex flex-col items-center z-10 opacity-60 hover:opacity-100 transition-opacity">
            <div className="w-24 h-24 rounded-full bg-gray-100 border-4 border-white shadow-md flex items-center justify-center text-4xl grayscale">
              ☄️
            </div>
            <span className="mt-4 font-bold text-gray-500 text-lg">陨石撞击</span>
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="mt-auto flex justify-center">
          <button 
            onClick={onClose} 
            className="px-10 py-4 bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-full font-black text-xl shadow-[0_10px_20px_rgba(99,102,241,0.3)] hover:shadow-[0_15px_30px_rgba(99,102,241,0.4)] hover:-translate-y-1 active:translate-y-0 transition-all cursor-pointer"
          >
            太酷了，返回大厅！
          </button>
        </div>
      </div>
    </div>
  );
}