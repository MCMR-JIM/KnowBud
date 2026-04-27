import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, Star, Mic, Send, HelpCircle, Loader2, Volume2 } from 'lucide-react';
import { SessionAPI } from '../api/client';

const COMPANIONS: Record<string, string> = {
  "星空兔": "🐰",
  "小智龙": "🦖"
};

export default function KidsLearning() {
  const navigate = useNavigate();
  
  const [companion, setCompanion] = useState("星空兔");
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: `小朋友你好呀！我是你的${companion}，今天我们要探索什么秘密呢？` }
  ]);

  // ================= 🪄 魔法功能：悬停语音点读 =================
  const handleHoverRead = (text: string) => {
    // 1. 先打断当前正在播放的声音（防止连续快速滑动导致多声音重叠）
    window.speechSynthesis.cancel();
    
    // 2. 创建新的发音任务
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN'; // 设定为中文
    utterance.rate = 0.85;    // 语速稍微调慢，适合儿童 (默认是 1)
    utterance.pitch = 1.1;    // 音调稍微调高，显得更亲切可爱
    
    // 3. 播放声音
    window.speechSynthesis.speak(utterance);
  };

  // ================= 聊天发送逻辑 =================
  const handleSend = async (textToSend: string) => {
    if (!textToSend.trim() || isLoading) return;

    setMessages(prev => [...prev, { role: 'user', content: textToSend }]);
    setInputText('');
    setIsLoading(true);

    try {
      const response = await SessionAPI.sendText(textToSend);
      setMessages(prev => [...prev, { role: 'assistant', content: response.data.reply_text }]);
      // 收到后端回复后，自动朗读出来！
      handleHoverRead(response.data.reply_text); 
    } catch (error) {
      console.error("请求后端失败:", error);
      setMessages(prev => [...prev, { role: 'assistant', content: '哎呀，魔法网络好像断开了！' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col min-h-screen p-6 gap-6">
      
      {/* 1. 顶部状态栏 */}
      <div className="bg-white/60 backdrop-blur-md rounded-3xl p-4 px-6 flex justify-between items-center shadow-sm border border-white/50">
        <button 
          onClick={() => navigate('/')}
          className="flex items-center gap-2 text-dark hover:text-primary transition-colors font-bold"
        >
          <ChevronLeft size={24} /> 返回大厅
        </button>

        <div className="flex flex-col items-center">
          <div className="flex items-center gap-4 text-xl font-bold text-dark">
            <span className="flex items-center gap-1 text-secondary"><Star fill="currentColor" /> 45</span>
            <span className="text-gray-300">|</span>
            <div className="flex items-center gap-2">
              <span>伙伴:</span>
              <select 
                value={companion}
                onChange={(e) => setCompanion(e.target.value)}
                className="bg-transparent text-2xl cursor-pointer outline-none hover:scale-110 transition-transform appearance-none text-center"
              >
                {Object.keys(COMPANIONS).map(name => (
                  <option key={name} value={name}>{COMPANIONS[name]}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="w-48 h-3 bg-white/80 rounded-full mt-2 overflow-hidden border border-white">
            <div className="h-full bg-gradient-to-r from-secondary to-primary w-1/3 rounded-full transition-all duration-500"></div>
          </div>
        </div>
        <div className="w-24"></div>
      </div>

      {/* 2. 核心内容区 */}
      <div className="flex flex-1 gap-6 h-[calc(100vh-140px)]">
        
        {/* 左侧：视频教学区 */}
        <div className="flex-[6] bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 flex flex-col">
          {/* 给标题也加上悬停朗读 */}
          <h3 
            onMouseEnter={() => handleHoverRead("今日探索：恐龙的秘密")}
            className="text-2xl font-bold text-blue mb-4 cursor-help hover:text-primary transition-colors flex items-center gap-2 w-fit"
            title="鼠标放上来听我说"
          >
            今日探索：恐龙的秘密 <Volume2 size={20} className="opacity-50" />
          </h3>
          <div className="w-full flex-1 bg-black/5 rounded-2xl overflow-hidden flex items-center justify-center border-2 border-white/80">
            <video className="w-full h-full object-cover" controls src="https://www.w3schools.com/html/mov_bbb.mp4" />
          </div>
        </div>

        {/* 右侧：聊天互动区 */}
        <div className="flex-[4] bg-white/40 backdrop-blur-md rounded-[30px] p-5 shadow-sm border border-white/50 flex flex-col">
          <h3 className="text-xl font-bold text-primary mb-4 flex items-center gap-2">
            <span className="bg-primary/20 p-2 rounded-xl">{COMPANIONS[companion]}</span> 伙伴连线
          </h3>
          
          {/* 聊天气泡滚动区 */}
          <div className="flex-1 overflow-y-auto pr-2 space-y-4 mb-4 scrollbar-hide">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className="text-2xl">{msg.role === 'user' ? '👦' : COMPANIONS[companion]}</div>
                {/* 🌟 核心：给气泡加上 onMouseEnter 事件和 hover 高亮效果 */}
                <div 
                  onMouseEnter={() => handleHoverRead(msg.content)}
                  className={`p-4 rounded-2xl max-w-[80%] shadow-sm cursor-help transition-all duration-300 relative group ${
                    msg.role === 'user' 
                      ? 'bg-blue/10 text-dark rounded-tr-sm border border-blue/20 hover:bg-blue/20' 
                      : 'bg-white text-dark rounded-tl-sm border border-white/80 hover:bg-yellow-50 hover:border-yellow-200'
                  }`}
                  title="鼠标放上来听我说"
                >
                  {/* 悬停时显示的小喇叭图标 */}
                  <Volume2 size={16} className="absolute -top-2 -right-2 text-primary opacity-0 group-hover:opacity-100 transition-opacity bg-white rounded-full p-0.5 shadow-sm" />
                  {msg.content}
                </div>
              </div>
            ))}
            
            {isLoading && (
              <div className="flex gap-3 flex-row">
                <div className="text-2xl">{COMPANIONS[companion]}</div>
                <div className="p-4 rounded-2xl bg-white text-dark rounded-tl-sm border border-white/80 flex items-center gap-2">
                  <Loader2 className="animate-spin text-primary" size={20} />
                  <span className="text-sm text-gray-500">正在思考中...</span>
                </div>
              </div>
            )}
          </div>

          {/* 底部输入区 */}
          <div className="flex flex-col gap-3 mt-auto">
            <div className="flex gap-2">
              <input 
                type="text" 
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend(inputText)}
                disabled={isLoading}
                placeholder="或者打字告诉我..." 
                className="flex-1 bg-white/80 border-2 border-white rounded-2xl px-4 py-3 focus:outline-none focus:border-primary transition-colors shadow-sm disabled:opacity-50"
              />
              <button 
                onClick={() => handleSend(inputText)}
                disabled={isLoading}
                className="bg-white/80 text-primary border-2 border-white hover:border-primary hover:bg-primary hover:text-white p-3 rounded-2xl transition-all shadow-sm disabled:opacity-50"
              >
                <Send size={20} />
              </button>
            </div>
            
            <div className="flex gap-3">
              <button className="flex-[3] bg-primary text-white font-bold py-4 rounded-2xl shadow-md hover:bg-primary/90 transition-colors flex items-center justify-center gap-2 text-lg active:scale-95">
                <Mic size={24} /> 按住说话
              </button>
              <button 
                onClick={() => handleSend("我没听懂，能用更简单的话再给我讲一遍吗？")}
                disabled={isLoading}
                className="flex-[1] bg-white/80 text-dark font-bold py-4 rounded-2xl shadow-sm border-2 border-white hover:border-gray-200 transition-colors flex items-center justify-center flex-col text-xs gap-1 disabled:opacity-50"
              >
                <HelpCircle size={18} className="text-blue" />
                没听懂
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}