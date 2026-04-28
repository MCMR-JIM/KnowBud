import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [reportStatus, setReportStatus] = useState("暂无报告");
  const [inputValue, setInputValue] = useState("");

  // 生成报告
  const handleGenerateReport = () => {
    setReportStatus("✅ 报告已生成");
  };

  // 推送任务
  const handlePushTask = () => {
    alert("✅ 任务已推送到学生端");
  };

  // 加入复习
  const handleAddToReview = () => {
    alert("✅ 已加入复习队列");
  };

  return (
    <div className="min-h-screen bg-purple-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* 返回大厅 */}
        <div className="bg-white rounded-2xl p-4 shadow mb-6 flex justify-between items-center">
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-2 text-gray-700 hover:text-black"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clipRule="evenodd" />
            </svg>
            <span className="text-lg font-medium">返回大厅</span>
          </button>
          <h1 className="text-xl font-semibold">家长控制台</h1>
          <div></div>
        </div>

        {/* 数据概览 */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-white rounded-2xl p-6 shadow">
            <h3>学习时长</h3>
            <p className="text-xl font-bold">45 分钟</p>
          </div>
          <div className="bg-white rounded-2xl p-6 shadow">
            <h3>掌握程度</h3>
            <p className="text-xl font-bold">78%</p>
          </div>
          <div className="bg-white rounded-2xl p-6 shadow">
            <h3>错题数量</h3>
            <p className="text-xl font-bold">3 题</p>
          </div>
        </div>

        {/* 学习轨迹 */}
        <div className="bg-white rounded-2xl p-6 shadow mb-6">
          <h2 className="text-lg font-bold mb-2">学习轨迹</h2>
          <p>2026-04-28 学习英语单词 × 5</p>
          <p>2026-04-28 完成数学练习 × 2</p>
        </div>

        {/* 错题本 */}
        <div className="bg-white rounded-2xl p-6 shadow mb-6">
          <h2 className="text-lg font-bold mb-2">错题本</h2>
          <div className="p-2 border rounded mb-2">1. 数学：乘法运算</div>
          <div className="p-2 border rounded mb-2">2. 英语：过去式拼写</div>
          <button
            onClick={handleAddToReview}
            className="bg-yellow-400 text-black py-2 px-4 rounded mt-2"
          >
            加入复习队列
          </button>
        </div>

        {/* 家长操作区 */}
        <div className="bg-white rounded-2xl p-6 shadow">
          <h2 className="text-lg font-bold mb-4">家长控制</h2>

          <button
            onClick={handleGenerateReport}
            className="bg-pink-100 py-2 px-4 rounded mr-4 mb-4"
          >
            生成学习报告
          </button>
          <p>{reportStatus}</p>

          <div className="mt-4">
            <input
              type="text"
              placeholder="输入要推送的任务"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              className="border p-2 rounded w-full mb-2"
            />
            <button
              onClick={handlePushTask}
              className="bg-black text-white py-3 px-6 rounded w-full font-bold"
            >
              推送任务到魔法舱
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}