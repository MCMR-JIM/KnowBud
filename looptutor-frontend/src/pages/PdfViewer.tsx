import { useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ZoomIn, ZoomOut, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';

// 🌟 关键：使用稳定的 CDN 载入 Worker，解决 Vite 环境下的 getOrInsertComputed 报错
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

  function onDocumentLoadSuccess({ numPages }: { numPages: number }) {
    setNumPages(numPages);
    // 首次加载完成，触发第一页的知识点获取
    if (onRenderComplete) {
      onRenderComplete(1);
    }
  }

  const changePage = (offset: number) => {
    // 直接计算新页码并设置，不使用回调
    const newPage = pageNumber + offset;
    setPageNumber(newPage);

    // 仅在点击翻页时触发请求
    if (onRenderComplete) {
      onRenderComplete(newPage);
    }
  };



  return (
    <div className="flex flex-col items-center w-full h-full bg-white/40 rounded-2xl p-4 overflow-hidden">
      {/* 顶栏控件 */}
      <div className="flex items-center justify-between w-full bg-white/80 backdrop-blur-sm px-4 py-2 rounded-xl mb-4 shadow-sm border border-white/50 z-20">
        <div className="flex gap-2">
          <button onClick={() => setScale(s => Math.max(0.5, s - 0.2))} className="p-2 bg-white text-gray-600 rounded-lg hover:bg-gray-100 shadow-sm transition-colors cursor-pointer"><ZoomOut size={18} /></button>
          <button onClick={() => setScale(s => Math.min(2.5, s + 0.2))} className="p-2 bg-white text-gray-600 rounded-lg hover:bg-gray-100 shadow-sm transition-colors cursor-pointer"><ZoomIn size={18} /></button>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={() => changePage(-1)}
            disabled={pageNumber <= 1}
            className="p-2 bg-white text-gray-600 rounded-lg hover:bg-gray-100 disabled:opacity-30 shadow-sm cursor-pointer"
          ><ChevronLeft size={18} /></button>
          <span className="text-sm font-bold text-gray-700 select-none">
            {pageNumber} <span className="text-gray-400">/</span> {numPages || '-'}
          </span>
          <button
            onClick={() => changePage(1)}
            disabled={pageNumber >= numPages}
            className="p-2 bg-white text-gray-600 rounded-lg hover:bg-gray-100 disabled:opacity-30 shadow-sm cursor-pointer"
          ><ChevronRight size={18} /></button>
        </div>
      </div>

      {/* PDF 内容区 */}
      <div className="flex-1 w-full overflow-auto flex justify-center items-start rounded-xl bg-gray-50/50 border border-white/40 relative custom-scrollbar">
        <Document
          file={url}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={
            <div className="flex flex-col items-center mt-20">
              <Loader2 className="animate-spin text-blue-500 mb-2" size={40} />
              <span className="text-gray-500 font-medium">召唤知识卷轴中...</span>
            </div>
          }
          error={<div className="text-red-500 mt-20">哎呀，卷轴打不开了</div>}
        >
          <Page 
            pageNumber={pageNumber} 
            scale={scale} 
            renderTextLayer={true}
            renderAnnotationLayer={false}
            loading=""
            className="shadow-2xl border border-gray-200 my-4"
          />
        </Document>
      </div>
    </div>
  );
}
