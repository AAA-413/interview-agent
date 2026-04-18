import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  Clock3,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import type {
  AsyncTaskStatus,
  KnowledgeBaseDetailDTO,
  RagAnswerDTO,
  RagReferenceDTO,
} from '../types/knowledgeBase';

const processingStatuses = new Set<AsyncTaskStatus>(['PENDING', 'PROCESSING']);
const statusMap: Record<AsyncTaskStatus, { label: string; color: string }> = {
  PENDING: { label: '待索引', color: 'bg-yellow-100 text-yellow-700' },
  PROCESSING: { label: '索引中', color: 'bg-blue-100 text-blue-700' },
  COMPLETED: { label: '已完成', color: 'bg-green-100 text-green-700' },
  FAILED: { label: '失败', color: 'bg-red-100 text-red-700' },
};

export default function KnowledgeBaseDetailPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<KnowledgeBaseDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [answer, setAnswer] = useState<RagAnswerDTO | null>(null);
  const [references, setReferences] = useState<RagReferenceDTO[]>([]);
  const [streamedAnswer, setStreamedAnswer] = useState('');
  const [answerSessionId, setAnswerSessionId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const numericKbId = useMemo(() => (kbId ? parseInt(kbId, 10) : null), [kbId]);

  const loadDetail = async (showLoading = false) => {
    if (!numericKbId) return;
    if (showLoading) {
      setLoading(true);
    }

    try {
      const data = await knowledgeBaseApi.getKnowledgeBase(numericKbId);
      setDetail(data);
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
    if (!numericKbId) return;
    void loadDetail(true);
  }, [numericKbId]);

  useEffect(() => {
    if (!detail || !processingStatuses.has(detail.index_status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void loadDetail(false);
    }, 3000);

    return () => window.clearInterval(timer);
  }, [detail?.index_status, numericKbId]);

  const handleReindex = async () => {
    if (!numericKbId) return;
    try {
      await knowledgeBaseApi.reindexKnowledgeBase(numericKbId);
      await loadDetail(false);
      alert('已提交重新索引请求');
    } catch (err) {
      alert(err instanceof Error ? err.message : '重新索引失败');
    }
  };

  const handleDelete = async () => {
    if (!numericKbId) return;
    if (!confirm('确定要删除这个知识库吗？')) return;
    try {
      await knowledgeBaseApi.deleteKnowledgeBase(numericKbId);
      navigate('/knowledgebases');
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const resetAnswerState = () => {
    setAnswer(null);
    setReferences([]);
    setStreamedAnswer('');
    setAnswerSessionId(null);
  };

  const handleAsk = async (e: FormEvent) => {
    e.preventDefault();
    if (!numericKbId || !question.trim()) return;
    setAsking(true);
    setError('');
    resetAnswerState();

    try {
      const result = await knowledgeBaseApi.askKnowledgeBase(numericKbId, {
        question: question.trim(),
        session_id: sessionId,
        top_k: 4,
      });
      setAnswer(result);
      setAnswerSessionId(result.session_id);
      setSessionId(result.session_id);
      setReferences(result.references);
      await loadDetail(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '提问失败');
    } finally {
      setAsking(false);
    }
  };

  const handleStreamAsk = async () => {
    if (!numericKbId || !question.trim()) return;
    setStreaming(true);
    setError('');
    resetAnswerState();

    try {
      await knowledgeBaseApi.streamKnowledgeBaseAnswer(
        numericKbId,
        {
          question: question.trim(),
          session_id: sessionId,
          top_k: 4,
        },
        {
          onMeta: (data) => {
            if (typeof data.session_id === 'string') {
              setSessionId(data.session_id);
              setAnswerSessionId(data.session_id);
            }
          },
          onChunk: (chunk) => {
            setStreamedAnswer(prev => prev + chunk);
          },
          onReferences: (refs) => {
            setReferences(refs as RagReferenceDTO[]);
          },
          onDone: async (data) => {
            const finalAnswer = typeof data.answer === 'string' ? data.answer : '';
            const rewrittenQuery = typeof data.rewritten_query === 'string' ? data.rewritten_query : question.trim();
            const nextSessionId = typeof data.session_id === 'string' ? data.session_id : sessionId || '';
            const finalReferences = Array.isArray(data.references) ? (data.references as RagReferenceDTO[]) : references;
            const finalPayload: RagAnswerDTO = {
              session_id: nextSessionId,
              rewritten_query: rewrittenQuery,
              answer: finalAnswer,
              references: finalReferences,
            };
            setReferences(finalReferences);
            setAnswer(finalPayload);
            setAnswerSessionId(nextSessionId || null);
            setSessionId(nextSessionId || null);
            await loadDetail(false);
          },
        },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '流式提问失败');
    } finally {
      setStreaming(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-red-300 mx-auto mb-4" />
          <p className="text-red-500">{error}</p>
          <button onClick={() => navigate('/knowledgebases')} className="mt-4 px-5 py-2 bg-primary-500 text-white rounded-xl">返回列表</button>
        </div>
      </div>
    );
  }

  if (!detail) {
    return null;
  }

  const status = statusMap[detail.index_status] || statusMap.PENDING;
  const currentAnswerText = answer?.answer || streamedAnswer;
  const currentReferences = answer?.references || references;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/knowledgebases')} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-xl font-bold text-slate-900">{detail.name}</h1>
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>{status.label}</span>
          </div>
          <div className="flex items-center gap-4 mt-1 text-sm text-slate-400 flex-wrap">
            <span>{detail.filename}</span>
            <span>{((detail.file_size || 0) / 1024).toFixed(1)} KB</span>
            <span>{detail.chunk_count} 个片段</span>
            <span>{new Date(detail.created_at).toLocaleString()}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleReindex} className="flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl hover:bg-slate-200 text-sm">
            <RefreshCw className="w-4 h-4" /> 重新索引
          </button>
          <button onClick={handleDelete} className="flex items-center gap-2 px-4 py-2 bg-red-50 text-red-600 rounded-xl hover:bg-red-100 text-sm">
            <Trash2 className="w-4 h-4" /> 删除
          </button>
        </div>
      </div>

      {detail.description && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6">
          <h2 className="text-lg font-semibold text-slate-900 mb-2">知识库说明</h2>
          <p className="text-slate-600 text-sm leading-relaxed">{detail.description}</p>
        </div>
      )}

      {processingStatuses.has(detail.index_status) && (
        <div className="bg-primary-50 border border-primary-100 rounded-2xl p-6">
          <div className="flex items-center gap-3">
            <Clock3 className="w-6 h-6 text-primary-500 animate-pulse" />
            <div>
              <h2 className="text-base font-semibold text-slate-900">索引处理中</h2>
              <p className="text-sm text-slate-600">系统正在分块和建立索引，页面会自动刷新。</p>
            </div>
          </div>
        </div>
      )}

      {detail.index_status === 'FAILED' && detail.index_error && (
        <div className="bg-red-50 border border-red-100 rounded-2xl p-6">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-6 h-6 text-red-500" />
            <div>
              <h2 className="text-base font-semibold text-slate-900">索引失败</h2>
              <p className="text-sm text-slate-600">{detail.index_error}</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <MessageSquare className="w-5 h-5 text-primary-500" />
              <h2 className="text-lg font-semibold text-slate-900">知识库问答</h2>
            </div>

            <form onSubmit={handleAsk} className="space-y-4">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="输入问题，例如：这个文档主要讲了什么？有哪些关键结论？"
                rows={4}
                disabled={detail.index_status !== 'COMPLETED' || asking || streaming}
                className="w-full px-4 py-3 rounded-xl border border-slate-200 outline-none focus:border-primary-400 resize-none disabled:bg-slate-50"
              />
              <div className="flex flex-wrap gap-3">
                <button
                  type="submit"
                  disabled={!question.trim() || detail.index_status !== 'COMPLETED' || asking || streaming}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl disabled:bg-slate-300 disabled:cursor-not-allowed"
                >
                  {asking ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} 普通问答
                </button>
                <button
                  type="button"
                  onClick={() => void handleStreamAsk()}
                  disabled={!question.trim() || detail.index_status !== 'COMPLETED' || asking || streaming}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl hover:bg-slate-200 disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed"
                >
                  {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} 流式问答
                </button>
              </div>
            </form>

            {error && (
              <div className="mt-4 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
                <AlertCircle className="w-5 h-5" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            {currentAnswerText && (
              <div className="mt-6 space-y-4">
                <div className="rounded-2xl border border-slate-200 p-5 bg-slate-50">
                  <h3 className="text-sm font-semibold text-slate-900 mb-3">回答结果</h3>
                  <p className="text-sm text-slate-700 leading-7 whitespace-pre-wrap">{currentAnswerText}</p>
                </div>

            {sessionId && (
              <p className="mt-3 text-xs text-slate-400">会话 ID：{answerSessionId || sessionId}</p>
            )}

                {currentReferences.length > 0 && (
                  <div className="rounded-2xl border border-slate-200 p-5">
                    <h3 className="text-sm font-semibold text-slate-900 mb-3">命中片段</h3>
                    <div className="space-y-3">
                      {currentReferences.map((ref) => (
                        <div key={`${ref.chunk_id}-${ref.chunk_index}`} className="rounded-xl border border-slate-100 p-4 bg-white">
                          <div className="flex items-center justify-between gap-3 mb-2">
                            <span className="text-xs font-medium text-primary-600">片段 #{ref.chunk_index + 1}</span>
                            <span className="text-xs text-slate-400">相关度 {(ref.score * 100).toFixed(1)}%</span>
                          </div>
                          <p className="text-sm text-slate-600 leading-6">{ref.content_preview}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <BookOpen className="w-5 h-5 text-primary-500" />
              <h2 className="text-lg font-semibold text-slate-900">文本片段预览</h2>
            </div>
            {detail.chunks.length === 0 ? (
              <p className="text-sm text-slate-400">当前还没有可展示的片段。</p>
            ) : (
              <div className="space-y-3 max-h-[520px] overflow-auto pr-1">
                {detail.chunks.slice(0, 20).map((chunk) => (
                  <div key={chunk.id} className="rounded-xl border border-slate-100 p-4 bg-slate-50">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-primary-600">片段 #{chunk.chunk_index + 1}</span>
                      {chunk.title && <span className="text-xs text-slate-400">{chunk.title}</span>}
                    </div>
                    <p className="text-sm text-slate-600 leading-6 whitespace-pre-wrap">{chunk.content_preview || chunk.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200 p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">文档信息</h2>
            <div className="space-y-3 text-sm text-slate-600">
              <div className="flex justify-between gap-4">
                <span>名称</span>
                <span className="text-slate-900 font-medium text-right">{detail.name}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span>文件名</span>
                <span className="text-slate-900 text-right break-all">{detail.filename}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span>文档数</span>
                <span className="text-slate-900 font-medium">{detail.document_count}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span>片段数</span>
                <span className="text-slate-900 font-medium">{detail.chunk_count}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span>最后索引</span>
                <span className="text-slate-900 text-right">{detail.last_indexed_at ? new Date(detail.last_indexed_at).toLocaleString() : '--'}</span>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">最近问答</h2>
            {detail.recent_chats.length === 0 ? (
              <p className="text-sm text-slate-400">暂无问答历史</p>
            ) : (
              <div className="space-y-3">
                {detail.recent_chats.map((chat) => (
                  <div key={chat.id} className="rounded-xl border border-slate-100 p-4 bg-slate-50">
                    <p className="text-sm font-medium text-slate-800 line-clamp-2">{chat.question}</p>
                    {chat.answer && <p className="text-xs text-slate-500 mt-2 line-clamp-3">{chat.answer}</p>}
                    <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                      <span>{chat.status}</span>
                      <span>{new Date(chat.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
