import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, BarChart3, Clock, Target, AlertCircle, BrainCircuit, PlusCircle, Loader2, Sparkles } from 'lucide-react';

// 模拟的图表数据
const mockChartData = [
  { name: '周一', score: 65, height: '65%' },
  { name: '周二', score: 85, height: '85%' },
  { name: '周三', score: 70, height: '70%' },
  { name: '周四', score: 90, height: '90%' },
  { name: '周五', score: 80, height: '80%' },
  { name: '周六', score: 95, height: '95%' },
  { name: '周日', score: 100, height: '100%' },
];

export default function AdminDashboard() {
  const navigate = useNavigate();

  // ================= 状态管理 (组件的灵魂) =================
  // 1. AI 报告状态
  const [isGenerating, setIsGenerating] = useState(false);
  const [aiReport, setAiReport] = useState("暂无最新报告，点击右上角按钮生成。");

  // 2. 任务配置状态
  const [newTaskTopic, setNewTaskTopic] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // ================= 交互逻辑 =================
  // 模拟请求后端的 AI 报告接口
  const handleGenerateReport = () => {
    setIsGenerating(true);
    // 模拟网络请求延迟 2 秒
    setTimeout(() => {
      setAiReport("星空兔观察到：本周小朋友在【自然科学】领域表现优异，特别是对“恐龙”相关知识吸收很快。但在“光合作用”等抽象概念上连续回答错误，建议在接下来的任务中增加植物相关的趣味探索。专注力平均时长 18 分钟，属于非常健康的水平！");
      setIsGenerating(false);
    }, 2000);
  };

  // 模拟向后端下发新任务接口
  const handleAddTask = () => {
    if (!newTaskTopic.trim()) return;
    setIsSubmitting(true);
    // 模拟网络请求延迟 1 秒
    setTimeout(() => {
      alert(`✅ 成功向魔法舱下发新任务：【${newTaskTopic}】`);
      setNewTaskTopic('');
      setIsSubmitting(false);
    }, 1000);
  };

  return (
    <div className="min-h-screen p-8 flex flex-col gap-6">
      
      {/* 1. 顶部导航栏 */}
      <div className="bg-white/60 backdrop-blur-md rounded-3xl p-4 px-6 flex justify-between items-center shadow-sm border border-white/50">
        <button 
          onClick={() => navigate('/')}
          className="flex items-center gap-2 text-dark hover:text-blue transition-colors font-bold"
        >
          <ChevronLeft size={24} /> 返回大厅
        </button>
        <h1 className="text-2xl font-bold text-dark flex items-center gap-2">
          <BarChart3 className="text-blue" /> 家长控制台
        </h1>
        <div className="w-24"></div>
      </div>

      {/* 2. 核心数据指标卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white/60 backdrop-blur-md rounded-[20px] p-6 shadow-sm border border-white/50 flex items-center gap-4 border-l-8 border-l-blue">
          <div className="p-4 bg-blue/10 rounded-2xl text-blue"><Clock size={32} /></div>
          <div>
            <p className="text-gray-500 font-bold">本周学习时长</p>
            <p className="text-3xl font-black text-dark">4.2 <span className="text-sm font-normal">小时</span></p>
          </div>
        </div>
        <div className="bg-white/60 backdrop-blur-md rounded-[20px] p-6 shadow-sm border border-white/50 flex items-center gap-4 border-l-8 border-l-primary">
          <div className="p-4 bg-primary/10 rounded-2xl text-primary"><Target size={32} /></div>
          <div>
            <p className="text-gray-500 font-bold">掌握知识点</p>
            <p className="text-3xl font-black text-dark">12 <span className="text-sm font-normal">个</span></p>
          </div>
        </div>
        <div className="bg-white/60 backdrop-blur-md rounded-[20px] p-6 shadow-sm border border-white/50 flex items-center gap-4 border-l-8 border-l-secondary">
          <div className="p-4 bg-secondary/20 rounded-2xl text-yellow-600"><AlertCircle size={32} /></div>
          <div>
            <p className="text-gray-500 font-bold">待攻克错题</p>
            <p className="text-3xl font-black text-dark">3 <span className="text-sm font-normal">题</span></p>
          </div>
        </div>
      </div>

      {/* 3. 业务功能区：左右分栏 */}
      <div className="flex flex-col lg:flex-row gap-6 flex-1">
        
        {/* 左侧：学情图表 & AI报告 */}
        <div className="flex-[2] flex flex-col gap-6">
          {/* AI 学情分析报告 */}
          <div className="bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue via-primary to-secondary"></div>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold text-dark flex items-center gap-2">
                <BrainCircuit className="text-primary" /> AI 综合学情洞察
              </h2>
              <button 
                onClick={handleGenerateReport}
                disabled={isGenerating}
                className="flex items-center gap-2 bg-primary/10 text-primary hover:bg-primary hover:text-white px-4 py-2 rounded-xl font-bold transition-all disabled:opacity-50"
              >
                {isGenerating ? <Loader2 className="animate-spin" size={18} /> : <Sparkles size={18} />}
                {isGenerating ? '大模型分析中...' : '生成最新报告'}
              </button>
            </div>
            <div className="bg-white/50 p-5 rounded-2xl border border-white min-h-[100px] text-gray-700 leading-relaxed shadow-inner">
              {aiReport}
            </div>
          </div>

          {/* 纯 CSS 柱状图 */}
          <div className="flex-1 bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 flex flex-col min-h-[250px]">
            <h2 className="text-lg font-bold text-dark mb-4">近七天专注度趋势</h2>
            <div className="flex-1 w-full flex items-end justify-around pb-2 border-b-2 border-dashed border-gray-300 relative">
              {mockChartData.map((item, index) => (
                <div key={index} className="flex flex-col items-center gap-2 w-10 group cursor-pointer">
                  <span className="opacity-0 group-hover:opacity-100 transition-opacity bg-dark text-white text-xs py-1 px-2 rounded-lg font-bold absolute -top-8">
                    {item.score}
                  </span>
                  <div 
                    className="w-full bg-gradient-to-t from-blue to-blue/40 rounded-t-xl group-hover:from-primary group-hover:to-primary/40 transition-colors shadow-sm"
                    style={{ height: `calc(${item.height} * 1.5)` }}
                  ></div>
                  <span className="text-xs font-bold text-gray-500">{item.name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧：任务配置 & 复习队列 */}
        <div className="flex-[1] flex flex-col gap-6">
          {/* 任务配置面板 */}
          <div className="bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50">
            <h2 className="text-xl font-bold text-dark mb-4 flex items-center gap-2">
              <PlusCircle className="text-blue" /> 派发学习任务
            </h2>
            <div className="flex flex-col gap-3">
              <label className="text-sm font-bold text-gray-500">探索主题</label>
              <input 
                type="text" 
                value={newTaskTopic}
                onChange={(e) => setNewTaskTopic(e.target.value)}
                placeholder="例如：神奇的太阳系..." 
                className="bg-white border-2 border-white focus:border-blue rounded-xl px-4 py-3 outline-none transition-colors shadow-sm"
              />
              <button 
                onClick={handleAddTask}
                disabled={isSubmitting || !newTaskTopic.trim()}
                className="mt-2 w-full flex items-center justify-center gap-2 bg-blue text-white font-bold py-3 rounded-xl shadow-md hover:bg-blue/90 transition-colors disabled:opacity-50"
              >
                {isSubmitting ? <Loader2 className="animate-spin" size={20} /> : '推送至魔法舱'}
              </button>
            </div>
          </div>

          {/* 待攻克错题 */}
          <div className="flex-1 bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 flex flex-col">
            <h2 className="text-lg font-bold text-dark mb-4">急需协助的错题</h2>
            <div className="space-y-4 overflow-y-auto pr-2">
              <div className="bg-white/80 p-4 rounded-2xl border border-white/50 shadow-sm transition-colors hover:border-secondary/50">
                <p className="font-bold text-dark mb-1">恐龙为什么会灭绝？</p>
                <button className="mt-3 w-full py-2 bg-secondary/10 text-yellow-700 font-bold rounded-xl hover:bg-secondary hover:text-white transition-colors">
                  设为下次优先探索
                </button>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}