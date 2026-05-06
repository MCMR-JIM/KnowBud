import { useNavigate } from 'react-router-dom';

export default function ModeSelect() {
  const navigate = useNavigate();

  return (
    <div className="w-screen h-screen bg-indigo-50 flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold text-indigo-900 mb-12">今天想开启什么冒险？</h1>
      
      <div className="flex gap-8">
        <button 
          onClick={() => navigate('/study?mode=review')}
          className="w-64 h-80 bg-white rounded-3xl shadow-xl hover:shadow-2xl hover:-translate-y-2 transition-all flex flex-col items-center justify-center border-4 border-blue-200 cursor-pointer"
        >
          <div className="text-6xl mb-4">🔄</div>
          <h2 className="text-2xl font-bold text-blue-600">温故知新</h2>
          <p className="text-gray-500 mt-2">复习昨天学过的知识</p>
        </button>

        <button 
          onClick={() => navigate('/study?mode=learn')}
          className="w-64 h-80 bg-white rounded-3xl shadow-xl hover:shadow-2xl hover:-translate-y-2 transition-all flex flex-col items-center justify-center border-4 border-orange-200 cursor-pointer"
        >
          <div className="text-6xl mb-4">🚀</div>
          <h2 className="text-2xl font-bold text-orange-600">探索新世界</h2>
          <p className="text-gray-500 mt-2">学习家长发送的新卷轴</p>
        </button>
      </div>
    </div>
  );
}