import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  BookOpen,
  ChevronRight,
  Database,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
  Link as LinkIcon,
  Sparkles,
} from 'lucide-react';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import type { AsyncTaskStatus, KnowledgeBaseListItemDTO } from '../types/knowledgeBase';

const statusMap: Record<AsyncTaskStatus, { label: string; color: string; bgColor: string; icon: string }> = {
  PENDING: { label: '待索引', color: 'text-amber-700', bgColor: 'bg-amber-50 border-amber-200', icon: '⏳' },
  PROCESSING: { label: '索引中', color: 'text-blue-700', bgColor: 'bg-blue-50 border-blue-200', icon: '⚡' },
  COMPLETED: { label: '已完成', color: 'text-emerald-700', bgColor: 'bg-emerald-50 border-emerald-200', icon: '✓' },
  FAILED: { label: '失败', color: 'text-red-700', bgColor: 'bg-red-50 border-red-200', icon: '✕' },
};

const processingStatuses = new Set<AsyncTaskStatus>(['PENDING', 'PROCESSING']);

export default function KnowledgeBaseListPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<KnowledgeBaseListItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchList = async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
    }
    try {
      const data = await knowledgeBaseApi.listKnowledgeBases();
      setItems(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    void fetchList(true);
  }, []);

  useEffect(() => {
    if (!items.some(item => processingStatuses.has(item.index_status))) {
      return;
    }

    const timer = window.setInterval(() => {
      void fetchList(false);
    }, 3000);

    return () => window.clearInterval(timer);
  }, [items]);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个知识库吗？')) return;
    try {
      await knowledgeBaseApi.deleteKnowledgeBase(id);
      setItems(prev => prev.filter(item => item.id !== id));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleReindex = async (id: number) => {
    try {
      await knowledgeBaseApi.reindexKnowledgeBase(id);
      await fetchList(false);
      alert('已提交重新索引请求');
    } catch (err) {
      alert(err instanceof Error ? err.message : '重新索引失败');
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh]">
        <div className="relative">
          <Loader2 className="w-12 h-12 text-primary-500 animate-spin" />
          <div className="absolute inset-0 w-12 h-12 bg-primary-500/20 rounded-full animate-ping" />
        </div>
        <p className="mt-4 text-sm text-slate-500 animate-pulse">加载知识库...</p>
      </div>
    );
  }

  return (
    <div className="animate-in fade-in duration-500">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-slate-900 via-slate-800 to-slate-700 bg-clip-text text-transparent">
            知识库管理
          </h1>
          <div className="flex items-center gap-2 mt-2">
            <div className="flex items-center gap-1.5 px-3 py-1 bg-primary-50 rounded-full">
              <Database className="w-3.5 h-3.5 text-primary-600" />
              <span className="text-sm font-medium text-primary-700">{items.length} 个知识库</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1 bg-emerald-50 rounded-full">
              <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
              <span className="text-sm font-medium text-emerald-700">
                {items.filter(i => i.index_status === 'COMPLETED').length} 已就绪
              </span>
            </div>
          </div>
        </div>
        <button
          onClick={() => navigate('/knowledgebases/upload')}
          className="group relative px-6 py-3 bg-gradient-to-r from-primary-600 via-primary-500 to-indigo-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/30 hover:shadow-xl hover:shadow-primary-500/40 transition-all duration-300 hover:scale-105"
        >
          <div className="absolute inset-0 bg-gradient-to-r from-white/20 to-transparent rounded-xl opacity-0 group-hover:opacity-100 transition-opacity" />
          <div className="relative flex items-center gap-2">
            <Upload className="w-4 h-4" />
            上传文档
          </div>
        </button>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-3 p-4 bg-red-50 border border-red-100 text-red-600 rounded-xl shadow-sm animate-in slide-in-from-top duration-300">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm flex-1">{error}</span>
          <button onClick={() => void fetchList(true)} className="text-sm font-medium underline hover:no-underline">重试</button>
        </div>
      )}

      {items.length === 0 ? (
        <div className="text-center py-24 bg-white/60 backdrop-blur-sm rounded-2xl border border-slate-200/60 shadow-xl animate-in zoom-in duration-500">
          <div className="relative inline-block">
            <Database className="w-20 h-20 text-slate-200 mx-auto mb-6" />
            <div className="absolute -top-2 -right-2 w-8 h-8 bg-gradient-to-br from-primary-500 to-indigo-500 rounded-full flex items-center justify-center shadow-lg">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
          </div>
          <h3 className="text-xl font-semibold text-slate-700 mb-2">还没有知识库</h3>
          <p className="text-slate-400 text-sm mb-6">上传文档后即可进行 RAG 智能问答</p>
          <button
            onClick={() => navigate('/knowledgebases/upload')}
            className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-primary-500 to-indigo-500 text-white rounded-xl font-medium hover:shadow-lg hover:scale-105 transition-all duration-300"
          >
            <Upload className="w-4 h-4" /> 上传第一个文档
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {items.map((item, index) => {
            const status = statusMap[item.index_status] || statusMap.PENDING;
            return (
              <div
                key={item.id}
                className="group bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 hover:shadow-xl hover:border-primary-200/60 transition-all duration-300 cursor-pointer animate-in slide-in-from-bottom"
                style={{ animationDelay: `${index * 50}ms` }}
                onClick={() => navigate(`/knowledgebases/${item.id}`)}
              >
                <div className="flex items-start gap-5">
                  <div className="relative w-14 h-14 bg-gradient-to-br from-primary-50 to-indigo-50 rounded-2xl flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform duration-300">
                    <BookOpen className="w-7 h-7 text-primary-500" />
                    <div className="absolute -top-1 -right-1 w-5 h-5 bg-gradient-to-br from-emerald-400 to-teal-500 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-lg">
                      {item.chunk_count}
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-3 mb-2">
                      <h3 className="font-semibold text-slate-900 text-lg truncate flex-1 group-hover:text-primary-600 transition-colors">
                        {item.name}
                      </h3>
                      <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${status.bgColor} ${status.color}`}>
                        <span>{status.icon}</span>
                        <span>{status.label}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-slate-500 flex-wrap mb-3">
                      <span className="inline-flex items-center gap-1.5">
                        <FileText className="w-4 h-4" />
                        {item.filename}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <div className="w-1 h-1 bg-slate-300 rounded-full" />
                        {((item.file_size || 0) / 1024).toFixed(1)} KB
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <div className="w-1 h-1 bg-slate-300 rounded-full" />
                        {item.chunk_count} 个片段
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <div className="w-1 h-1 bg-slate-300 rounded-full" />
                        {new Date(item.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    {item.description && (
                      <p className="text-sm text-slate-600 line-clamp-2 leading-relaxed">{item.description}</p>
                    )}
                    {item.index_error && item.index_status === 'FAILED' && (
                      <div className="mt-3 flex items-start gap-2 p-3 bg-red-50 border border-red-100 rounded-lg">
                        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                        <p className="text-sm text-red-600 line-clamp-2">{item.index_error}</p>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => void handleReindex(item.id)}
                      className="p-2.5 text-slate-400 hover:text-primary-500 hover:bg-primary-50 rounded-xl transition-all duration-200"
                      title="重新索引"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => void handleDelete(item.id)}
                      className="p-2.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-xl transition-all duration-200"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-primary-500 group-hover:translate-x-1 transition-all duration-300" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
