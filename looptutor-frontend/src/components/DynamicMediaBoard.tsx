import { Volume2 } from 'lucide-react';

interface MediaBoardProps {
  type: 'video' | 'iframe' | 'whiteboard';
  url?: string;
}

export default function DynamicMediaBoard({ type, url }: MediaBoardProps) {
  return (
    <div className="w-full flex-1 bg-black/5 rounded-2xl overflow-hidden flex flex-col border-2 border-white/80 relative">
      {/* 1. 视频模式 */}
      {type === 'video' && url && (
        <video className="w-full h-full object-cover" controls src={url} />
      )}

      {/* 2. iframe 模式 (用于 PPT 或 H5 课件互动) */}
      {type === 'iframe' && url && (
        <iframe 
          src={url} 
          className="w-full h-full border-0" 
          allow="autoplay; encrypted-media" 
          title="AI Courseware"
        />
      )}

      {/* 3. 白板模式 (预留 Canvas 接口) */}
      {type === 'whiteboard' && (
        <div className="relative w-full h-full bg-white">
          <canvas id="ai-whiteboard" className="w-full h-full touch-none" />
          <div className="absolute inset-0 flex items-center justify-center text-gray-400 pointer-events-none text-sm">
            大模型老师正在准备白板...
          </div>
        </div>
      )}

      {/* 兜底状态：无资源时显示 */}
      {!url && type !== 'whiteboard' && (
        <div className="flex-1 flex items-center justify-center text-gray-400 p-10 text-center text-sm">
          等待老师分享学习资源...
        </div>
      )}
    </div>
  );
}