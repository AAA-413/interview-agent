import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, Trash2, Loader2, AlertCircle, ChevronRight, Eye } from 'lucide-react';
import { interviewApi } from '../api/interview';
import type { SessionListItemDTO } from '../types/interview';

export default function InterviewHistoryPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionListItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchSessions = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await interviewApi.listSessions();
      setSessions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSessions(); }, []);

  const handleDelete = async (sessionId: string) => {
    if (!confirm('确定要删除这条面试记录吗？')) return;
    try {
      await interviewApi.deleteSession(sessionId);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const statusMap: Record<string, { label: string; color: string }> = {
    CREATED: { label: '已创建', color: 'bg-yellow-100 text-yellow-700' },
    IN_PROGRESS: { label: '进行中', color: 'bg-blue-100 text-blue-700' },
    COMPLETED: { label: '已完成', color: 'bg-green-100 text-green-700' },
    EVALUATED: { label: '已评估', color: 'bg-purple-100 text-purple-700' },
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
          <h1 className="text-2xl font-bold text-slate-900">面试记录</h1>
          <p className="text-slate-500 mt-1">共 {sessions.length} 条记录</p>
        </div>
        <button
          onClick={() => navigate('/interview-hub')}
          className="px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25 hover:from-primary-700 hover:to-primary-600 transition-all"
        >
          开始新面试
        </button>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5" />
          <span className="text-sm">{error}</span>
          <button onClick={fetchSessions} className="ml-auto text-sm underline">重试</button>
        </div>
      )}

      {sessions.length === 0 ? (
        <div className="text-center py-20">
          <MessageSquare className="w-16 h-16 text-slate-200 mx-auto mb-4" />
          <p className="text-slate-400 text-lg">暂无面试记录</p>
          <p className="text-slate-300 text-sm mt-2">开始第一次模拟面试吧</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sessions.map((session) => {
            const status = statusMap[session.status] || statusMap.CREATED;
            return (
              <div
                key={session.session_id}
                className="bg-white rounded-xl border border-slate-200 p-5 hover:shadow-md transition-all duration-200 cursor-pointer"
                onClick={() => navigate(`/interviews/${session.session_id}`)}
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-primary-50 rounded-xl flex items-center justify-center flex-shrink-0">
                    <MessageSquare className="w-6 h-6 text-primary-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <h3 className="font-medium text-slate-900">面试 #{session.session_id.slice(-8)}</h3>
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                        {status.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 mt-1 text-sm text-slate-400">
                      <span>{session.total_questions || 0} 道题</span>
                      {session.difficulty && <span>难度: {session.difficulty}</span>}
                      {session.created_at && <span>{new Date(session.created_at).toLocaleDateString()}</span>}
                      {session.overall_score !== null && (
                        <span className="text-primary-600 font-medium">评分: {session.overall_score}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    {session.status === 'IN_PROGRESS' && (
                      <button
                        onClick={() => navigate('/interview', { state: { sessionIdToResume: session.session_id } })}
                        className="flex items-center gap-1 px-3 py-1.5 bg-primary-50 text-primary-600 rounded-lg text-sm hover:bg-primary-100"
                      >
                        继续面试
                      </button>
                    )}
                    <button onClick={() => navigate(`/interviews/${session.session_id}`)} className="p-2 text-slate-400 hover:text-primary-500 rounded-lg hover:bg-slate-50" title="查看详情">
                      <Eye className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleDelete(session.session_id)} className="p-2 text-slate-400 hover:text-red-500 rounded-lg hover:bg-slate-50" title="删除">
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
