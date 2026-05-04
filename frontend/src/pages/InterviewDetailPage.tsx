import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Loader2, AlertCircle, Download, Award, TrendingUp, Target, Clock3 } from 'lucide-react';
import { interviewApi } from '../api/interview';
import type { InterviewDetailDTO } from '../types/interview';

const PROCESSING_STATUSES = new Set(['PENDING', 'PROCESSING']);

export default function InterviewDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<InterviewDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    void loadDetail(true);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !detail?.evaluate_status || !PROCESSING_STATUSES.has(detail.evaluate_status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void loadDetail(false);
    }, 3000);

    return () => window.clearInterval(timer);
  }, [sessionId, detail?.evaluate_status]);

  const loadDetail = async (showLoading = false) => {
    if (!sessionId) return;

    if (showLoading) {
      setLoading(true);
    }

    try {
      const data = await interviewApi.getInterviewDetail(sessionId);
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

  const handleExport = async () => {
    if (!sessionId) return;
    try {
      const blob = await interviewApi.exportPdf(sessionId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `interview-report-${sessionId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : '导出失败');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-red-300 mx-auto mb-4" />
          <p className="text-red-500">{error || '面试记录不存在'}</p>
          <button onClick={() => navigate('/interviews')} className="mt-4 px-5 py-2 bg-primary-500 text-white rounded-xl">返回列表</button>
        </div>
      </div>
    );
  }

  const isEvaluating = !!detail.evaluate_status && PROCESSING_STATUSES.has(detail.evaluate_status);
  const isFailed = detail.evaluate_status === 'FAILED';
  const hasReport = detail.overall_score !== null;

  return (
    <div>
      <div className="flex items-center gap-3 mb-8">
        <button onClick={() => navigate('/interviews')} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-slate-900">面试报告 #{sessionId!.slice(-8)}</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-slate-400">
            <span>{detail.total_questions || 0} 道题</span>
            {detail.difficulty && <span>难度: {detail.difficulty}</span>}
            {detail.created_at && <span>{new Date(detail.created_at).toLocaleDateString()}</span>}
          </div>
        </div>
        <button
          onClick={handleExport}
          disabled={!hasReport}
          className="flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl hover:bg-slate-200 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Download className="w-4 h-4" /> 导出PDF
        </button>
      </div>

      {isEvaluating && (
        <div className="bg-primary-50 border border-primary-100 rounded-2xl p-6 mb-8">
          <div className="flex items-center gap-3">
            <Clock3 className="w-6 h-6 text-primary-500 animate-pulse" />
            <div>
              <h2 className="text-base font-semibold text-slate-900">报告生成中</h2>
              <p className="text-sm text-slate-600">AI 正在评估本次面试表现，页面会自动刷新。</p>
            </div>
          </div>
        </div>
      )}

      {isFailed && (
        <div className="bg-red-50 border border-red-100 rounded-2xl p-6 mb-8">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-6 h-6 text-red-500" />
            <div>
              <h2 className="text-base font-semibold text-slate-900">报告生成失败</h2>
              <p className="text-sm text-slate-600">{detail.evaluate_error || '请稍后重试或重新发起面试。'}</p>
            </div>
          </div>
        </div>
      )}

      {hasReport && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
            <div className="bg-white rounded-2xl border border-slate-200 p-6 text-center">
              <Award className="w-8 h-8 text-primary-500 mx-auto mb-3" />
              <div className="text-4xl font-bold text-primary-600 mb-1">{detail.overall_score}</div>
              <div className="text-sm text-slate-500">综合评分</div>
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-6">
              <TrendingUp className="w-8 h-8 text-green-500 mb-3" />
              <h3 className="font-semibold text-slate-900 mb-2">优势</h3>
              <ul className="text-sm text-slate-600 space-y-1">
                {detail.strengths.slice(0, 3).map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-green-500">✓</span>
                    <span className="line-clamp-1">{s}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-6">
              <Target className="w-8 h-8 text-orange-500 mb-3" />
              <h3 className="font-semibold text-slate-900 mb-2">待改进</h3>
              <ul className="text-sm text-slate-600 space-y-1">
                {detail.improvements.slice(0, 3).map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-orange-500">→</span>
                    <span className="line-clamp-1">{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {detail.overall_feedback && (
            <div className="bg-white rounded-2xl border border-slate-200 p-6 mb-8">
              <h2 className="text-lg font-semibold text-slate-900 mb-3">综合评价</h2>
              <p className="text-slate-600 leading-relaxed">{detail.overall_feedback}</p>
            </div>
          )}

          <div className="bg-white rounded-2xl border border-slate-200 p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">问答详情</h2>
            <div className="space-y-4">
              {detail.question_evaluations.map((q, idx) => {
                const refAnswer = detail.reference_answers?.find(r => r.question_index === q.question_index);
                const isFollowUp = refAnswer?.question?.includes('-追问') || false;
                return (
                  <div key={idx} className="border border-slate-100 rounded-xl p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="w-6 h-6 bg-primary-100 text-primary-600 rounded-full flex items-center justify-center text-xs font-medium">{q.question_index + 1}</span>
                        {isFollowUp && (
                          <span className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">追问</span>
                        )}
                        {q.question_type === 'project' && (
                          <span className="px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded text-xs">项目题</span>
                        )}
                        <span className="text-xs text-slate-400">{q.category || '综合'}</span>
                      </div>
                      {q.score > 0 && (
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          q.score >= 80 ? 'bg-green-100 text-green-600' :
                          q.score >= 60 ? 'bg-yellow-100 text-yellow-600' :
                          'bg-red-100 text-red-600'
                        }`}>{q.score} 分</span>
                      )}
                    </div>
                    <p className="text-slate-800 font-medium mb-2">{q.question}</p>
                    {q.user_answer && (
                      <div className="bg-slate-50 rounded-lg p-3 mb-2">
                        <p className="text-sm text-slate-600"><span className="font-medium text-slate-700">你的回答：</span>{q.user_answer}</p>
                      </div>
                    )}
                    {q.feedback && (
                      <p className="text-sm text-slate-500 mb-2"><span className="font-medium text-slate-700">点评：</span>{q.feedback}</p>
                    )}

                    {/* 知识题：关键得分点 */}
                    {q.covered_points && q.covered_points.length > 0 && (
                      <div className="mt-2 p-2 bg-green-50 rounded-lg">
                        <p className="text-xs font-medium text-green-700 mb-1">答到的点：</p>
                        <div className="flex flex-wrap gap-1">
                          {q.covered_points.map((p, i) => (
                            <span key={i} className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs">{p}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {q.missed_points && q.missed_points.length > 0 && (
                      <div className="mt-2 p-2 bg-orange-50 rounded-lg">
                        <p className="text-xs font-medium text-orange-700 mb-1">遗漏的点：</p>
                        <div className="flex flex-wrap gap-1">
                          {q.missed_points.map((p, i) => (
                            <span key={i} className="px-2 py-0.5 bg-orange-100 text-orange-700 rounded text-xs">{p}</span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 项目题：四维评分 */}
                    {q.dimensions && (
                      <div className="mt-2 grid grid-cols-4 gap-2">
                        <div className="text-center p-2 bg-slate-50 rounded-lg">
                          <p className="text-xs text-slate-500">真实性</p>
                          <p className="text-sm font-semibold text-slate-700">{q.dimensions.authenticity}</p>
                        </div>
                        <div className="text-center p-2 bg-slate-50 rounded-lg">
                          <p className="text-xs text-slate-500">技术深度</p>
                          <p className="text-sm font-semibold text-slate-700">{q.dimensions.technical_depth}</p>
                        </div>
                        <div className="text-center p-2 bg-slate-50 rounded-lg">
                          <p className="text-xs text-slate-500">深度</p>
                          <p className="text-sm font-semibold text-slate-700">{q.dimensions.depth}</p>
                        </div>
                        <div className="text-center p-2 bg-slate-50 rounded-lg">
                          <p className="text-xs text-slate-500">表达</p>
                          <p className="text-sm font-semibold text-slate-700">{q.dimensions.expression}</p>
                        </div>
                      </div>
                    )}

                    {/* 参考答案 */}
                    {refAnswer?.reference_answer && (
                      <details className="mt-2">
                        <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-600">查看参考答案</summary>
                        <div className="mt-1 p-2 bg-blue-50 rounded-lg">
                          <p className="text-xs text-blue-800">{refAnswer.reference_answer}</p>
                        </div>
                      </details>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
