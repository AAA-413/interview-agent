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
} from 'lucide-react';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import type { AsyncTaskStatus, KnowledgeBaseListItemDTO } from '../types/knowledgeBase';

const statusMap: Record<AsyncTaskStatus, { label: string; color: string }> = {
  PENDING: { label: '待索引', color: 'bg-yellow-100 text-yellow-700' },
  PROCESSING: { label: '索引中', color: 'bg-blue-100 text-blue-700' },
  COMPLETED: { label: '已完成', color: 'bg-green-100 text-green-700' },
  FAILED: { label: '失败', color: 'bg-red-100 text-red-700' },
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
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">知识库管理</h1>
          <p className="text-slate-500 mt-1">共 {items.length} 个知识库</p>
        </div>
        <button
          onClick={() => navigate('/knowledgebases/upload')}
          className="px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25 hover:from-primary-700 hover:to-primary-600 transition-all"
        >
          上传文档
        </button>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5" />
          <span className="text-sm">{error}</span>
          <button onClick={() => void fetchList(true)} className="ml-auto text-sm underline">重试</button>
        </div>
      )}

      {items.length === 0 ? (
        <div className="text-center py-20 bg-white rounded-2xl border border-slate-200">
          <Database className="w-16 h-16 text-slate-200 mx-auto mb-4" />
          <p className="text-slate-400 text-lg">暂无知识库</p>
          <p className="text-slate-300 text-sm mt-2">上传文档后即可进行 RAG 问答</p>
          <button
            onClick={() => navigate('/knowledgebases/upload')}
            className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 bg-primary-500 text-white rounded-xl hover:bg-primary-600"
          >
            <Upload className="w-4 h-4" /> 上传第一个文档
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const status = statusMap[item.index_status] || statusMap.PENDING;
            return (
              <div
                key={item.id}
                className="bg-white rounded-xl border border-slate-200 p-5 hover:shadow-md transition-all duration-200 cursor-pointer"
                onClick={() => navigate(`/knowledgebases/${item.id}`)}
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-primary-50 rounded-xl flex items-center justify-center flex-shrink-0">
                    <BookOpen className="w-6 h-6 text-primary-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <h3 className="font-medium text-slate-900 truncate">{item.name}</h3>
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                        {status.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 mt-1 text-sm text-slate-400 flex-wrap">
                      <span className="inline-flex items-center gap-1">
                        <FileText className="w-4 h-4" />
                        {item.filename}
                      </span>
                      <span>{((item.file_size || 0) / 1024).toFixed(1)} KB</span>
                      <span>{item.chunk_count} 个片段</span>
                      <span>{new Date(item.created_at).toLocaleDateString()}</span>
                    </div>
                    {item.description && (
                      <p className="mt-2 text-sm text-slate-500 line-clamp-1">{item.description}</p>
                    )}
                    {item.index_error && item.index_status === 'FAILED' && (
                      <p className="mt-2 text-sm text-red-500 line-clamp-1">错误：{item.index_error}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => void handleReindex(item.id)}
                      className="p-2 text-slate-400 hover:text-primary-500 rounded-lg hover:bg-slate-50"
                      title="重新索引"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => void handleDelete(item.id)}
                      className="p-2 text-slate-400 hover:text-red-500 rounded-lg hover:bg-slate-50"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-4 h-4 text-slate-300" />
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
