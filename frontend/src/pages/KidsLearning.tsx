import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, Star, Mic, Send, HelpCircle, Loader2, Volume2, Pause } from 'lucide-react';
import { SessionAPI } from '../api/client';
import { API_BASE, API_BASE_NO_VERSION } from '../api/config';
import PdfViewer from "../components/PdfViewer";
import { useAppDialog } from '../components/AppDialog';
import LanguageSwitcher from '../i18n/LanguageSwitcher';

const COMPANIONS: Record<string, string> = {
  rabbit: "🐰",
  dinosaur: "🦖"
};

export default function KidsLearning() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const appDialog = useAppDialog();
  const apiBaseUrl = API_BASE;

  type TopicResource = {
    resource_id: string;
    resource_name: string;
    media_type: string;
    resource_url: string;
  };

  const getCompanionLabel = (key: string) => key === 'rabbit' ? t('roles.starRabbit') : t('roles.littleDino');
  const getCompanionEmoji = (key: string) => COMPANIONS[key] || '🐰';

  const [companion, setCompanion] = useState("rabbit");
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [speakingText, setSpeakingText] = useState<string | null>(null);
  const triggeredPagesRef = useRef<Set<number>>(new Set());
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      window.speechSynthesis.cancel();
    };
  }, []);

  const [todayTopic, setTodayTopic] = useState('恐龙的秘密');
  const [todayTopicId, setTodayTopicId] = useState('');
  const [topicResources, setTopicResources] = useState<TopicResource[]>([]);
  const [previewResource, setPreviewResource] = useState<TopicResource | null>(null);

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
        // silent failure
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
      try {
        // 优先尝试获取当前 topic 绑定的资源
        if (todayTopicId) {
          const res = await fetch(`${apiBaseUrl}/resource/topics/${todayTopicId}`);
          if (res.ok) {
            const data = await res.json();
            const resources = (data.resources || []) as TopicResource[];
            if (resources.length > 0) {
              setTopicResources(resources);
              const previewable = resources.find((resource) =>
                ['video', 'image', 'audio', 'pdf'].includes(resource.media_type) ||
                resource.resource_url.toLowerCase().endsWith('.pdf')
              );
              setPreviewResource(previewable || null);
              return;
            }
          }
        }

        // 回退：当前 topic 无资源时，显示所有已导入的资源
        const res = await fetch(`${apiBaseUrl}/resources`);
        if (res.ok) {
          const allData = await res.json();
          const allResources = (Array.isArray(allData) ? allData : allData.resources || []) as TopicResource[];
          setTopicResources(allResources);

          const previewable = allResources.find((resource: TopicResource) =>
            ['video', 'image', 'audio', 'pdf'].includes(resource.media_type) ||
            resource.resource_url.toLowerCase().endsWith('.pdf')
          );
          setPreviewResource(previewable || null);
        } else {
          setTopicResources([]);
          setPreviewResource(null);
        }
      } catch (e) {
        setTopicResources([]);
        setPreviewResource(null);
      }
    };

    void fetchTopicResources();
  }, [todayTopicId]);

  const companionName = getCompanionLabel(companion);

  const [messages, setMessages] = useState([
    { role: 'assistant', content: t('learning.greeting', { companion: companionName }) }
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

  const toggleRead = async (text: string) => {
    if (speakingText === text) {
      if (ttsAudioRef.current) {
        ttsAudioRef.current.pause();
        ttsAudioRef.current = null;
      }
      setSpeakingText(null);
      return;
    }

    if (ttsAudioRef.current) {
      ttsAudioRef.current.pause();
      ttsAudioRef.current = null;
    }
    
    window.speechSynthesis.cancel();

    try {
      setSpeakingText(text);

      const voiceName = companion === "rabbit" ? "zh-CN-XiaoxiaoNeural" : "zh-CN-YunxiNeural";
      const response = await SessionAPI.synthesizeSpeech(text, voiceName);
      
      const audioBlob = response.data;
      const audioUrl = URL.createObjectURL(audioBlob);

      const audio = new Audio(audioUrl);
      ttsAudioRef.current = audio;

      audio.onended = () => {
        setSpeakingText(null);
        ttsAudioRef.current = null;
        URL.revokeObjectURL(audioUrl);
      };
      
      audio.onerror = () => {
        console.error(t('learning.audioFailed'));
        setSpeakingText(null);
      };

      await audio.play();

    } catch (error) {
      console.error("TTS failed:", error);
      setSpeakingText(null);
    }
  };

  const resolveResourceUrl = (resourceUrl: string) => {
    if (resourceUrl.startsWith('http://') || resourceUrl.startsWith('https://')) {
      return resourceUrl;
    }
    return `${API_BASE_NO_VERSION}${resourceUrl}`;
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
        handleSendAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error("Mic permission denied:", error);
      await appDialog.alert(t('learning.micPermission'), { title: t('learning.micPermissionTitle'), intent: 'warning' });
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
    setMessages(prev => [...prev, { role: 'user', content: `🎤 ${t('learning.listening')}` }]);

    try {
      const response = await SessionAPI.sendAudio(blob);
      const { recognized_text, reply_text } = response.data;

      setMessages(prev => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1].content = `🎤 ${recognized_text || t('learning.noSound')}`;
        return [...newMsgs, { role: 'assistant', content: reply_text }];
      });

      toggleRead(reply_text);
    } catch (error) {
      console.error("Voice send failed:", error);
      setMessages(prev => [...prev, { role: 'assistant', content: t('learning.voiceFailed') }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handlePdfPageTurned = async (pageNumber: number) => {
    if (!todayTopicId) return;

    if (triggeredPagesRef.current.has(pageNumber)) return;

    setIsLoading(true);
    try {
      const response = await SessionAPI.getKnowledgeByPage(todayTopicId, pageNumber);
      const data = response.data;

      const question = data.guiding_question ? data.guiding_question.trim() : "";
      const hint = data.teaching_hint ? data.teaching_hint.trim() : "";

      if (!question && !hint) {
        return;
      }

      const cleanMessage = [question, hint].filter(Boolean).join("\n");

      if (cleanMessage) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: cleanMessage 
        }]);
        
        triggeredPagesRef.current.add(pageNumber);
      }
    } catch (error) {
      console.error("Failed to get page knowledge:", error);
    } finally {
      setIsLoading(false);
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
      const audioUrl = `${API_BASE}/session/output/audio/stream/${streamId}`;
      const audio = new Audio(audioUrl);
      currentAudioRef.current = audio;

      audio.onended = () => { currentAudioRef.current = null; };
      audio.play().catch(e => console.error("Audio play blocked:", e));

    } catch (error) {
      console.error("Backend request failed:", error);
      setMessages(prev => [...prev, { role: 'assistant', content: t('learning.networkError') }]);
    } finally {
      setIsLoading(false);
    }
  };

  const companionEmoji = getCompanionEmoji(companion);

  return (
    <div className="flex flex-col h-screen overflow-hidden p-6 gap-6">

      <div className="bg-white/60 backdrop-blur-md rounded-3xl p-4 px-6 flex justify-between items-center shadow-sm border border-white/50">
        <button onClick={() => navigate('/')} className="flex items-center gap-2 text-dark hover:text-primary transition-colors font-bold">
          <ChevronLeft size={24} /> {t('common.backToHall')}
        </button>
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-4 text-xl font-bold text-dark">
            <span className="flex items-center gap-1 text-secondary"><Star fill="currentColor" /> 45</span>
            <span className="text-gray-300">|</span>
            <div className="flex items-center gap-2">
              <span>{t('learning.companion')}:</span>
              <select value={companion} onChange={(e) => setCompanion(e.target.value)} className="bg-transparent text-2xl cursor-pointer outline-none hover:scale-110 transition-transform appearance-none text-center">
                {Object.keys(COMPANIONS).map(key => <option key={key} value={key}>{COMPANIONS[key]}</option>)}
              </select>
            </div>
          </div>
        </div>
        <div className="w-24 flex justify-end">
          <LanguageSwitcher />
        </div>
      </div>

      <div className="flex flex-1 gap-6 h-[calc(100vh-140px)] min-h-0">

        <div className="flex-[6] bg-white/60 backdrop-blur-md rounded-[30px] p-6 shadow-sm border border-white/50 flex flex-col">
          <h3 onClick={() => toggleRead(`${t('learning.todayTopic')}: ${todayTopic}`)} className="text-2xl font-bold text-blue mb-4 cursor-pointer hover:text-primary transition-colors flex items-center gap-2 w-fit select-none">
            {t('learning.todayTopic')}: {todayTopic} 
            {speakingText === `${t('learning.todayTopic')}: ${todayTopic}` ? (
               <Pause size={20} className="text-primary animate-pulse" />
            ) : (
               <Volume2 size={20} className="opacity-50" />
            )}
          </h3>
          <div className="w-full flex-1 bg-black/5 rounded-2xl overflow-hidden flex items-center justify-center border-2 border-white/80 relative">
            {previewResource ? (
              previewResource.media_type === 'video' ? (
              <video className="w-full h-full object-cover" controls src={resolveResourceUrl(previewResource.resource_url)} />
            ) : previewResource.media_type === 'pdf' || previewResource.resource_url.endsWith('.pdf') ? (
              <PdfViewer
                url={resolveResourceUrl(previewResource.resource_url)}
                onRenderComplete={handlePdfPageTurned}
              />
            ) : previewResource.media_type === 'image' ? (
              <img className="w-full h-full object-contain" src={resolveResourceUrl(previewResource.resource_url)} alt={previewResource.resource_name} />
            ) : previewResource.media_type === 'audio' ? (
              <div className="w-full h-full flex items-center justify-center">
                <audio controls src={resolveResourceUrl(previewResource.resource_url)} className="w-4/5" />
              </div>
            ) : (
              <div className="text-center text-gray-500 px-6">
                <p className="text-lg font-medium">{t('learning.noPreview')}</p>
                <p className="text-sm mt-2">{t('learning.noPreviewHint')}</p>
              </div>
            )) : topicResources.length > 0 ? (
              // 有资源但无可预览类型时，显示第一个资源的概要信息
              <div className="text-center px-6">
                <p className="text-3xl mb-3">📄</p>
                <p className="text-lg font-bold text-gray-700">{topicResources[0].resource_name}</p>
                <p className="text-sm text-gray-500 mt-1 uppercase">{topicResources[0].media_type}</p>
                <a
                  href={resolveResourceUrl(topicResources[0].resource_url)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block mt-4 px-6 py-2 bg-pink-100 text-pink-700 rounded-full font-bold text-sm hover:bg-pink-200 transition-colors"
                >
                  {t('learning.open')}
                </a>
                <p className="text-xs text-gray-400 mt-3">{t('learning.noPreviewHint')}</p>
              </div>
            ) : (
              <div className="text-center text-gray-500 px-6">
                <p className="text-lg font-medium">{t('learning.noPreview')}</p>
                <p className="text-sm mt-2">{t('learning.noPreviewHint')}</p>
              </div>
            )}
          </div>
          <div className="mt-4 bg-white/70 rounded-2xl border border-white/70 p-4 max-h-48 overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-bold text-dark">{t('learning.resources')}</p>
              <p className="text-xs text-gray-500">{t('learning.resourceCount', { count: topicResources.length })}</p>
            </div>
            {topicResources.length === 0 ? (
              <p className="text-sm text-gray-400">{t('learning.noResources')}</p>
            ) : (
              <div className="space-y-2">
                {topicResources.map((resource) => {
                  const isPreviewable = ['video', 'image', 'audio', 'pdf'].includes(resource.media_type) || resource.resource_url.toLowerCase().endsWith('.pdf');
                  return (
                    <div key={resource.resource_id} className="flex items-center justify-between bg-white rounded-xl px-3 py-2 border border-white/80">
                      <div>
                        <p className="text-sm font-medium text-dark">{resource.resource_name}</p>
                        <p className="text-xs text-gray-500 uppercase">{resource.media_type}</p>
                      </div>
                      <div className="flex gap-2">
                        {isPreviewable && (
                          <button
                            onClick={() => setPreviewResource(resource)}
                            className="text-xs px-3 py-1 rounded-full bg-sky-100 text-sky-700 hover:bg-sky-200 transition-colors"
                          >
                            {t('learning.preview')}
                          </button>
                        )}
                        <a
                          href={resolveResourceUrl(resource.resource_url)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs px-3 py-1 rounded-full bg-pink-100 text-pink-700 hover:bg-pink-200 transition-colors"
                        >
                          {t('learning.open')}
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex-[4] bg-white/40 backdrop-blur-md rounded-[30px] p-5 shadow-sm border border-white/50 flex flex-col min-h-0">
          <h3 className="text-xl font-bold text-primary mb-4 flex items-center gap-2">...</h3>

          <div className="flex-1 overflow-y-auto pr-2 space-y-4 mb-4 scrollbar-hide min-h-0">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className="text-2xl">{msg.role === 'user' ? '👦' : companionEmoji}</div>
                <div
                  className={`p-4 rounded-2xl max-w-[80%] shadow-sm transition-all duration-300 relative group flex items-start gap-2 ${msg.role === 'user' ? 'bg-blue/10 text-dark rounded-tr-sm border border-blue/20' : 'bg-white text-dark rounded-tl-sm border border-white/80'
                    }`}
                >
                  <span className="flex-1">{msg.content}</span>

                  {msg.role === 'assistant' && (
                    <button
                      onClick={() => toggleRead(msg.content)}
                      className="p-1.5 bg-gray-50 text-gray-400 hover:text-primary hover:bg-pink-50 rounded-lg transition-colors flex-shrink-0 cursor-pointer border border-transparent hover:border-pink-200"
                      title={speakingText === msg.content ? t('learning.stopReading') : t('learning.clickToRead')}
                    >
                      {speakingText === msg.content ? (
                        <Pause size={16} className="text-primary animate-pulse" />
                      ) : (
                        <Volume2 size={16} />
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex gap-3 flex-row">
                <div className="text-2xl">{companionEmoji}</div>
                <div className="p-4 rounded-2xl bg-white text-dark rounded-tl-sm flex items-center gap-2"><Loader2 className="animate-spin text-primary" size={20} /><span className="text-sm">{t('learning.thinking')}</span></div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="flex flex-col gap-3 mt-auto">
            <div className="flex gap-2">
              <input type="text" value={inputText} onChange={(e) => setInputText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSendText(inputText)} disabled={isLoading} placeholder={t('learning.typePlaceholder')} className="flex-1 bg-white/80 border-2 border-white rounded-2xl px-4 py-3 outline-none focus:border-primary shadow-sm disabled:opacity-50" />
              <button onClick={() => handleSendText(inputText)} disabled={isLoading} className="bg-white/80 text-primary border-2 border-white hover:border-primary hover:bg-primary hover:text-white p-3 rounded-2xl transition-all shadow-sm disabled:opacity-50">
                <Send size={20} />
              </button>
            </div>

            <div className="flex gap-3">
              <button
                onMouseDown={startRecording}
                onMouseUp={stopRecording}
                onMouseLeave={stopRecording}
                disabled={isLoading}
                className={`flex-[3] text-white font-bold py-4 rounded-2xl shadow-md transition-all duration-300 flex items-center justify-center gap-2 text-lg select-none relative overflow-hidden ${isRecording
                  ? 'bg-red-500 scale-95 shadow-[0_0_20px_rgba(239,68,68,0.6)]'
                  : 'bg-primary hover:bg-primary/90 hover:shadow-lg'
                  }`}
              >
                {isRecording && (
                  <span className="absolute inset-0 bg-white/20 animate-ping rounded-2xl"></span>
                )}
                <Mic size={24} className={isRecording ? "animate-bounce" : ""} />
                {isRecording ? t('learning.listening') : t('learning.holdToSpeak')}
              </button>

              <button onClick={() => handleSendText(t('learning.dontUnderstandMsg'))} disabled={isLoading} className="flex-[1] bg-white/80 text-dark font-bold py-4 rounded-2xl shadow-sm border-2 border-white hover:border-gray-200 transition-colors flex items-center justify-center flex-col text-xs gap-1 disabled:opacity-50">
                <HelpCircle size={18} className="text-blue" />{t('learning.dontUnderstand')}
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
