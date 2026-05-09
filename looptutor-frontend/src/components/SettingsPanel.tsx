import { useState, useEffect, useCallback, useRef } from 'react';
import { SettingsAPI } from '../api/client';

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
};

type DownloadState = {
  progress: number;
  status: string;
};

type Provider = {
  key: string;
  label: string;
  baseUrl: string;
  models: string[];
  helpUrl: string;
};

const PROVIDERS: Provider[] = [
  { key: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', models: ['deepseek-v4-flash', 'deepseek-v4-pro'], helpUrl: 'https://platform.deepseek.com/api_keys' },
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
  const [mode, setMode] = useState<'api' | 'local'>('api');
  const [provider, setProvider] = useState<string>('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [testResult, setTestResult] = useState('');
  const [gpu, setGpu] = useState<GPUInfo | null>(null);
  const [gpuLoading, setGpuLoading] = useState(false);
  const [localPath, setLocalPath] = useState('');
  const [dtype, setDtype] = useState('bfloat16');
  const [maxTokens, setMaxTokens] = useState(500);
  const [temp, setTemp] = useState(0.7);
  const [timeoutSec, setTimeoutSec] = useState(120);
  const [models, setModels] = useState<ModelDef[]>([]);
  const [modelPaths, setModelPaths] = useState<Record<string, string>>({});
  const [downloadStates, setDownloadStates] = useState<Record<string, DownloadState>>({});
  const [saving, setSaving] = useState(false);
  const intervalRefs = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    void loadSettings();
    void loadModels();
    void detectGPU();
  }, []);

  useEffect(() => {
    const active = Object.entries(intervalRefs.current);
    for (const [, id] of active) clearInterval(id);
    intervalRefs.current = {};

    for (const [key, state] of Object.entries(downloadStates)) {
      if (state.status === 'downloading') {
        intervalRefs.current[key] = setInterval(() => void pollDownload(key), 500);
      }
    }
    return () => {
      for (const id of Object.values(intervalRefs.current)) clearInterval(id);
    };
  }, [downloadStates]);

  async function loadSettings() {
    try {
      const res = await SettingsAPI.getSettings();
      const data = res.data;
      if (data.mode) setMode(data.mode);
      if (data.provider) setProvider(data.provider);
      if (data.remote) {
        setApiKey(data.remote.api_key || '');
        setBaseUrl(data.remote.base_url || '');
        setModel(data.remote.model || '');
        if (!data.remote.base_url && data.provider) {
          const prov = PROVIDERS.find((p) => p.key === data.provider);
          if (prov) setBaseUrl(prov.baseUrl);
        }
      }
      if (data.local) {
        setLocalPath(data.local.model_path || '');
        setDtype(data.local.precision || 'bfloat16');
        setMaxTokens(data.local.max_tokens || 500);
        setTemp(data.local.temperature != null ? data.local.temperature : 0.7);
        setTimeoutSec(data.local.timeout_sec || 120);
      }
    } catch { /* ignore */ }
  }

  async function detectGPU() {
    setGpuLoading(true);
    try {
      const res = await SettingsAPI.getGPU();
      setGpu(res.data);
    } catch {
      setGpu(null);
    } finally {
      setGpuLoading(false);
    }
  }

  async function testConnection() {
    setTestResult('检测中...');
    try {
      await SettingsAPI.getModels();
      setTestResult('✓ 连接成功');
    } catch {
      setTestResult('✗ 连接失败');
    }
  }

  function recommendedModel(): ModelDef | null {
    if (!gpu || !gpu.cuda_available) return null;
    const free = gpu.vram_free_gb || gpu.vram_total_gb;
    if (free >= 54) return models.find((m) => m.key === 'qwen-27b') || null;
    if (free >= 24) return models.find((m) => m.key === 'gemma-12b') || null;
    if (free >= 14) return models.find((m) => m.key === 'qwen-7b') || null;
    if (free >= 8) return models.find((m) => m.key === 'gemma-4b') || null;
    return models.find((m) => m.key === 'gemma-4b') || null;
  }

  async function loadModels() {
    try {
      const res = await SettingsAPI.getModels();
      const raw = res.data.models || {};
      const list: ModelDef[] = Object.entries(raw).map(([key, info]: [string, unknown]) => {
        const m = info as Record<string, string>;
        return {
          key, label: m.label || key, size: m.size || '', vram: m.vram || '',
          gpu: m.gpu || '', repo_id: m.repo_id || '', description: m.description || '',
        };
      });
      setModels(list);
      for (const def of list) void checkDownloadStatus(def.key);
    } catch { /* ignore */ }
  }

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
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { progress: prog, status } }));
    } catch { /* ignore */ }
  }

  async function pollDownload(modelKey: string) {
    try {
      const res = await SettingsAPI.getDownloadStatus(modelKey);
      if (!res.data) return;
      const prog = res.data.progress;
      let status = 'downloading';
      if (res.data.status === 'completed' || prog >= 100) status = 'done';
      else if (res.data.status === 'failed' || prog === -1) status = 'error';
      else if (res.data.status === 'cancelled') status = 'cancelled';
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { progress: prog, status } }));
      if (['done', 'error', 'cancelled'].includes(status) && intervalRefs.current[modelKey]) {
        clearInterval(intervalRefs.current[modelKey]);
        delete intervalRefs.current[modelKey];
      }
    } catch { /* ignore */ }
  }

  const handleProviderChange = useCallback((p: Provider) => {
    setProvider(p.key);
    setBaseUrl(p.baseUrl);
    setModel(p.models.length > 0 ? p.models[0] : '');
  }, []);

  const handleDownload = useCallback(async (modelKey: string) => {
    const path = modelPaths[modelKey]?.trim();
    if (!path) return alert('请填写下载路径');
    try {
      await SettingsAPI.downloadModel(modelKey, path);
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { progress: 0, status: 'downloading' } }));
    } catch (err: unknown) {
      alert('下载失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  }, [modelPaths]);

  const handlePause = useCallback(async (modelKey: string) => {
    try {
      await SettingsAPI.cancelDownload(modelKey);
      if (intervalRefs.current[modelKey]) { clearInterval(intervalRefs.current[modelKey]); delete intervalRefs.current[modelKey]; }
      setDownloadStates((prev) => ({ ...prev, [modelKey]: { ...(prev[modelKey] || { progress: 0, status: '' }), status: 'cancelled' } }));
    } catch { /* ignore */ }
  }, []);

  const handleCancel = useCallback(async (modelKey: string) => { await handlePause(modelKey); }, [handlePause]);

  const handleDelete = useCallback(async (modelKey: string) => {
    const path = modelPaths[modelKey]?.trim();
    if (!path) return alert('请填写路径');
    try {
      await SettingsAPI.deleteModel(modelKey);
      setDownloadStates((prev) => { const copy = { ...prev }; delete copy[modelKey]; return copy; });
    } catch (err: unknown) {
      alert('删除失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  }, [modelPaths]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await SettingsAPI.saveSettings({
        mode, provider,
        remote: { api_key: apiKey, base_url: baseUrl, model },
        local: { model_path: localPath, precision: dtype, max_tokens: maxTokens, temperature: temp, timeout_sec: timeoutSec },
      });
    } catch { /* ignore */ } finally { setSaving(false); }
  }, [mode, provider, apiKey, baseUrl, model, localPath, dtype, maxTokens, temp, timeoutSec]);

  const recommended = recommendedModel();
  const providerModels = PROVIDERS.find((p) => p.key === provider)?.models || [];

  return (
    <div className="bg-white/80 backdrop-blur rounded-[32px] p-8 shadow-sm space-y-10">
      <div>
        <h2 className="text-2xl font-black text-gray-800">系统设置</h2>
        <p className="mt-1 text-sm text-gray-400">配置 LLM 模型服务，管理本地模型下载。</p>
      </div>

      {/* ===== Mode Switch ===== */}
      <div className="grid grid-cols-2 gap-3">
        {(['api', 'local'] as const).map((m) => (
          <label
            key={m}
            className={`relative cursor-pointer rounded-2xl border-2 p-5 transition-all ${mode === m ? 'border-blue-400 bg-blue-50/50 shadow-md ring-4 ring-blue-100' : 'border-gray-200 bg-white'}`}
          >
            <input type="radio" name="mode" checked={mode === m} onChange={() => setMode(m)} className="sr-only" />
            <div className="text-sm font-black text-gray-800">{m === 'api' ? '远程 API' : '本地模型'}</div>
            <div className="mt-1 text-xs text-gray-400">{m === 'api' ? '通过 API Key 连接到云端模型服务' : '在本地 GPU 上运行开源模型'}</div>
          </label>
        ))}
      </div>

      {/* ===== Remote API Settings ===== */}
      {mode === 'api' && (
        <div className="space-y-6">
          {/* Provider Selection Cards */}
          <div>
            <div className="mb-3 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">供应商选择</span>
              <InfoTooltip text="选择已预设的 API 供应商，或使用自定义 Base URL" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              {PROVIDERS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => handleProviderChange(p)}
                  className={`rounded-2xl border-2 p-4 text-left transition-all ${provider === p.key ? 'border-blue-400 bg-blue-50/50 shadow-md ring-4 ring-blue-100' : 'border-gray-200 bg-white hover:border-gray-300'}`}
                >
                  <div className="text-sm font-black text-gray-800">{p.label}</div>
                  <div className="mt-1 text-xs text-gray-400">{p.key === 'custom' ? '手动填写配置' : '预设 API'}</div>
                </button>
              ))}
            </div>
          </div>

          {/* API Key */}
          <div>
            <div className="mb-2 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">API Key</span>
              <InfoTooltip text="用于身份认证的密钥，在供应商网站获取" />
              {PROVIDERS.find((p) => p.key === provider)?.helpUrl && (
                <a href={PROVIDERS.find((p) => p.key === provider)!.helpUrl} target="_blank" className="ml-auto text-xs font-bold text-blue-500 hover:underline">如何获取？</a>
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
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">Base URL</span>
              <InfoTooltip text="API 服务地址，DeepSeek 等预设供应商自动填写" />
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
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">Model</span>
              <InfoTooltip text="模型名称，DeepSeek 预设可选 deepseek-v4-flash 和 deepseek-v4-pro" />
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
                placeholder="例如 gpt-4o"
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            )}
          </div>

          {/* Test Connection */}
          <button
            type="button"
            onClick={testConnection}
            className="rounded-xl bg-blue-500 px-5 py-2.5 text-sm font-bold text-gray-900 shadow-lg shadow-blue-200 transition-colors hover:bg-blue-600"
          >
            {testResult || '测试连接'}
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
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">GPU 检测结果</span>
                <InfoTooltip text="检测到的显卡设备。模型加载使用普通 GPU 内存，非专用显存" />
              </div>
              <button
                type="button" onClick={detectGPU} disabled={gpuLoading}
                className="rounded-lg bg-gray-100 px-3 py-1 text-xs font-bold text-gray-600 hover:bg-gray-200 disabled:opacity-50"
              >
                重新检测
              </button>
            </div>
            {gpu && gpu.cuda_available ? (
              <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
                <div><span className="text-gray-400">设备</span><div className="font-bold text-gray-800">{gpu.gpu_name}</div></div>
                <div><span className="text-gray-400">总显存</span><div className="font-bold text-gray-800">{gpu.vram_total_gb} GB</div></div>
                <div><span className="text-gray-400">可用</span><div className="font-bold text-gray-800">{gpu.vram_free_gb} GB</div></div>
              </div>
            ) : gpuLoading ? (
              <p className="mt-3 text-sm text-gray-400">检测中...</p>
            ) : (
              <p className="mt-3 text-sm text-gray-400">未检测到可用 GPU</p>
            )}
          </div>

          {/* Recommended */}
          {recommended && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm">
              <span className="font-bold text-amber-700">推荐模型: </span>
              <span className="text-amber-600">{recommended.label}（需 {recommended.vram} 显存，建议 {recommended.gpu}）</span>
            </div>
          )}

          {/* Local Settings Fields */}
          <div>
            <div className="mb-2 flex items-center gap-1">
              <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">模型路径</span>
              <InfoTooltip text="本地模型的文件夹绝对路径（如 D:\Models\gemma-3-4b），首次使用需下载" />
            </div>
            <input
              type="text" value={localPath} onChange={(e) => setLocalPath(e.target.value)}
              placeholder="D:\Models\gemma-3-4b"
              className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">精度</span>
                <InfoTooltip text="bfloat16 推荐用于 RTX 30 系列及以上，8bit 可降低显存但可能影响输出质量" />
              </div>
              <select value={dtype} onChange={(e) => setDtype(e.target.value)}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50">
                <option value="bfloat16">bfloat16</option>
                <option value="float16">float16</option>
                <option value="8bit">8bit</option>
                <option value="4bit">4bit</option>
              </select>
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">最大 Token</span>
                <InfoTooltip text="每次推理最大输出的 token 数量，越大回答越详细但越慢" />
              </div>
              <input
                type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">温度 ({temp})</span>
                <InfoTooltip text="0=确定性输出，1=更随机有创意，推荐 0.7" />
              </div>
              <input type="range" min="0" max="2" step="0.05" value={temp} onChange={(e) => setTemp(Number(e.target.value))} className="w-full accent-blue-500" />
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1">
                <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">超时 (秒)</span>
                <InfoTooltip text="单次模型调用最大等待时间，超时则返回错误" />
              </div>
              <input
                type="number" value={timeoutSec} onChange={(e) => setTimeoutSec(Number(e.target.value))}
                className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold outline-none transition-all focus:border-blue-300 focus:ring-4 focus:ring-blue-50"
              />
            </div>
          </div>

          {/* ===== Model Download Cards (local only) ===== */}
          <div>
            <h3 className="mb-5 mt-6 text-sm font-black uppercase tracking-[0.14em] text-gray-500">模型下载</h3>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {models.map((m) => {
                const ds = downloadStates[m.key];
                const isDownloading = ds?.status === 'downloading';
                const isDone = ds?.status === 'done';
                const isError = ds?.status === 'error';
                const progress = ds?.progress || 0;
                const vramGB = parseFloat(m.vram) || 0;
                const gpuVramOK = gpu && gpu.vram_total_gb >= vramGB;

                return (
                  <div key={m.key} className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div>
                        <h4 className="text-base font-black text-gray-800">{m.label}</h4>
                        <p className="mt-1 text-xs text-gray-400">{m.description}</p>
                      </div>
                      {isDownloading && <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-black text-blue-600">下载中</span>}
                      {isDone && <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-black text-emerald-600">已下载</span>}
                      {isError && <span className="rounded-full bg-rose-50 px-2.5 py-0.5 text-xs font-black text-rose-600">失败</span>}
                      {!isDownloading && !isDone && !isError && !gpuVramOK && gpu && <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-black text-amber-600">显存不足</span>}
                    </div>

                    <div className="mb-3 grid grid-cols-2 gap-1 text-xs text-gray-400">
                      <span>文件大小: <strong className="text-gray-700">{m.size}</strong></span>
                      <span>显存需求: <strong className="text-gray-700">{m.vram}</strong></span>
                      <span className="col-span-2">推荐显卡: <strong className="text-gray-700">{m.gpu}</strong></span>
                    </div>

                    {/* Download path */}
                    <div className="mb-3">
                      <input
                        type="text" value={modelPaths[m.key] || ''}
                        onChange={(e) => setModelPaths((prev) => ({ ...prev, [m.key]: e.target.value }))}
                        placeholder="D:\Models\gemma-3-4b"
                        className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-semibold outline-none transition-all focus:border-blue-300 focus:bg-white"
                      />
                    </div>
                    <div className="mb-2 flex items-center gap-1">
                      <span className="text-xs font-black uppercase tracking-[0.14em] text-gray-500">下载路径</span>
                      <InfoTooltip text="模型文件存放位置。已下载的模型可通过选择已有文件夹直接使用" />
                    </div>

                    {/* Progress bar */}
                    <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden mb-1">
                      <div
                        className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-500 ease-out"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    <span className="text-sm text-gray-500">
                      {isDownloading ? `${Math.round(progress)}%` : isDone ? '已完成 ✓' : isError ? '下载失败 ✗' : ds?.status === 'cancelled' ? '已取消' : '等待下载'}
                    </span>

                    <div className="mt-3 flex flex-wrap justify-end gap-2">
                      {isDownloading ? (
                        <>
                          <button onClick={() => handlePause(m.key)} className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-bold text-gray-600 hover:bg-gray-200">暂停</button>
                          <button onClick={() => handleCancel(m.key)} className="rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-100">取消</button>
                        </>
                      ) : isDone ? (
                        <button onClick={() => handleDelete(m.key)} className="rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-100">删除</button>
                      ) : (
                        <button onClick={() => handleDownload(m.key)} className="rounded-lg bg-blue-500 px-4 py-1.5 text-xs font-bold text-gray-900 hover:bg-blue-600">下载</button>
                      )}
                    </div>
                  </div>
                );
              })}
              {models.length === 0 && (
                <div className="col-span-2 rounded-2xl border border-dashed border-gray-200 bg-gray-50 py-10 text-center text-sm text-gray-400">
                  加载模型列表中...
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ===== Save Button ===== */}
      <div className="sticky bottom-0 border-t border-gray-100 bg-white/90 pt-6 backdrop-blur">
        <button
          type="button" onClick={handleSave} disabled={saving}
          className="w-full rounded-2xl bg-gray-900 py-3.5 text-base font-black text-white shadow-lg shadow-gray-200 transition-colors hover:bg-pink-600 disabled:opacity-50"
        >
          {saving ? '保存中...' : '保存设置'}
        </button>
      </div>
    </div>
  );
}
