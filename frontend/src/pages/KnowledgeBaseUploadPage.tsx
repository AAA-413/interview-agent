import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle2, FileText, Loader2, Upload } from 'lucide-react';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import type { KnowledgeBaseDetailDTO } from '../types/knowledgeBase';

export default function KnowledgeBaseUploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<KnowledgeBaseDetailDTO | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const validateAndSetFile = (selected: File) => {
    const ext = selected.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'docx', 'doc', 'txt', 'md', 'markdown'].includes(ext || '')) {
      setError('仅支持 PDF、DOCX、DOC、TXT、Markdown 格式');
      return;
    }
    setFile(selected);
    setError('');
    if (!name.trim()) {
      setName(selected.name.replace(/\.[^.]+$/, ''));
    }
  };

  const handleUpload = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setError('');
    setResult(null);
    try {
      const detail = await knowledgeBaseApi.uploadKnowledgeBase(file, {
        name: name.trim() || undefined,
        description: description.trim() || undefined,
      });
      setResult(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
    }
  }, [description, file, name]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      validateAndSetFile(droppedFile);
    }
  }, []);

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">上传知识库文档</h1>
          <p className="text-slate-500 mt-2">上传文档后将自动解析文本并异步建立索引</p>
        </div>
        <button onClick={() => navigate('/knowledgebases')} className="text-sm text-slate-500 hover:text-slate-700">
          返回列表
        </button>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 p-6 mb-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">知识库名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：FastAPI 项目文档"
            className="w-full px-4 py-3 rounded-xl border border-slate-200 outline-none focus:border-primary-400"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">描述</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述这个知识库的用途、内容范围或适用场景"
            rows={4}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 outline-none focus:border-primary-400 resize-none"
          />
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
          <p className="text-slate-600 font-medium">拖拽文档到此处，或点击选择文件</p>
          <p className="text-slate-400 text-sm mt-2">支持 PDF、DOCX、DOC、TXT、Markdown</p>
          <input
            type="file"
            accept=".pdf,.docx,.doc,.txt,.md,.markdown"
            onChange={(e) => {
              const selected = e.target.files?.[0];
              if (selected) {
                validateAndSetFile(selected);
              }
            }}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          />
        </div>

        {file && (
          <div className="flex items-center gap-3 p-4 bg-slate-50 rounded-xl">
            <FileText className="w-5 h-5 text-primary-500" />
            <span className="text-sm text-slate-700 flex-1 truncate">{file.name}</span>
            <span className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</span>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {result && (
          <div className="flex items-center gap-2 p-4 bg-green-50 text-green-700 rounded-xl">
            <CheckCircle2 className="w-5 h-5 flex-shrink-0" />
            <span className="text-sm">文档上传成功，正在异步建立索引。</span>
            <button
              onClick={() => navigate(`/knowledgebases/${result.id}`)}
              className="ml-auto text-sm underline"
            >
              查看详情
            </button>
          </div>
        )}

        <button
          onClick={() => void handleUpload()}
          disabled={!file || uploading}
          className={`w-full py-3 rounded-xl font-medium text-white transition-all duration-200 ${
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
            '开始上传并建立索引'
          )}
        </button>
      </div>
    </div>
  );
}
