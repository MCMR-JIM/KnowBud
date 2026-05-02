import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, Star, Mic, Send, HelpCircle, Loader2, Volume2 } from 'lucide-react';
import { SessionAPI } from '../api/client';

export default function KidsLearning() {
  const navigate = useNavigate();
  const apiBaseUrl = 'http://127.0.0.1:8090/v1';

  type TopicResource = {
    resource_id: string;
    resource_name: string;
    media_type: string;
    resource_url: string;
  };
  
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [todayTopic, setTodayTopic] = useState('恐龙的秘密');
  const [todayTopicId, setTodayTopicId] = useState('');
  const [topicResources, setTopicResources] = useState<TopicResource[]>([]);
  const [previewResource, setPreviewResource] = useState<TopicResource | null>(null);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: `小朋友你好呀！我是你的AI老师，今天我们要探索什么秘密呢？` }
  ]);

  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null); 
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  useEffect(() => {
    const syncTopic = async () => {
      try {
        const queueRes = await fetch(`${apiBaseUrl}/session/review-queue`);
        if (queueRes.ok) {
          const queueData = await queueRes.json();
          const latestItem = queueData.items?.[queueData.items.length - 1];
          if (latestItem?.topic_id) {
            setTodayTopic(latestItem.title || latestItem.topic_id);
            setTodayTopicId(latestItem.topic_id);
            return;
          }
        }

        const stateRes = await fetch(`${apiBaseUrl}/session/state`);
        if (!stateRes.ok) {
          return;
        }

        const stateData = await stateRes.json();
        const currentTopicId = stateData.learning?.current_topic_id || '';
        if (!currentTopicId) {
          return;
        }

        const currentTopic = stateData.topics?.find((topic: any) => topic.topic_id === currentTopicId);
        setTodayTopic(currentTopic?.title || currentTopicId);
        setTodayTopicId(currentTopicId);
      } catch (e) {
      }
    };

    const timer = setInterval(async () => {
      await syncTopic();
    }, 2000);

    void syncTopic();
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchTopicResources = async () => {
      if (!todayTopicId) {
        setTopicResources([]);
        setPreviewResource(null);
        return;
      }

      try {
        const res = await fetch(`${apiBaseUrl}/resource/topics/${todayTopicId}`);
        if (!res.ok) {
          return;
        }

        const data = await res.json();
        const resources = (data.resources || []) as TopicResource[];
        setTopicResources(resources);
        const previewable = resources.find((resource) => ['video', 'image', 'audio'].includes(resource.media_type));
        setPreviewResource(previewable || null);
      } catch (e) {
        setTopicResources([]);
        setPreviewResource(null);
      }
    };

    void fetchTopicResources();
  }, [todayTopicId]);

  const playVoice = (text: string) => {
    if (!text || text.includes('麦克风') || text.includes('按住说话') || text.includes('没听懂')) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 0.85;
    utterance.pitch = 1.1;
    window.speechSynthesis.speak(utterance);
  };

  const resolveResourceUrl = (resourceUrl: string) => {
    if (resourceUrl.startsWith('http://') || resourceUrl.startsWith('https://')) {
      return resourceUrl;
    }
    return `http://127.0.0.1:8090${resourceUrl}`;
  };

  const startRecording = async () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    window.speechSynthesis.cancel(); 

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        setIsLoading(true);
        setMessages(prev => [...prev, { role: 'user', content: '🎤 正在仔细听...' }]);

        try {
          const response = await SessionAPI.sendAudio(audioBlob);
          const { recognized_text, reply_text } = response.data;
          
          setMessages(prev => {
            const newMsgs = [...prev];
            newMsgs[newMsgs.length - 1].content = `🎤 ${recognized_text || '录音好像没声音哦'}`;
            return [...newMsgs, { role: 'assistant', content: reply_text }];
          });
        } catch (error) {
          setMessages(prev => [...prev, { role: 'assistant', content: '哎呀，语音魔法失效了，请再试一次！' }]);
        } finally {
          setIsLoading(false);
        }
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      alert("AI老师需要你的麦克风权限才能听见你说话哦！");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleSendText = async (textToSend: string) => {
    if (!textToSend.trim() || isLoading) return;
    
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    window.speechSynthesis.cancel();

    setMessages(prev => [...prev, { role: 'user', content: textToSend }]);
    setInputText('');
    setIsLoading(true);

    try {
      const res = await SessionAPI.sendTextRealtime(textToSend);
      const streamId = res.data.stream_id;
      
      setMessages(prev => [...prev, { role: 'assistant', content: res.data.reply_text }]);
      
      const audioUrl = `http://127.0.0.1:8090/v1/session/output/audio/stream/${streamId}`;
      const audio = new Audio(audioUrl);
      currentAudioRef.current = audio;
      
      audio.onended = () => { currentAudioRef.current = null; };
      audio.play().catch(e => console.error("音频播放被拦截:", e));

    } catch (error) {
      setMessages(prev => [...prev, { role: 'assistant', content: '哎呀，网络好像断开了！' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 to-pink-50 p-6">
      <div className="bg-white/80 backdrop-blur rounded-2xl p-4 shadow-sm flex justify-between items-center mb-6">
        <button onClick={() => navigate('/')} className="flex items-center gap-2 text-gray-700">
          <ChevronLeft size={22} /> 返回大厅
        </button>
        <div className="flex items-center gap-3 font-bold">
          <Star fill="currentColor" size={18} className="text-yellow-500" />
          <span>45</span>
          <span className="text-2xl ml-1">🤖</span>
        </div>
        <div className="w-20"></div>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        <div className="w-full lg:w-2/3 bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm flex flex-col">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
            🤖 AI辅导老师
          </h2>
          <div className="flex-1 h-[550px] overflow-y-auto space-y-4 mb-4">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className="text-2xl">{msg.role === 'user' ? '👦' : '🤖'}</div>
                <div className="p-4 rounded-xl bg-white shadow-sm border max-w-[85%] relative">
                  {msg.content}
                  {msg.role === 'assistant' && (
                    <button onClick={() => playVoice(msg.content)} className="absolute right-2 top-2 text-gray-400 hover:text-blue-500">
                      <Volume2 size={16} />
                    </button>
                  )}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex gap-3">
                <div>🤖</div>
                <div className="p-3 rounded-xl bg-white shadow-sm flex items-center gap-2">
                  <Loader2 className="animate-spin" size={18} />
                  思考中...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendText(inputText)}
              disabled={isLoading}
              placeholder="输入你的问题..."
              className="flex-1 border rounded-xl px-4 py-3 outline-none focus:border-pink-400"
            />
            <button
              onClick={() => handleSendText(inputText)}
              disabled={isLoading}
              className="p-3 bg-pink-100 text-pink-600 rounded-xl hover:bg-pink-200 disabled:opacity-50"
            >
              <Send size={20} />
            </button>
          </div>
          <div className="flex gap-3 mt-3">
            <button
              onMouseDown={startRecording}
              onMouseUp={stopRecording}
              onMouseLeave={stopRecording}
              disabled={isLoading}
              className={`flex-1 py-4 rounded-xl text-white font-medium flex items-center justify-center gap-2 ${isRecording ? 'bg-red-500' : 'bg-pink-500'}`}
            >
              <Mic size={22} />
              {isRecording ? '聆听中...' : '按住说话'}
            </button>
            <button
              onClick={() => handleSendText("我没听懂，再讲一遍")}
              disabled={isLoading}
              className="w-20 bg-gray-100 rounded-xl flex flex-col items-center justify-center text-xs"
            >
              <HelpCircle size={18} className="text-blue-600" />
              没听懂
            </button>
          </div>
        </div>

        <div className="w-full lg:w-1/3 bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
          <h2 className="text-lg font-bold mb-3">🎦 学习素材</h2>
          <div className="aspect-video bg-gray-100 rounded-xl overflow-hidden flex items-center justify-center mb-3">
            {previewResource?.media_type === 'video' ? (
              <video className="w-full h-full object-contain" controls src={resolveResourceUrl(previewResource.resource_url)} />
            ) : previewResource?.media_type === 'image' ? (
              <img className="w-full h-full object-contain" src={resolveResourceUrl(previewResource.resource_url)} alt="" />
            ) : previewResource?.media_type === 'audio' ? (
              <audio controls src={resolveResourceUrl(previewResource.resource_url)} className="w-4/5" />
            ) : (
              <p className="text-gray-400 text-sm">暂无预览素材</p>
            )}
          </div>
          <div className="max-h-40 overflow-y-auto space-y-2">
            {topicResources.map(r => (
              <div key={r.resource_id} className="p-2 bg-gray-50 rounded-lg flex justify-between items-center">
                <p className="text-sm font-medium truncate max-w-[65%]">{r.resource_name}</p>
                <div className="flex gap-1">
                  {['video','image','audio'].includes(r.media_type) && (
                    <button
                      onClick={() => setPreviewResource(r)}
                      className="text-xs px-2 py-1 bg-sky-100 text-sky-700 rounded-full"
                    >
                      预览
                    </button>
                  )}
                  <a
                    href={resolveResourceUrl(r.resource_url)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs px-2 py-1 bg-pink-100 text-pink-700 rounded-full"
                  >
                    打开
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}