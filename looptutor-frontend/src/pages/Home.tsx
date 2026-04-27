import { Rocket, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function Home() {
  // useNavigate 是路由提供的钩子，用于页面跳转
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-6">
      {/* 头部标题区 */}
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold text-dark mb-4">欢迎来到星梦乐园</h1>
        <p className="text-gray-500 text-lg">请选择你的身份，开启奇妙旅程</p>
      </div>

      {/* 卡片容器 */}
      <div className="flex flex-col md:flex-row gap-8 w-full max-w-4xl">
        
        {/* 1. 儿童端卡片 - 玻璃拟态效果 (backdrop-blur-md) */}
        <div className="flex-1 bg-white/60 backdrop-blur-md rounded-[30px] p-8 text-center shadow-sm border-t-8 border-primary border-b border-b-white/80 transition-transform hover:-translate-y-2 hover:scale-[1.02] duration-300">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-white/90 shadow-md flex items-center justify-center text-primary">
            <Rocket size={40} />
          </div>
          <h2 className="text-2xl font-bold text-dark mb-2">我是小朋友</h2>
          <p className="text-gray-500 mb-8">进入魔法学习舱，看动画闯关</p>
          <button 
            onClick={() => navigate('/kids')}
            className="w-full py-3 px-6 bg-white/90 border-2 border-primary text-primary font-bold rounded-2xl shadow-sm hover:bg-primary hover:text-white transition-all"
          >
            启动学习舱
          </button>
        </div>

        {/* 2. 家长端卡片 */}
        <div className="flex-1 bg-white/60 backdrop-blur-md rounded-[30px] p-8 text-center shadow-sm border-t-8 border-blue border-b border-b-white/80 transition-transform hover:-translate-y-2 hover:scale-[1.02] duration-300">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-white/90 shadow-md flex items-center justify-center text-blue">
            <Users size={40} />
          </div>
          <h2 className="text-2xl font-bold text-dark mb-2">我是家长</h2>
          <p className="text-gray-500 mb-8">查看学习报告，配置课程内容</p>
          <button 
            onClick={() => navigate('/admin')}
            className="w-full py-3 px-6 bg-white/90 border-2 border-blue text-blue font-bold rounded-2xl shadow-sm hover:bg-blue hover:text-white transition-all"
          >
            进入控制台
          </button>
        </div>

      </div>
    </div>
  );
}