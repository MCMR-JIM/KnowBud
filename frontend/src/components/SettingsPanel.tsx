import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { SettingsAPI } from '../api/client';
import { X } from 'lucide-react';

type GPUInfo = {
  cuda_available: boolean;
  gpu_name: string;
  vram_total_gb: number;
  vram_free_gb: number;
};

type ModelDef = {
  key: string;
  label: string;
  size: string;
  vram: string;
  gpu: string;
  repo_id: string;
  description: string;
  context_limit?: string;
};

type DownloadState = {
  progress: number;
  status: string;
  speed?: number;
};

type Provider = {
  key: string;
  label: string;
  baseUrl: string;
  models: string[];
  helpUrl: string;
  contextLimit?: string;
};

const PROVIDERS: Provider[] = [
  { key: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', models: ['deepseek-v4-flash', 'deepseek-v4-pro'], helpUrl: 'https://platform.deepseek.com/api_keys', contextLimit: '1000000' },
  { key: 'custom', label: '自定义', baseUrl: '', models: [], helpUrl: '' },
];

function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="group relative ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-gray-300 text-[10px] font-bold text-white">
      i
      <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 rounded-lg bg-gray-800 px-3 py-2 text-xs leading-relaxed text-white opacity-0 transition-opacity group-hover:opacity-100" style={{ width: '200px' }}>
        {text}
      </span>
    </span>
  );
}

export default function SettingsPanel() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'api' | 'local'>('api');
  const [provider, setProvider] = useState<string>('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [testResult, setTestResult] = useState('');
  const [skipLocalParsing, setSkipLocalParsing] = useState(false);
  const [gpu, setGpu] = useState<GPUInfo | null>(null);
  const [gpuLoading, setGpuLoading] = useState(false);
  const [localPath, setLocalPath] = useState('');
  const [localModel, setLocalModel] = useState('');
  const [localPort, setLocalPort] = useState(8000);
  const [dtype, setDtype] = useState('bf16');
  const [maxTokens, setMaxTokens] = useState(500);
  const [temp, setTemp] = useState(0.7);
  const [timeoutSec, setTimeoutSec] = useState(120);
  const [models, setModels] = useState<ModelDef[]>([]);
  const [parserModels, setParserModels] = useState<ModelDef[]>([]);
  const [modelPaths, setModelPaths] = useState<Record<string, string>>({});
  const [downloadStates, setDownloadStates] = useState<Record<string, DownloadState>>({});
  const [saving, setSaving] = useState(false);
  const [confirmModal, setConfirmModal] = useState<{open: boolean, title: string, message: string, onConfirm: () => void, confirmText: string} | null>(null);
  const intervalRefs = useRef<Record<string, ReturnType<typeof setInterval>>>({});
  const settingsLoadedRef = useRef(false);

  useEffect(() => {
    void loadSettings();
    void loadModels();
    void detectGPU();
  }, []);

  async function loadSettings() {
    try {
      const res = await SettingsAPI.getSettings();
      const data = res.data;
      if (data.mode) setMode(data.mode === 'local' ? 'local' : 'api');
      if (data.provider) setProvider(data.provider);
      if (data.remote) { setApiKey(data.remote.api_key||''); setBaseUrl(data.remote.base_url||''); setModel(data.remote.model||''); setSkipLocalParsing(data.remote.skip_local_parsing||false); }
      if (data.local) { setLocalPath(data.local.model_path||''); setLocalModel(data.local.model||''); setLocalPort(data.local.port||8000); setDtype(data.local.precision||'bf16'); setMaxTokens(data.local.max_tokens||500); setTemp(data.local.temperature!=null?data.local.temperature:0.7); setTimeoutSec(data.local.timeout_sec||120); }
      if (data.model_paths) setModelPaths(data.model_paths);
      settingsLoadedRef.current = true;
    } catch { settingsLoadedRef.current = true; }
  }

  useEffect(() => {
    if (localModel || !localPath) return;
    const matchedEntry = Object.entries(modelPaths).find(([, path]) => path === localPath);
    if (matchedEntry) setLocalModel(matchedEntry[0]);
  }, [localModel, localPath, modelPaths]);

  async function detectGPU() {
    setGpuLoading(true);
    try {
      const res = await SettingsAPI.getGPU();
      setGpu(res.data);
    } catch { /* ignore */ } finally { setGpuLoading(false); }
  }

  async function loadModels() {
    try {
      const res = await SettingsAPI.getModels();
      const raw = res.data.models || {};
      const list: ModelDef[] = Object.entries(raw).map(([key, info]: [string, unknown]) => {
        const m = info as Record<string, string>;
        return { key, label: m.label || key, size: m.size || '', vram: m.vram || '', gpu: m.gpu || '', repo_id: m.repo_id || '', description: m.description || '', context_limit: m.context_limit || '' };
      });
      setModels(list);
      const rawParser = res.data.parser_models || {};
      const parserList = Object.entries(rawParser).map(([key, info]: [string, unknown]) => {
        const m = info as Record<string, string>;
        return { key, label: m.label || key, size: m.size || '', vram: m.vram || '', gpu: m.gpu || '', repo_id: m.repo_id || '', description: m.description || '' };
      });
      setParserModels(parserList);
      for (const def of [...list, ...parserList]) void checkDownloadStatus(def.key);
    } catch { /* ignore */ }
  }

  async function testConnection() {
    setTestResult(t('settings.testing'));
    try { await SettingsAPI.getModels(); setTestResult(t('settings.connectionSuccess')); }
    catch { setTestResult(t('settings.connectionFailed')); }
  }

  // Scan existing model paths to detect already-downloaded models
  async function scanExistingModels() {
    for (const m of [...models, ...parserModels]) {
      const path = modelPaths[m.key]?.trim();
      if (!path) continue;
      try {
        const res = await SettingsAPI.validatePath(m.key, path);
        if (res.data?.valid) {
          setDownloadStates((prev) => ({ ...prev, [m.key]: { progress: 100, status: 'done' } }));
        }
      } catch { /* ignore */ }
    }
  }

  // Save modelPaths to backend on change
  useEffect(() => {
    if (!settingsLoadedRef.current) return;
    if (Object.keys(modelPaths).length === 0) return;
    const timer = setTimeout(() => {
      SettingsAPI.saveSettings({ model_paths: modelPaths }).catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [modelPaths]);

  useEffect(() => {
    if (!settingsLoadedRef.current) return;
    const timer = setTimeout(() => {
      setSaving(true);
      SettingsAPI.saveSettings({
        mode: mode === 'local' ? 'local' : 'remote',
        provider,
        remote: { api_key: apiKey, base_url: baseUrl, model, skip_local_parsing: skipLocalParsing },
        local: {
          model_path: localPath,
          model: localModel,
          port: localPort,
          precision: dtype,
          temperature: temp,
          timeout_sec: timeoutSec,
          max_tokens: maxTokens,
        },
      }).finally(() => setSaving(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [mode, provider, apiKey, baseUrl, model, skipLocalParsing, localPath, localModel, localPort, dtype, temp, timeoutSec, maxTokens]);

  // Scan when models or paths change
  useEffect(() => {
    if (models.length > 0 || parserModels.length > 0) void scanExistingModels();
  }, [models, parserModels, modelPaths]);

  async function checkDownloadStatus(modelKey: string) {
    try {
      const res = await SettingsAPI.getDownloadStatus(modelKey);
      if (!res.data) return;
      const prog = res.data.progress;
      let status = 'not_started';
      if (res.data.status === 'downloading') status = 'downloading';
      else if (res.data.status === 'completed' || prog >= 100) status = 'done';
      else if (res.data.status === 'failed' || prog === -1) status = 'error';
      else if (res.data.status === 'cancelled') status = 'cancelled';
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { progress: prog, status, speed: res.data?.speed_mbps } }));
    } catch { /* ignore */ }
  }

  const handleProviderChange = useCallback((p: Provider) => {
    setProvider(p.key);
    setBaseUrl(p.baseUrl);
    setModel(p.models.length > 0 ? p.models[0] : '');
  }, []);

  const handlePause = useCallback(async (modelKey: string) => {
    try {
      await SettingsAPI.pauseDownload(modelKey);
      if (intervalRefs.current[modelKey]) { clearInterval(intervalRefs.current[modelKey]); delete intervalRefs.current[modelKey]; }
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { ...(prev[modelKey] || { progress: 0, status: '' }), status: 'paused' } }));
    } catch { /* ignore */ }
  }, []);

  const handleResume = useCallback(async (modelKey: string) => {
    try {
      const path = modelPaths[modelKey]?.trim();
      if (!path) return;
      await SettingsAPI.downloadModel(modelKey, path);
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { ...(prev[modelKey] || { progress: 0, status: '' }), status: 'downloading' } }));
    } catch { /* ignore */ }
  }, [modelPaths]);

  const handleCancel = useCallback(async (modelKey: string) => {
    const p = modelPaths[modelKey] || '';
    setConfirmModal({
      open: true, title: t('settings.confirmCancelTitle'),
      message: `${t('settings.confirmCancelMsg')}\n${t('settings.path')}: ${p}\n\n${t('settings.confirmCancelCleanup')}`,
      confirmText: t('settings.cancelAndClean'), onConfirm: async () => {
        setConfirmModal(null);
        await SettingsAPI.cancelDownload(modelKey);
        if (p) await SettingsAPI.deleteModel(modelKey).catch(() => {});
        if (intervalRefs.current[modelKey]) { clearInterval(intervalRefs.current[modelKey]); delete intervalRefs.current[modelKey]; }
        setDownloadStates((prev) => ({ ...prev, [modelKey]: { progress: 0, status: 'cancelled' } }));
      }
    });
  }, [modelPaths]);

  const handleDelete = useCallback(async (modelKey: string) => {
    const path = modelPaths[modelKey]?.trim();
    if (!path) return alert(t('settings.pleaseFillPath'));
    try {
      await SettingsAPI.deleteModel(modelKey);
      setDownloadStates((prev) => { const copy = { ...prev }; delete copy[modelKey]; return copy; });
    } catch (err: unknown) {
      alert(t('settings.deleteFailed') + ': ' + (err instanceof Error ? err.message : String(err)));
    }
  }, [modelPaths]);

  function recommendedModel(): ModelDef | null {
    if (!gpu || !gpu.cuda_available || models.length === 0) return null;
    const free = gpu.vram_free_gb || gpu.vram_total_gb;
    const withVram = models.map((m) => ({ model: m, vramGb: Number((m.vram.match(/[\d.]+/) || ['0'])[0]) }));
    const affordable = withVram.filter((item) => item.vramGb > 0 && item.vramGb <= free).sort((a, b) => b.vramGb - a.vramGb);
    return affordable[0]?.model || models[0];
  }

  const recommended = recommendedModel();
  const providerModels = PROVIDERS.find((p) => p.key === provider)?.models || [];

  // Shared model card renderer for parser + LLM models
  const renderCard = (m: ModelDef, isParser: boolean) => {
    const ds = downloadStates[m.key];
    const isDownloading = ds?.status === 'downloading';
    const isDone = ds?.status === 'done';
    const progress = ds?.progress || 0;

    return (
      <div key={m.key} className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h4 className="text-base font-black text-gray-800">{m.label}</h4>
            <p className="mt-1 text-xs text-gray-400">{m.description}</p>
          </div>
          {isDownloading && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-black text-blue-600">{t('settings.downloading')}</span>}
          {ds?.status === 'paused' && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-black text-amber-600">{t('settings.paused')}</span>}
          {isDone && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-black text-emerald-600">{t('settings.downloaded')}</span>}
        </div>
        <div className="mb-3 grid grid-cols-2 gap-1 text-xs text-gray-400">
          <span>{t('settings.size')}: <strong className="text-gray-700">{m.size}</strong></span>
          {!isParser && <span>{t('settings.vram')}: <strong className="text-gray-700">{m.vram}</strong></span>}
          {!isParser && m.context_limit && <span>{t('settings.context')}: <strong className="text-gray-700">{parseInt(m.context_limit) >= 1000 ? `${(parseInt(m.context_limit)/1000).toFixed(0)}K` : m.context_limit}</strong></span>}
          <span className={isParser ? 'col-span-2' : !m.context_limit ? 'col-span-2' : ''}>{t('settings.recommended')}: <strong className="text-gray-700">{m.gpu}</strong></span>
        </div>
        <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden mb-1">
          <div className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-500 ease-out" style={{ width: `${progress}%` }}/>
        </div>
        <span className="text-sm text-gray-500">
          {isDownloading ? `${Math.round(progress)}%` + (ds?.speed ? ` · ${ds.speed.toFixed(1)} MB/s` : '') : isDone ? t('settings.completed') : ds?.status === 'error' ? t('settings.downloadFailed') : ds?.status === 'paused' ? t('settings.paused') : t('settings.waitingDownload')}
        </span>
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          {isDone ? (
            <button onClick={() => { const p = modelPaths[m.key]||''; setConfirmModal({open:true,title:t('settings.confirmDeleteTitle'),message:`${t('settings.deletePath')}: ${p}`,confirmText:t('settings.confirmDelete'),onConfirm:()=>{setConfirmModal(null);handleDelete(m.key);}});}} className="rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-100">{t('settings.delete')}</button>
          ) : isDownloading ? (<><button onClick={()=>handlePause(m.key)} className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-bold text-gray-600 hover:bg-gray-200">{t('settings.pause')}</button><button onClick={()=>handleCancel(m.key)} className="rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-100">{t('settings.cancel')}</button></>) : ds?.status==='paused' ? (<><button onClick={()=>handleResume(m.key)} className="rounded-lg bg-blue-500 px-3 py-1.5 text-xs font-bold text-gray-900 hover:bg-blue-600">{t('settings.resume')}</button><button onClick={()=>handleCancel(m.key)} className="rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-100">{t('settings.cancel')}</button></>) : (
            <button onClick={async()=>{try{const r=await SettingsAPI.browseFolder();if(!r.data?.path)return;const path=r.data.path;setModelPaths(prev=>({...prev,[m.key]:path}));const v=await SettingsAPI.validatePath(m.key,path);if(v.data?.files?.length){const ok=await new Promise(r=>{setConfirmModal({open:true,title:t('settings.folderNotEmptyTitle'),message:`${path}\n${t('settings.folderNotEmptyMsg')}`,confirmText:t('settings.stillDownload'),onConfirm:()=>{setConfirmModal(null);r(true)}})});if(!ok)return}await SettingsAPI.downloadModel(m.key,path);setDownloadStates(prev=>({...prev,[m.key]:{progress:0,status:'downloading'}}))}catch{}}} className="rounded-lg bg-blue-500 px-4 py-1.5 text-xs font-bold text-gray-900 hover:bg-blue-600">{t('settings.download')}</button>
          )}
          <button onClick={async()=>{try{const r=await SettingsAPI.browseFolder();if(!r.data?.path)return;const path=r.data.path;setModelPaths(prev=>({...prev,[m.key]:path}));const v=await SettingsAPI.validatePath(m.key,path);if(v.data?.valid)setDownloadStates(prev=>({...prev,[m.key]:{progress:100,status:'done'}}))}catch{}}} className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-bold text-gray-600 hover:bg-gray-200">{t('settings.browse')}</button>
        </div>
      </div>
    );
  };

  return (
    <div className="bg-white/80 rounded-[32px] p-8 shadow-sm space-y-6">
      <div>
        <h2 className="text-2xl font-black text-gray-800">{t('settings.title')}</h2>
        <p className="mt-1 text-sm text-gray-400">{t('settings.description')}</p>
      </div>

      {/* ===== Parser Models: Required ===== */}
      <div className="rounded-[24px] border border-rose-100 bg-gradient-to-br from-rose-50/60 to-amber-50/40 p-6">
        <h3 className="mb-1 text-sm font-black uppercase tracking-[0.14em] text-rose-600">{t('settings.parserTitle')}</h3>
        <p className="mb-4 text-xs text-gray-400">{t('settings.parserDesc')}</p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {parserModels.map((m) => renderCard(m, true))}
          {parserModels.length === 0 && <div className="col-span-2 rounded-2xl border border-dashed border-rose-200 bg-white/60 py-10 text-center text-sm text-gray-400">{t('settings.parserLoading')}</div>}
        </div>
      </div>

      {/* ===== LLM Config ===== */}
      <div className="rounded-[24px] border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-sm font-black uppercase tracking-[0.14em] text-gray-500">LLM 模型配置</h3>
        <div className="mb-5 flex rounded-2xl bg-gray-100 p-1">
          {(['api', 'local'] as const).map((m) => (
            <button key={m} type="button" onClick={() => setMode(m)}
              className={`flex-1 rounded-xl px-4 py-2.5 text-sm font-bold transition-all ${mode === m ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              {m === 'api' ? t('settings.api') : t('settings.local')}
            </button>
          ))}
        </div>

      {/* ===== Remote API Settings ===== */}
      {mode === 'api' && (
        <div className="space-y-5">
          {!apiKey.trim() && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
              {t('settings.noApiKey')}
            </div>
          )}
          {/* Provider Selection Cards */}
          <div>
            <div className="mb-3 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.providerSelection')}</span>
              <InfoTooltip text={t('settings.providerTooltip')} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              {PROVIDERS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => handleProviderChange(p)}
                  className={`rounded-2xl border-2 p-4 text-left transition-all ${provider === p.key ? 'border-blue-400 bg-blue-50/50 shadow-md ring-4 ring-blue-100' : 'border-gray-200 bg-white hover:border-gray-300'}`}
                >
                  <div className="text-sm font-black text-gray-800">{p.key === 'custom' ? t('settings.customProvider') : p.label}{p.contextLimit ? <span className="ml-1 text-[10px] font-normal text-gray-400">{parseInt(p.contextLimit) >= 1000 ? `${(parseInt(p.contextLimit)/1000).toFixed(0)}K ${t('settings.context')}` : ''}</span> : ''}</div>
                  <div className="mt-1 text-xs text-gray-400">{p.key === 'custom' ? t('settings.customConfig') : t('settings.presetApi')}</div>
                </button>
              ))}
            </div>
          </div>

          {/* API Key */}
          <div>
            <div className="mb-2 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.apiKey')}</span>
              <InfoTooltip text={t('settings.apiKeyTooltip')} />
              {PROVIDERS.find((p) => p.key === provider)?.helpUrl && (
                <a href={PROVIDERS.find((p) => p.key === provider)!.helpUrl} target="_blank" className="ml-auto text-xs font-bold text-blue-500 hover:underline">{t('settings.howToGet')}</a>
              )}
            </div>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..."
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 pr-12 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
              <button type="button" onClick={() => setShowApiKey((v) => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-gray-400 hover:bg-gray-100">
                {showApiKey ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          {/* Base URL */}
          <div>
            <div className="mb-2 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.baseUrl')}</span>
              <InfoTooltip text={t('settings.baseUrlTooltip')} />
            </div>
            <input
              type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              disabled={provider === 'deepseek'}
              className={`w-full rounded-2xl border border-gray-200 px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50 ${provider === 'deepseek' ? 'bg-gray-100 text-gray-500' : 'bg-white'}`}
            />
          </div>

          {/* Model */}
          <div>
            <div className="mb-2 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.model')}</span>
              <InfoTooltip text={t('settings.modelTooltip')} />
            </div>
            {providerModels.length > 0 ? (
              <select
                value={model} onChange={(e) => setModel(e.target.value)}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              >
                {providerModels.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <input
                type="text" value={model} onChange={(e) => setModel(e.target.value)}
                placeholder={t('settings.modelPlaceholder')}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            )}
          </div>

          {/* Direct Remote Upload Toggle */}
          <div className="rounded-2xl border border-amber-100 bg-amber-50/60 p-5 space-y-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h4 className="text-sm font-black text-amber-800">📤 直接上传资源至远程API解析</h4>
                <p className="mt-1 text-xs text-amber-600/80">模型下载失败时，跳过本地解析，将资源文件直接发送给远程 API 进行知识点提取（需要已配置 API Key）</p>
              </div>
              <button
                type="button"
                onClick={() => setSkipLocalParsing(v => !v)}
                className={`relative shrink-0 h-7 w-12 rounded-full transition-colors ${skipLocalParsing ? 'bg-amber-500' : 'bg-gray-300'}`}
              >
                <span className={`absolute top-0.5 left-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform ${skipLocalParsing ? 'translate-x-5' : ''}`}></span>
              </button>
            </div>
            {skipLocalParsing && !apiKey.trim() && (
              <p className="text-xs text-red-600 font-semibold">⚠ 请先在上方配置 API Key，否则上传后解析会失败</p>
            )}
            {skipLocalParsing && (
              <p className="text-xs text-amber-700">已开启：上传资源时将跳过本地 MinerU/OCR 解析，直接使用远程 API 提取知识点</p>
            )}
          </div>

          {/* Test Connection */}
          <button
            type="button"
            onClick={testConnection}
            className="rounded-xl bg-blue-500 px-5 py-2.5 text-sm font-bold text-gray-900 shadow-lg shadow-blue-200 transition-colors hover:bg-blue-600"
          >
            {testResult || t('settings.testConnection')}
          </button>
        </div>
      )}

      {/* ===== Local Model Settings ===== */}
      {mode === 'local' && (
        <div className="space-y-5">
          {/* GPU Info */}
          <div className="rounded-2xl border border-gray-200 bg-white p-5">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.gpuDetection')}</span>
                <InfoTooltip text={t('settings.gpuDetectionTooltip')} />
              </div>
              <button
                type="button" onClick={detectGPU} disabled={gpuLoading}
                className="rounded-lg bg-gray-100 px-3 py-1 text-xs font-bold text-gray-600 hover:bg-gray-200 disabled:opacity-50"
              >
                {t('settings.reDetect')}
              </button>
            </div>
            {gpu && gpu.cuda_available ? (
              <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
                <div><span className="text-gray-400">{t('settings.device')}</span><div className="font-bold text-gray-800">{gpu.gpu_name}</div></div>
                <div><span className="text-gray-400">{t('settings.totalVram')}</span><div className="font-bold text-gray-800">{gpu.vram_total_gb} GB</div></div>
                <div><span className="text-gray-400">{t('settings.available')}</span><div className="font-bold text-gray-800">{gpu.vram_free_gb} GB</div></div>
              </div>
            ) : gpuLoading ? (
              <p className="mt-3 text-sm text-gray-400">{t('settings.detecting')}</p>
            ) : (
              <p className="mt-3 text-sm text-gray-400">{t('settings.noGpu')}</p>
            )}
          </div>

          {/* Recommended */}
          {recommended && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm">
              <span className="font-bold text-amber-700">{t('settings.recommendedModel')}: </span>
              <span className="text-amber-600">{recommended.label}{t('settings.recommendedVramDesc', { vram: recommended.vram, gpu: recommended.gpu })}</span>
            </div>
          )}

          {/* Select downloaded model to use */}
          <div>
            <div className="mb-2 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.selectModel')}</span>
              <InfoTooltip text={t('settings.selectModelTooltip')} />
            </div>
            <select
              value={localModel}
              onChange={(e) => {
                const selectedModel = e.target.value;
                setLocalModel(selectedModel);
                setLocalPath(modelPaths[selectedModel] || '');
              }}
              className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
            >
              <option value="">{t('settings.unselected')}</option>
              {Object.entries(downloadStates).filter(([, ds]) => ds.status === 'done').map(([key]) => {
                const m = models.find((mod) => mod.key === key);
                if (!m) return null;
                const ctx = m.context_limit ? ` (${parseInt(m.context_limit) >= 1000 ? `${(parseInt(m.context_limit)/1000).toFixed(0)}K` : m.context_limit})` : '';
                return <option key={key} value={key}>{m.label}{ctx}</option>;
              })}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.precision')}</span>
                <InfoTooltip text={t('settings.precisionTooltip')} />
              </div>
              <select value={dtype} onChange={(e) => setDtype(e.target.value)}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50">
                <option value="bf16">bf16</option>
                <option value="fp16">fp16</option>
                <option value="fp32">fp32</option>
                <option value="auto">auto</option>
              </select>
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.maxTokens')}</span>
                <InfoTooltip text={t('settings.maxTokensTooltip')} />
              </div>
              <input
                type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.temperature')} ({temp})</span>
                <InfoTooltip text={t('settings.temperatureTooltip')} />
              </div>
              <input type="range" min="0" max="2" step="0.05" value={temp} onChange={(e) => setTemp(Number(e.target.value))} className="w-full accent-blue-500" />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.localPort')}</span>
                <InfoTooltip text={t('settings.localPortTooltip')} />
              </div>
              <input
                type="number" value={localPort} onChange={(e) => setLocalPort(Number(e.target.value) || 8000)}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.timeout')}</span>
                <InfoTooltip text={t('settings.timeoutTooltip')} />
              </div>
              <input
                type="number" value={timeoutSec} onChange={(e) => setTimeoutSec(Number(e.target.value))}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            </div>
          </div>

          {/* ===== Model Download Cards ===== */}
          <div className="mb-6">
            <h3 className="mb-3 text-sm font-black uppercase tracking-[0.14em] text-gray-500">{t('settings.optionalModels')}</h3>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {models.map((m) => renderCard(m, false))}
              {models.length === 0 && (
                <div className="col-span-2 rounded-2xl border border-dashed border-gray-200 bg-gray-50 py-10 text-center text-sm text-gray-400">
                   {t('settings.loadingModels')}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      </div>

      {/* ===== Save Button ===== */}
      <div className="sticky bottom-0 border-t border-gray-100 bg-white/90 pt-6 backdrop-blur flex items-center gap-2">
        <span className="text-xs text-gray-400">{saving ? t('settings.saving') : t('settings.autoSaved')}</span>
        <span className="text-xs text-emerald-500">{saving ? '' : '✓'}</span>
      </div>

      {/* Confirm modal */}
      {confirmModal?.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/45 p-4 backdrop-blur-sm" onClick={() => setConfirmModal(null)}>
          <div className="w-full max-w-md overflow-hidden rounded-[32px] border border-white/70 bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="relative overflow-hidden bg-gradient-to-br from-pink-500 via-rose-400 to-orange-300 p-6 text-white">
              <div className="absolute -right-12 -top-16 h-44 w-44 rounded-full bg-white/20 blur-2xl"></div>
              <div className="relative flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.28em] text-white/75">{t('settings.confirmTitle')}</p>
                  <h2 className="mt-2 text-2xl font-black">{confirmModal.title}</h2>
                </div>
                <button type="button" onClick={() => setConfirmModal(null)} className="rounded-full bg-white/15 p-2 text-white transition-colors hover:bg-white/25" aria-label={t('settings.closeModal')}><X size={20} /></button>
              </div>
            </div>
            <div className="space-y-4 p-6">
              <div className="rounded-2xl border border-gray-100 bg-gray-50/80 p-4">
                <p className="whitespace-pre-wrap text-sm leading-6 text-gray-600">{confirmModal.message}</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-gray-100 bg-gray-50 px-6 py-4">
              <button onClick={() => setConfirmModal(null)} className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-bold text-gray-600 hover:bg-gray-100">{t('settings.cancel')}</button>
              <button onClick={confirmModal.onConfirm} className="rounded-xl bg-gray-900 px-5 py-2 text-sm font-black text-white shadow-lg shadow-gray-200 hover:bg-pink-600 transition-colors">{confirmModal.confirmText}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
