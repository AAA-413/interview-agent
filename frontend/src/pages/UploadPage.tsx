import { useState, useCallback } from 'react';
import { Upload, FileText, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { resumeApi } from '../api/resume';
import type { ResumeDetailDTO } from '../types/resume';

interface UploadPageProps {
  onUploadComplete?: (resumeId: number) => void;
}

export default function UploadPage({ onUploadComplete }: UploadPageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ResumeDetailDTO | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleUpload = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setError('');
    setResult(null);
    try {
      const detail = await resumeApi.uploadResume(file);
      setResult(detail);
      onUploadComplete?.(detail.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
    }
  }, [file, onUploadComplete]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      const ext = droppedFile.name.split('.').pop()?.toLowerCase();
      if (['pdf', 'docx', 'doc', 'txt'].includes(ext || '')) {
        setFile(droppedFile);
        setError('');
      } else {
        setError('仅支持 PDF、DOCX、DOC、TXT 格式');
      }
    }
  }, []);

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">上传简历</h1>
        <p className="text-slate-500 mt-2">上传简历文件，AI 将自动解析并分析简历内容</p>
      </div>

      <div
        className={`relative border-2 border-dashed rounded-2xl p-12 text-center transition-all duration-200 ${
          dragOver
            ? 'border-primary-400 bg-primary-50'
            : 'border-slate-200 hover:border-primary-300 hover:bg-slate-50'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <Upload className={`w-12 h-12 mx-auto mb-4 ${dragOver ? 'text-primary-500' : 'text-slate-300'}`} />
        <p className="text-slate-600 font-medium">拖拽文件到此处，或点击选择文件</p>
        <p className="text-slate-400 text-sm mt-2">支持 PDF、DOCX、DOC、TXT 格式</p>
        <input
          type="file"
          accept=".pdf,.docx,.doc,.txt"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) { setFile(f); setError(''); }
          }}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
      </div>

      {file && (
        <div className="mt-4 flex items-center gap-3 p-4 bg-slate-50 rounded-xl">
          <FileText className="w-5 h-5 text-primary-500" />
          <span className="text-sm text-slate-700 flex-1 truncate">{file.name}</span>
          <span className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</span>
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {result && (
        <div className="mt-4 flex items-center gap-2 p-4 bg-green-50 text-green-700 rounded-xl">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">简历上传成功！ID: {result.id}，正在分析中...</span>
        </div>
      )}

      <button
        onClick={handleUpload}
        disabled={!file || uploading}
        className={`mt-6 w-full py-3 rounded-xl font-medium text-white transition-all duration-200 ${
          !file || uploading
            ? 'bg-slate-300 cursor-not-allowed'
            : 'bg-gradient-to-r from-primary-600 to-primary-500 hover:from-primary-700 hover:to-primary-600 shadow-lg shadow-primary-500/25'
        }`}
      >
        {uploading ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            上传中...
          </span>
        ) : (
          '开始上传'
        )}
      </button>
    </div>
  );
}
