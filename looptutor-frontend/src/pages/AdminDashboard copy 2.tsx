import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [reportStatus, setReportStatus] = useState("暂无最新报告，点击右上角按钮生成。");
  const [inputValue, setInputValue] = useState("");

  const handleGenerateReport = () => {
    setReportStatus("✅ 报告已生成！");
  };

  const handlePushTask = () => {
    alert("✅ 任务已推送至魔法舱！");
  };

  const handleSetPriority = () => {
    alert("✅ 已设为下次优先探索！");
  };

  return (
    <div className="min-h-screen bg-purple-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* ✅ 和儿童端完全一样的返回大厅按钮样式 */}
        <div className="bg-white/80 rounded-2xl p-4 mb-6 flex justify-between items-center shadow-sm">
          <button 
            onClick={() => navigate('/')} 
            className="flex items-center gap-2 text-gray-700 hover:text-gray-900 transition-colors"
          >
            {/* 儿童端的箭头图标 */}
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clipRule="evenodd" />
            </svg>
            <span className="text-lg font-medium">返回大厅</span>
          </button>
          <h1 className="text-lg font-semibold">家长控制台</h1>
          <div></div>
        </div>

        {/* 数据卡片 */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-white rounded-2xl p-5 shadow-sm border-l-4 border-blue-400">
            <div className="text-gray-500 text-sm">本周学习时长</div>
            <div className="text-2xl font-bold mt-2">4.2 小时</div>
          </div>
          <div className="bg-white rounded-2xl p-5 shadow-sm border-l-4 border-pink-400">
            <div className="text-gray-500 text-sm">掌握知识点</div>
            <div className="text-2xl font-bold mt-2">12 个</div>
          </div>
          <div className="bg-white rounded-2xl p-5 shadow-sm border-l-4 border-yellow-400">
            <div className="text-gray-500 text-sm">待攻克错题</div>
            <div className="text-2xl font-bold mt-2">3 题</div>
          </div>
        </div>

        {/* 内容区 */}
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2 space-y-4">
            <div className="bg-white rounded-2xl p-5 shadow-sm">
              <div className="flex justify-between items-center mb-3">
                <h3 className="font-medium">AI 综合学情洞察</h3>
                <button
                  onClick={handleGenerateReport}
                  className="px-3 py-1 bg-pink-100 text-pink-600 text-sm rounded-lg"
                >
                  生成最新报告
                </button>
              </div>
              <div className="bg-gray-50 rounded-lg p-3 text-gray-400 text-sm">
                {reportStatus}
              </div>
            </div>

            <div className="bg-white rounded-2xl p-5 shadow-sm">
              <h3 className="font-medium mb-4">近七天专注趋势</h3>
              <div className="h-40 flex items-end justify-around">
                <div className="flex flex-col items-center">
                  <div className="w-8 bg-blue-400 rounded-t" style={{height:'40px'}}></div>
                  <span className="text-xs mt-2 text-gray-500">周一</span>
                </div>
                <div className="flex flex-col items-center">
                  <div className="w-8 bg-blue-400 rounded-t" style={{height:'70px'}}></div>
                  <span className="text-xs mt-2 text-gray-500">周二</span>
                </div>
                <div className="flex flex-col items-center">
                  <div className="w-8 bg-blue-400 rounded-t" style={{height:'50px'}}></div>
                  <span className="text-xs mt-2 text-gray-500">周三</span>
                </div>
                <div className="flex flex-col items-center">
                  <div className="w-8 bg-blue-400 rounded-t" style={{height:'90px'}}></div>
                  <span className="text-xs mt-2 text-gray-500">周四</span>
                </div>
                <div className="flex flex-col items-center">
                  <div className="w-8 bg-blue-400 rounded-t" style={{height:'80px'}}></div>
                  <span className="text-xs mt-2 text-gray-500">周五</span>
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="bg-white rounded-2xl p-5 shadow-sm">
              <h3 className="font-medium mb-3">派发学习任务</h3>
              <div className="mb-3">
                <label className="text-xs text-gray-500 mb-1 block">探索主题</label>
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder="例如：神奇的太阳系..."
                  className="w-full border border-gray-200 rounded-lg p-2 text-sm"
                />
              </div>
              {/* 黑色推送按钮 */}
              <button
                onClick={handlePushTask}
                className="w-full py-3 bg-black text-white font-bold rounded-lg"
              >
                推送至魔法舱
              </button>
            </div>

            <div className="bg-white rounded-2xl p-5 shadow-sm">
              <h3 className="font-medium mb-3">急需协助的错题</h3>
              <div className="bg-gray-50 rounded-lg p-3 mb-3 text-sm">
                恐龙为什么会灭绝？
              </div>

              {/* ✅ 已改为好看的黄色，不是黑色！ */}
              <button
                onClick={handleSetPriority}
                className="w-full py-3 bg-yellow-400 text-black font-bold rounded-lg"
              >
                设为下次优先探索
              </button>

            </div>
          </div>
        </div>
      </div>
    </div>
  );
}