import { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, BookOpen, Search, Smile, Mic, Send, Zap, Loader2, Volume2, Check, MessageCircle, Camera } from 'lucide-react';
import PdfViewer from '../components/PdfViewer';
import CelebrationModal from '../components/CelebrationModal';
import { SessionAPI, apiClient } from '../api/client';
import { useAppDialog } from '../components/AppDialog';

// ================= 模块一：数据卡片 =================
const UserStatsCard = ({ totalScore = 0 }) => (
  <div className="w-full flex flex-col items-center justify-center gap-3 bg-white/60 backdrop-blur-xl p-6 rounded-[2.5rem] shadow-lg border-2 border-white pointer-events-auto hover:-translate-y-1 transition-all cursor-pointer">
    <div className="flex items-center gap-2">
      <Zap size={32} className="text-fuchsia-400 fill-fuchsia-400 animate-pulse shrink-0" />
      <span className="text-indigo-950 font-black text-3xl tracking-tight">{totalScore} 能量</span>
    </div>
    <div className="bg-white/60 px-4 py-1.5 rounded-full border border-white shadow-sm mt-1">
      <span className="text-gray-600 text-sm font-bold">坚持学习，继续加油！</span>
    </div>
  </div>
);

// ================= 模块二：知识星图 =================
const InlineKnowledgeMap = ({ nodes, onSelectNode }: { nodes: any[], onSelectNode: (id: string) => void }) => (
  <div className="w-full flex-1 min-h-0 flex flex-col bg-white/60 backdrop-blur-xl p-5 rounded-[2rem] shadow-lg border-2 border-white pointer-events-auto overflow-hidden">
    <div className="bg-purple-100 text-purple-800 px-4 py-1.5 rounded-full font-black text-xs mb-4 flex items-center justify-center gap-2 border border-purple-200 shrink-0 mx-auto w-fit">
      🗺️ 探索星图
    </div>
    <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
      {nodes.length === 0 ? (
        <div className="text-center text-gray-400 text-sm mt-10">这里暂时没有任务哦</div>
      ) : (
        <div className="flex flex-col items-start relative w-full pl-4 py-2">
          <div className="absolute left-[31px] top-4 bottom-4 w-1 bg-gray-200/60 rounded-full z-0" />
          {nodes.map((node) => {
            const isCompleted = node.status === 'completed';
            const isCurrent = node.status === 'current';

            return (
              <div key={node.id} onClick={() => onSelectNode(node.id)} className="flex flex-row items-center w-full mb-5 relative z-10 cursor-pointer hover:opacity-75 transition-all hover:translate-x-1">
                <div className={`w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-sm border-2 transition-all duration-300 ${isCompleted ? 'bg-indigo-100 border-indigo-300 text-indigo-600 shadow-sm' : isCurrent ? 'bg-gradient-to-tr from-purple-400 to-fuchsia-400 border-white text-white shadow-md animate-pulse' : 'bg-gray-100 border-gray-200 text-gray-400 grayscale opacity-60'}`}>
                  {isCompleted ? <Check size={16} strokeWidth={4} /> : (isCurrent ? '📍' : '🔒')}
                </div>
                <div className="ml-4 flex flex-col">
                  <span className={`font-bold text-sm ${isCompleted ? 'text-indigo-600' : isCurrent ? 'text-fuchsia-600' : 'text-gray-400'}`}>{node.title}</span>
                  {isCurrent && <span className="text-[10px] text-fuchsia-500 font-black mt-0.5">当前位置</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  </div>
);

// ================= 模块三：右侧对话卡片 =================
const InteractionCard = ({ state, onSend, isLoading, isRecording, onStartRecord, onStopRecord, onPlayVoice }: any) => {
  const [inputText, setInputText] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => { setIsPlaying(false); }, [state.message]);
  const handleSendClick = () => { if (inputText.trim() && !isLoading) { onSend(inputText); setInputText(''); } };

  return (
    <div className="w-full flex-1 min-h-0 bg-white/70 backdrop-blur-2xl rounded-[2.5rem] shadow-lg border-2 border-white flex flex-col pointer-events-auto overflow-hidden">
      <div className="p-5 border-b-2 border-white/50 flex items-center justify-between bg-gradient-to-r from-purple-50/50 to-fuchsia-50/50">
        <div className="flex items-center gap-2 pl-2">
          <MessageCircle className="text-purple-500" size={24} />
          <span className="font-black text-indigo-950 text-xl tracking-tight">星空兔伴学</span>
        </div>
      </div>
      <div className="flex-1 p-6 overflow-y-auto custom-scrollbar flex flex-col">
        {state.type === 'none' && !isLoading && (
          <div className="m-auto text-gray-400 text-sm text-center">你可以随时按住麦克风和我聊天，或者翻开资料哦！</div>
        )}
        {state.type !== 'none' && (
          <div className={`relative p-6 rounded-3xl rounded-tl-none border-2 mb-6 shadow-sm bg-fuchsia-50 border-fuchsia-200`}>
            <div className="absolute top-0 -left-3 w-0 h-0 border-t-[12px] border-t-fuchsia-50 border-l-[12px] border-l-transparent"></div>
            <div className="flex justify-between items-start gap-4">
              <p className="text-xl leading-[1.6] font-bold flex-1 text-fuchsia-600 whitespace-pre-wrap">{state.message}</p>
              <button onClick={() => { setIsPlaying(!isPlaying); if (!isPlaying && state.message) onPlayVoice(state.message); else window.speechSynthesis.cancel(); }} className={`shrink-0 w-12 h-12 rounded-full flex items-center justify-center cursor-pointer transition-all shadow-sm ${isPlaying ? 'bg-purple-500 text-white animate-pulse' : 'bg-white text-purple-500 hover:bg-purple-50 border-2 border-purple-100'}`}>
                {isPlaying ? <Loader2 className="animate-spin" size={24} /> : <Volume2 size={24} strokeWidth={2.5} />}
              </button>
            </div>
          </div>
        )}
        {isLoading && (
           <div className="flex items-center gap-3 text-purple-500 font-bold mb-4 ml-2 bg-purple-50 w-fit px-4 py-2 rounded-full shadow-sm">
             <Loader2 className="animate-spin" size={20} /> 星空兔思考中...
           </div>
        )}
      </div>
      <div className="p-6 bg-white/50 backdrop-blur-md border-t-2 border-white flex flex-col gap-4">
        <div className="flex items-center gap-3 bg-white/80 rounded-2xl px-5 py-4 border-2 border-purple-50 focus-within:border-purple-300 transition-colors">
          <Smile size={28} className="text-purple-300 cursor-pointer hover:text-purple-500" />
          <input type="text" value={inputText} onChange={(e) => setInputText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleSendClick(); } }} disabled={isLoading} placeholder="打字告诉兔兔..." className="flex-1 min-w-0 bg-transparent text-lg outline-none text-indigo-900 font-medium disabled:opacity-50" />
          <Send onClick={handleSendClick} size={28} className={`shrink-0 cursor-pointer transition-colors hover:scale-110 ${inputText && !isLoading ? 'text-purple-500' : 'text-purple-200'}`} />
        </div>
        <button onMouseDown={onStartRecord} onMouseUp={onStopRecord} onMouseLeave={onStopRecord} disabled={isLoading} className={`w-full py-5 text-white rounded-2xl font-black text-xl transition-all flex items-center justify-center gap-3 cursor-pointer relative overflow-hidden disabled:opacity-50 ${isRecording ? 'bg-fuchsia-400 shadow-[0_0_25px_rgba(232,121,249,0.6)]' : 'bg-gradient-to-r from-purple-400 to-fuchsia-500 shadow-lg hover:shadow-xl'}`}>
          <Mic size={26} className={isRecording ? "animate-bounce" : ""} /> {isRecording ? '正在仔细听...' : '按住说话'}
        </button>
      </div>
    </div>
  );
};

// ================= 模块四：儿童信息弹窗 (支持真实图片上传) =================
const ProfileModal = ({ profile, onSave, onClose }: any) => {
  const [formData, setFormData] = useState(profile);
  const avatars = ['🐰', '👦', '👧', '🦖', '🐼'];

  // 🌟 图片上传处理逻辑
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setFormData({ ...formData, avatar: reader.result as string }); // 保存为 base64
      };
      reader.readAsDataURL(file);
    }
  };

  const isCustomImage = formData.avatar.startsWith('data:image');

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-indigo-950/40 backdrop-blur-sm transition-all">
      <div className="bg-white/90 backdrop-blur-2xl rounded-[2.5rem] p-8 shadow-2xl flex flex-col w-full max-w-sm mx-4 relative border-4 border-white animate-[bounce_0.5s_ease-out_1]">
        <h2 className="text-2xl font-black text-indigo-950 mb-6 text-center">我的名片</h2>

        {/* 🌟 升级版头像选择区 */}
        <div className="flex flex-col items-center mb-6">
          <label className="cursor-pointer relative group flex flex-col items-center">
            <input type="file" accept="image/*" className="hidden" onChange={handleImageUpload} />
            <div className="w-24 h-24 rounded-full border-4 border-purple-200 flex items-center justify-center bg-gray-50 text-5xl overflow-hidden group-hover:border-purple-400 transition-colors shadow-sm relative z-10">
              {isCustomImage ? (
                <img src={formData.avatar} alt="avatar" className="w-full h-full object-cover" />
              ) : (
                formData.avatar
              )}
            </div>
            <div className="absolute bottom-6 right-0 bg-fuchsia-500 text-white p-2 rounded-full shadow-md z-20 group-hover:scale-110 transition-transform">
               <Camera size={16} />
            </div>
            <span className="text-xs text-gray-400 mt-3 font-bold group-hover:text-purple-500">点击上传专属照片</span>
          </label>
        </div>

        <div className="flex flex-wrap gap-2 justify-center mb-6">
          {avatars.map(a => (
            <button key={a} onClick={() => setFormData({ ...formData, avatar: a })} className={`text-2xl w-10 h-10 rounded-full flex items-center justify-center transition-all cursor-pointer ${formData.avatar === a ? 'bg-purple-100 border-2 border-purple-400 scale-110 shadow-md' : 'bg-gray-50 border border-gray-200 grayscale opacity-60 hover:grayscale-0 hover:opacity-100'}`}>
              {a}
            </button>
          ))}
        </div>

        {/* 资料表单 */}
        <div className="space-y-4 mb-8">
          <div>
            <label className="block text-sm font-bold text-gray-600 mb-1 ml-1">名字</label>
            <input type="text" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} className="w-full bg-white/80 border-2 border-purple-100 rounded-xl px-4 py-2 outline-none focus:border-purple-400 font-bold text-indigo-900 transition-colors" />
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-sm font-bold text-gray-600 mb-1 ml-1">年龄</label>
              <input type="number" value={formData.age} onChange={e => setFormData({ ...formData, age: e.target.value })} className="w-full bg-white/80 border-2 border-purple-100 rounded-xl px-4 py-2 outline-none focus:border-purple-400 font-bold text-indigo-900 transition-colors" />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-bold text-gray-600 mb-1 ml-1">性别</label>
              <select value={formData.gender} onChange={e => setFormData({ ...formData, gender: e.target.value })} className="w-full bg-white/80 border-2 border-purple-100 rounded-xl px-4 py-2 outline-none focus:border-purple-400 font-bold text-indigo-900 transition-colors appearance-none cursor-pointer">
                <option value="boy">男生</option>
                <option value="girl">女生</option>
                <option value="secret">保密</option>
              </select>
            </div>
          </div>
        </div>

        <div className="flex gap-4">
          <button onClick={onClose} className="flex-1 py-3 bg-gray-100 text-gray-600 font-bold rounded-2xl hover:bg-gray-200 transition-colors cursor-pointer">取消</button>
          <button onClick={() => { onSave(formData); onClose(); }} className="flex-[2] py-3 bg-gradient-to-r from-purple-500 to-fuchsia-500 text-white font-bold rounded-2xl hover:scale-105 active:scale-95 transition-all shadow-md cursor-pointer">保存修改</button>
        </div>
      </div>
    </div>
  );
};


// ================= 主容器 =================
export default function StudyRoom() {
  const navigate = useNavigate();
  const location = useLocation();
  const appDialog = useAppDialog();

  // 🌟 核心：解析 URL 中的 mode 参数
  const searchParams = new URLSearchParams(location.search);
  const playMode = searchParams.get('mode') || 'learn'; // 'learn' 或 'review'

  const [userProfile, setUserProfile] = useState(() => {
    const saved = localStorage.getItem('looptutor_profile');
    return saved ? JSON.parse(saved) : { name: '小勇士', age: 7, gender: 'boy', avatar: '🐰' };
  });
  const [showProfileModal, setShowProfileModal] = useState(false);

  const [subjects, setSubjects] = useState<any[]>([]);
  const [activeSubjectId, setActiveSubjectId] = useState<string>('');
  const [allTopics, setAllTopics] = useState<any[]>([]);
  const [treeNodes, setTreeNodes] = useState<any[]>([]);
  const [reviewQueueTopics, setReviewQueueTopics] = useState<string[]>([]); // 🌟 存储复习队列 ID
  
  const [currentTopicId, setCurrentTopicId] = useState('');
  const [pdfResourceUrl, setPdfResourceUrl] = useState<string | null>(null);
  const [currentResourceName, setCurrentResourceName] = useState<string>('');
  
  const [interactionState, setInteractionState] = useState<any>({ type: 'none', message: '' });
  const [masteryList, setMasteryList] = useState<any[]>([]);
  const [totalScore, setTotalScore] = useState(0);
  const [prevMastery, setPrevMastery] = useState<Record<string, string>>({});
  
  const [showCelebration, setShowCelebration] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);
  const triggeredPagesRef = useRef<Set<number>>(new Set());
  const allTopicsRef = useRef<any[]>([]); 

  useEffect(() => {
    allTopicsRef.current = allTopics;
  }, [allTopics]);

  // 🌟 新增：如果处于复习模式，拉取后端的复习队列
  useEffect(() => {
    if (playMode === 'review') {
      apiClient.get('/session/review-queue').then(res => {
        setReviewQueueTopics(res.data.topics || []);
      }).catch(e => console.error("获取复习队列失败", e));
    }
  }, [playMode]);

  const syncBackendState = async (triggerCelebration = false) => {
    try {
      const res = await SessionAPI.getState();
      const data = res.data;
      const masteryMap = data.mastery || []; 
      const allNormalTopics = data.topics.filter((t: any) => !t.tags?.includes('facet:root'));
      
      setAllTopics(allNormalTopics);
      setMasteryList(masteryMap);
      setTotalScore(data.learning?.total_score || 0);

      const newMasteryRecord: Record<string, string> = {};
      masteryMap.forEach((m: any) => newMasteryRecord[m.topic_id] = m.mastery_state);

      if (triggerCelebration && currentTopicId) {
        const m = masteryMap.find((m: any) => m.topic_id === currentTopicId);
        const isMastered = m?.mastery_state === 'mastered' || m?.mastery_state === 'true_mastered';
        if (isMastered && prevMastery[currentTopicId] !== 'mastered' && prevMastery[currentTopicId] !== 'true_mastered') {
           setShowCelebration(true); 
        }
      }
      setPrevMastery(newMasteryRecord);
    } catch (e) {
      console.error("同步后端状态失败", e);
    }
  };

  useEffect(() => {
    SessionAPI.getState().then(res => {
      const data = res.data;
      const topics = data?.topics || [];
      const rootSubjects = topics.filter((t: any) => t.tags?.includes('facet:root'));
      const normalNodes = topics.filter((t: any) => !t.tags?.includes('facet:root'));
      
      // 🌟 核心分流逻辑：复习模式 VS 学习模式
      if (playMode === 'review') {
        // 复习模式下，强行捏造一个“复习任务”大类
        setSubjects([{ topic_id: 'review_root', title: '复习任务' }]);
        setActiveSubjectId('review_root');
      } else {
        setSubjects(rootSubjects);
        if (rootSubjects.length > 0) setActiveSubjectId(rootSubjects[0].topic_id);
      }
      
      setAllTopics(normalNodes);
      setMasteryList(data?.mastery || []);
      setTotalScore(data?.learning?.total_score || 0);
    }).catch(e => console.error("获取图谱状态失败", e));
  }, [playMode]);

  useEffect(() => {
    if (!activeSubjectId || allTopics.length === 0) return;

    let subjectTopics = [];

    // 🌟 过滤节点：复习模式只显示队列里的节点
    if (playMode === 'review') {
      subjectTopics = allTopics.filter(t => reviewQueueTopics.includes(t.topic_id));
    } else {
      const getDescendants = (parentId: string, all: any[]): any[] => {
        const children = all.filter(t => t.parent_ids?.includes(parentId));
        let res = [...children];
        children.forEach(c => { res = res.concat(getDescendants(c.topic_id, all)); });
        return res;
      };
      subjectTopics = getDescendants(activeSubjectId, allTopics);
    }

    const fallbackIcons = ['🦕', '🌋', '☄️', '🌟', '🚀', '🌍', '🔬', '💡'];
    const dynamicNodes = subjectTopics.map((topic: any, index: number) => {
      const nodeMastery = masteryList.find((m: any) => m.topic_id === topic.topic_id);
      const isMastered = nodeMastery?.mastery_state === 'mastered' || nodeMastery?.mastery_state === 'true_mastered';
      return {
        id: topic.topic_id,
        title: topic.title,
        status: isMastered ? 'completed' : (topic.topic_id === currentTopicId ? 'current' : 'locked'),
        icon: fallbackIcons[index % fallbackIcons.length]
      };
    });

    setTreeNodes(dynamicNodes);

    if (!subjectTopics.find(t => t.topic_id === currentTopicId)) {
      if (subjectTopics.length > 0) setCurrentTopicId(subjectTopics[0].topic_id);
      else setCurrentTopicId(''); 
    }
  }, [activeSubjectId, allTopics, masteryList, currentTopicId, playMode, reviewQueueTopics]);

  useEffect(() => {
    setInteractionState({ type: 'none', message: '' });
    triggeredPagesRef.current.clear();
    
    if (!currentTopicId) {
      setPdfResourceUrl(null);
      setCurrentResourceName('');
      return;
    }

    import('../api/client').then(({ ResourceAPI }) => {
      ResourceAPI.getTopicResources(currentTopicId).then(res => {
        const resources = res.data?.resources || [];
        const pdfResource = resources.find((r: any) => 
          r.media_type === 'pdf' || (r.resource_url && r.resource_url.toLowerCase().endsWith('.pdf'))
        );

        if (pdfResource) {
          setCurrentResourceName(pdfResource.resource_name);
          import('../api/config').then(({ API_BASE_NO_VERSION, API_BASE }) => {
            const url = pdfResource.resource_url;
            let fullUrl = url;
            if (!url.startsWith('http')) {
               const baseUrl = typeof API_BASE_NO_VERSION !== 'undefined' ? API_BASE_NO_VERSION : API_BASE.replace(/\/v1\/?$/, '');
               fullUrl = `${baseUrl}${url.startsWith('/') ? '' : '/'}${url}`;
            }
            setPdfResourceUrl(fullUrl);
          });
        } else {
          setPdfResourceUrl(null);
          setCurrentResourceName('');
          
          const topicNode = allTopicsRef.current.find(t => t.topic_id === currentTopicId);
          const topicTitle = topicNode ? topicNode.title : "新知识";
          const greeting = `${userProfile.name}，我们现在来探索关于【${topicTitle}】的奥秘吧，你可以按住麦克风问我任何问题哦！`;
          setInteractionState({ type: 'feedback', message: greeting });
          handleHoverRead(greeting);
        }
      }).catch(e => console.error("获取资源失败:", e));
    });
  }, [currentTopicId, userProfile.name]);

  const handlePageChange = async (p: number, totalPages: number = 0) => {
    if (!currentTopicId) return;
    if (triggeredPagesRef.current.has(p)) return; 

    setIsLoading(true);
    try {
      const response = await SessionAPI.getKnowledgeByPage(currentTopicId, p);
      const data = response.data;
      
      const question = data.guiding_question ? data.guiding_question.trim() : "";
      const hint = data.teaching_hint ? data.teaching_hint.trim() : "";
      let cleanMessage = [question, hint].filter(Boolean).join("\n");

      if (!cleanMessage && data.knowledge_text) {
        cleanMessage = data.knowledge_text.trim();
      }

      if (cleanMessage) {
        setInteractionState({ type: 'feedback', message: cleanMessage });
        handleHoverRead(cleanMessage);
        triggeredPagesRef.current.add(p); 
      } else {
        setInteractionState({ type: 'none', message: '' });
      }
    } catch (error) {
      console.error("AI 巡场提问失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleHoverRead = (text: string) => {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 0.85;
    utterance.pitch = 1.1;
    window.speechSynthesis.speak(utterance);
  };

  const handleSendText = async (textToSend: string) => {
    if (!textToSend.trim() || isLoading) return;
    window.speechSynthesis.cancel();
    setIsLoading(true);
    try {
      const res = await SessionAPI.sendTextRealtime(textToSend);
      setInteractionState({ type: 'feedback', message: res.data.reply_text });
      handleHoverRead(res.data.reply_text);
      await syncBackendState(true);
    } catch (error) {
      setInteractionState({ type: 'feedback', message: '哎呀，网络好像断开了！' });
    } finally {
      setIsLoading(false);
    }
  };

  const startRecording = async () => {
    window.speechSynthesis.cancel();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        handleSendAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };
      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      await appDialog.alert("星空兔需要你的麦克风权限！");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleSendAudio = async (blob: Blob) => {
    setIsLoading(true);
    try {
      const response = await SessionAPI.sendAudio(blob);
      setInteractionState({ type: 'feedback', message: response.data.reply_text });
      handleHoverRead(response.data.reply_text);
      await syncBackendState(true);
    } catch (error) {
      setInteractionState({ type: 'feedback', message: '哎呀，语音魔法失效了！' });
    } finally {
      setIsLoading(false);
    }
  };

  const isCustomImage = userProfile.avatar.startsWith('data:image');

  return (
    <div className="w-screen h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-purple-50 to-fuchsia-50 flex flex-col py-6 px-6 md:px-10 gap-6">
      
      <header className="w-full max-w-[1800px] mx-auto h-20 md:h-24 bg-white/50 backdrop-blur-2xl border-2 border-white/70 rounded-3xl flex items-center justify-between px-8 shadow-sm shrink-0 z-50">
        <div className="flex items-center gap-6">
          <button onClick={() => navigate(-1)} className="flex items-center gap-2 px-5 py-2.5 bg-white/70 text-indigo-900 rounded-full font-black text-lg hover:bg-white active:scale-[0.96] transition-all cursor-pointer border border-white shadow-sm">
            <ArrowLeft size={20} strokeWidth={3} /> 返回上一页
          </button>
          
          {subjects.length > 0 && (
            <div className="flex bg-white/50 backdrop-blur-md rounded-full p-1 border border-white shadow-sm ml-4">
              {subjects.map(sub => (
                <button
                  key={sub.topic_id}
                  onClick={() => setActiveSubjectId(sub.topic_id)}
                  className={`px-6 py-2 rounded-full font-black text-sm transition-all cursor-pointer ${
                    activeSubjectId === sub.topic_id 
                      ? 'bg-gradient-to-r from-purple-500 to-fuchsia-500 text-white shadow-md' 
                      : 'text-gray-600 hover:bg-white/80 hover:text-purple-600'
                  }`}
                >
                  {sub.title}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-6">
          {/* 🌟 右上角渲染自定义头像 */}
          <div 
            onClick={() => setShowProfileModal(true)}
            className="w-14 h-14 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 font-black text-2xl shadow-sm border-[3px] border-white hover:scale-110 transition-transform cursor-pointer select-none overflow-hidden"
            title="点击修改个人信息"
          >
            {isCustomImage ? <img src={userProfile.avatar} alt="avatar" className="w-full h-full object-cover" /> : userProfile.avatar}
          </div>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[1800px] mx-auto bg-white/40 backdrop-blur-2xl border-2 border-white/60 rounded-[2.5rem] shadow-sm flex flex-row items-stretch justify-between p-6 xl:p-8 gap-6 xl:gap-8 relative overflow-hidden">
        
        <div className="w-[280px] xl:w-[320px] shrink-0 flex flex-col gap-6 justify-center z-20 h-full">
          <InlineKnowledgeMap nodes={treeNodes} onSelectNode={setCurrentTopicId} />
          <UserStatsCard totalScore={totalScore} />
        </div>

        <div className="flex-1 h-full relative z-10 bg-white/30 rounded-3xl border border-white/50 shadow-inner flex flex-col min-w-[400px] overflow-hidden">
          {pdfResourceUrl ? (
            <>
              <div className="w-full bg-white/70 backdrop-blur-md px-6 py-3 border-b border-white/50 flex items-center justify-between z-20 shadow-sm shrink-0">
                <div className="flex items-center gap-2">
                  <span className="bg-purple-100 text-purple-600 p-1.5 rounded-lg"><BookOpen size={16} /></span>
                  <span className="font-bold text-indigo-900 text-sm">关联教材：{currentResourceName || '学习课件'}</span>
                </div>
              </div>
              <div className="flex-1 w-full relative p-4">
                <PdfViewer url={pdfResourceUrl} onRenderComplete={handlePageChange} />
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center text-gray-400 gap-4 bg-white/50 border-2 border-dashed border-white m-4 rounded-2xl w-[calc(100%-2rem)] h-[calc(100%-2rem)]">
              <div className="text-8xl mb-4 animate-bounce">🐰</div>
              <p className="text-2xl font-black text-indigo-900">我们直接开始畅聊吧！</p>
              <p className="text-sm font-medium bg-white/60 px-4 py-2 rounded-full border border-white">右侧的星空兔已经准备好啦</p>
            </div>
          )}
        </div>

        <div className="w-[360px] xl:w-[420px] shrink-0 flex flex-col items-center justify-end z-20 gap-6 h-full relative">
          <div className="w-36 h-36 xl:w-44 xl:h-44 shrink-0 rounded-full bg-gradient-to-br from-white to-fuchsia-100 border-4 border-white shadow-[0_15px_40px_rgba(217,70,239,0.25)] flex items-center justify-center text-6xl xl:text-7xl relative z-30 transform transition-transform hover:scale-105 animate-[bounce_4s_ease-in-out_infinite]">
            🐰
            <div className="absolute -bottom-3 bg-fuchsia-100 text-fuchsia-600 px-4 py-1.5 rounded-full text-xs font-black shadow-sm border border-white whitespace-nowrap">Live2D 待接入</div>
          </div>
          <InteractionCard state={interactionState} isLoading={isLoading} isRecording={isRecording} onStartRecord={startRecording} onStopRecord={stopRecording} onPlayVoice={handleHoverRead} onSend={handleSendText} />
        </div>
      </main>

      {showCelebration && (
        <CelebrationModal 
          topicTitle={treeNodes.find(n => n.id === currentTopicId)?.title || "新知识"} 
          topicIcon={treeNodes.find(n => n.id === currentTopicId)?.icon || "🌟"}
          onClose={() => setShowCelebration(false)} 
        />
      )}

      {showProfileModal && (
        <ProfileModal
          profile={userProfile}
          onClose={() => setShowProfileModal(false)}
          onSave={(newProfile: any) => {
            setUserProfile(newProfile);
            localStorage.setItem('looptutor_profile', JSON.stringify(newProfile));
          }}
        />
      )}
    </div>
  );
}