import { useState, useRef, useEffect, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ZoomIn, ZoomOut, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

interface PdfViewerProps {
  url: string;
  onRenderComplete?: (currentPage: number) => void;
}

export default function PdfViewer({ url, onRenderComplete }: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [scale, setScale] = useState<number>(1.0);

  const containerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

  const onResize = useCallback(() => {
    if (containerRef.current) {
      setContainerSize({
        width: containerRef.current.clientWidth - 40, // 留出呼吸边距
        height: containerRef.current.clientHeight - 80, // 上下留出充足空间给指示器
      });
    }
  }, []);

  useEffect(() => {
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [onResize]);

  function onDocumentLoadSuccess({ numPages }: { numPages: number }) {
    setNumPages(numPages);
    if (onRenderComplete) {
      onRenderComplete(1);
    }
  }

  const changePage = (offset: number) => {
    const newPage = pageNumber + offset;
    setPageNumber(newPage);
    if (onRenderComplete) {
      onRenderComplete(newPage);
    }
  };

  return (
    <div className="relative flex flex-col items-center w-full h-full bg-transparent rounded-3xl overflow-hidden group">
      
     {/* 🌟 悬浮：右上角童趣放大缩小控制 */}
      <div className="absolute top-6 right-6 z-30 flex gap-4 opacity-90 hover:opacity-100 transition-opacity">
        <button 
          onClick={() => setScale(s => Math.max(0.5, s - 0.2))} 
          className="w-14 h-14 bg-white/95 text-blue-500 rounded-full shadow-lg border-4 border-blue-100 flex items-center justify-center hover:bg-blue-500 hover:text-white hover:scale-110 active:scale-90 transition-all cursor-pointer"
          title="变小一点"
        >
          <ZoomOut size={32} strokeWidth={3} />
        </button>
        <button 
          onClick={() => setScale(s => Math.min(2.5, s + 0.2))} 
          className="w-14 h-14 bg-white/95 text-orange-500 rounded-full shadow-lg border-4 border-orange-100 flex items-center justify-center hover:bg-orange-500 hover:text-white hover:scale-110 active:scale-90 transition-all cursor-pointer"
          title="变大一点"
        >
          <ZoomIn size={32} strokeWidth={3} />
        </button>
      </div>
      {/* 🌟 悬浮：左侧超大翻页按钮 */}
      <button 
        onClick={() => changePage(-1)} 
        disabled={pageNumber <= 1} 
        className="absolute left-6 top-1/2 -translate-y-1/2 z-30 w-20 h-20 bg-white/95 rounded-full shadow-[0_8px_30px_rgba(0,0,0,0.12)] flex items-center justify-center text-gray-400 hover:text-orange-500 hover:scale-110 disabled:opacity-0 transition-all cursor-pointer border border-gray-50"
      >
        <ChevronLeft size={48} strokeWidth={3} />
      </button>

      {/* 🌟 悬浮：右侧超大翻页按钮 */}
      <button 
        onClick={() => changePage(1)} 
        disabled={pageNumber >= numPages} 
        className="absolute right-6 top-1/2 -translate-y-1/2 z-30 w-20 h-20 bg-white/95 rounded-full shadow-[0_8px_30px_rgba(0,0,0,0.12)] flex items-center justify-center text-gray-400 hover:text-orange-500 hover:scale-110 disabled:opacity-0 transition-all cursor-pointer border border-gray-50"
      >
        <ChevronRight size={48} strokeWidth={3} />
      </button>

      {/* PDF 内容区 (加上了柔和的投影和圆角) */}
      <div 
        ref={containerRef}
        className="flex-1 w-full h-full flex justify-center items-center relative z-10"
      >
        <Document
          file={url}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={<div className="flex flex-col items-center"><Loader2 className="animate-spin text-orange-400 mb-4" size={64} /><span className="text-orange-500 font-bold text-2xl">正在召唤知识卷轴...</span></div>}
          error={<div className="flex flex-col items-center text-red-500 bg-red-50 p-8 rounded-3xl border border-red-100"><span className="text-6xl mb-4">📄</span><span className="font-bold text-2xl">卷轴打开失败</span></div>}
        >
          <Page 
            pageNumber={pageNumber} 
            scale={scale} 
            height={containerSize.height > 0 ? containerSize.height : undefined} 
            renderTextLayer={true}
            renderAnnotationLayer={false}
            loading={<div className="flex justify-center p-10"><Loader2 className="animate-spin text-gray-400" size={48} /></div>}
            className="shadow-[0_16px_40px_rgba(0,0,0,0.1)] rounded-[16px] overflow-hidden border border-gray-100"
          />
        </Document>
      </div>

      {/* 🌟 底部中央：童趣点点进度指示器 */}
      {numPages > 0 && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-4 bg-white/90 backdrop-blur-md px-8 py-4 rounded-full shadow-lg border border-gray-100 transition-all">
          {Array.from({ length: numPages }).map((_, i) => (
            <div 
              key={i} 
              className={`rounded-full transition-all duration-300 ${
                pageNumber === i + 1 
                  ? 'w-6 h-6 bg-orange-500 shadow-[0_0_15px_rgba(249,115,22,0.6)]' 
                  : 'w-4 h-4 bg-gray-200'
              }`} 
            />
          ))}
        </div>
      )}
    </div>
  );
}