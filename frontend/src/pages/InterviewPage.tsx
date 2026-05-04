import { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, Send, Loader2, AlertCircle, CheckCircle2, Clock3 } from 'lucide-react';
import { interviewApi } from '../api/interview';
import type { InterviewQuestionDTO, InterviewSessionDTO, InterviewReportDTO } from '../types/interview';

const PROCESSING_STATUSES = new Set(['PENDING', 'PROCESSING']);

export default function InterviewPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { sessionId?: string; sessionIdToResume?: string } | null;
  const sessionIdFromState = state?.sessionId || state?.sessionIdToResume;

  const [sessionId, setSessionId] = useState<string | null>(sessionIdFromState || null);
  const [session, setSession] = useState<InterviewSessionDTO | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState<InterviewQuestionDTO | null>(null);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [completed, setCompleted] = useState(false);
  const [report, setReport] = useState<InterviewReportDTO | null>(null);
  const [questionHistory, setQuestionHistory] = useState<{ question: InterviewQuestionDTO; answer: string }[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!sessionId) {
      navigate('/interview-hub');
      return;
    }
    void loadSession(true);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !completed || report) {
      return;
    }

    const timer = window.setInterval(() => {
      void pollReport();
    }, 3000);

    return () => window.clearInterval(timer);
  }, [sessionId, completed, report]);

  const loadSession = async (showLoading = false) => {
    if (!sessionId) return;

    if (showLoading) {
      setLoading(true);
    }

    try {
      const s = await interviewApi.getSession(sessionId);
      setSession(s);

      if (s.status === 'COMPLETED' || s.status === 'EVALUATED') {
        setCompleted(true);
        setCurrentQuestion(null);

        if (s.status === 'EVALUATED') {
          const r = await interviewApi.getReport(sessionId);
          setReport(r);
          setError('');
        } else {
          setReport(null);
          if (s.evaluate_status === 'FAILED') {
            setError(s.evaluate_error || '面试报告生成失败');
          } else {
            setError('');
          }
        }
        return;
      }

      const q = await interviewApi.getCurrentQuestion(sessionId);
      if (q.completed) {
        setCompleted(true);
        setCurrentQuestion(null);
        setReport(null);
        setError('');
      } else if (q.question) {
        setCurrentQuestion(q.question);
        setCompleted(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const pollReport = async () => {
    if (!sessionId) return;

    try {
      const s = await interviewApi.getSession(sessionId);
      setSession(s);

      if (s.status === 'EVALUATED') {
        const r = await interviewApi.getReport(sessionId);
        setReport(r);
        setError('');
        return;
      }

      if (s.evaluate_status === 'FAILED') {
        setError(s.evaluate_error || '面试报告生成失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载报告失败');
    }
  };

  const handleSubmit = async () => {
    if (!sessionId || !answer.trim() || submitting || !currentQuestion) return;
    setSubmitting(true);
    setError('');
    try {
      const trimmedAnswer = answer.trim();
      const response = await interviewApi.submitAnswer(sessionId, currentQuestion.question_index, trimmedAnswer);
      setQuestionHistory(prev => [...prev, { question: currentQuestion, answer: trimmedAnswer }]);
      setAnswer('');

      if (response.has_next_question && response.next_question) {
        setCurrentQuestion(response.next_question);
      } else {
        setCompleted(true);
        setCurrentQuestion(null);
        setReport(null);
        await loadSession(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  if (completed && report) {
    return (
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-8">
          <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-slate-900">面试完成！</h1>
          <p className="text-slate-500 mt-2">AI 已完成对你的面试评估</p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-8 mb-6">
          <div className="flex items-center justify-center mb-6">
            <div className="relative w-36 h-36">
              <svg className="w-36 h-36 -rotate-90" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="50" fill="none" stroke="#e2e8f0" strokeWidth="10" />
                <circle cx="60" cy="60" r="50" fill="none" stroke="#6366f1" strokeWidth="10"
                  strokeDasharray={`${report.overall_score * 3.14} 314`} strokeLinecap="round" />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-4xl font-bold text-primary-600">{report.overall_score}</span>
              </div>
            </div>
          </div>

          {report.overall_feedback && (
            <div className="bg-slate-50 rounded-xl p-4 mb-6">
              <p className="text-slate-700 leading-relaxed">{report.overall_feedback}</p>
            </div>
          )}

          {report.strengths.length > 0 && (
            <div className="mb-4">
              <h3 className="font-semibold text-green-700 mb-2">✓ 优势</h3>
              <ul className="space-y-1">
                {report.strengths.map((s, i) => (
                  <li key={i} className="text-sm text-slate-600 pl-4">{s}</li>
                ))}
              </ul>
            </div>
          )}

          {report.improvements.length > 0 && (
            <div>
              <h3 className="font-semibold text-orange-700 mb-2">→ 待改进</h3>
              <ul className="space-y-1">
                {report.improvements.map((s, i) => (
                  <li key={i} className="text-sm text-slate-600 pl-4">{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="space-y-4 mb-8">
          <h2 className="text-lg font-semibold text-slate-900">答题详情</h2>
          {report.question_evaluations.map((q, idx) => {
            const question = report.reference_answers?.find(r => r.question_index === q.question_index);
            const isFollowUp = question?.question?.includes('-追问') || false;
            return (
              <div key={idx} className="bg-white rounded-xl border border-slate-200 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-700">Q{q.question_index + 1}. {q.question}</span>
                    {isFollowUp && (
                      <span className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">追问</span>
                    )}
                    {q.question_type === 'project' && (
                      <span className="px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded text-xs">项目题</span>
                    )}
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    q.score >= 80 ? 'bg-green-100 text-green-600' :
                    q.score >= 60 ? 'bg-yellow-100 text-yellow-600' :
                    'bg-red-100 text-red-600'
                  }`}>{q.score}分</span>
                </div>
                {q.user_answer && <p className="text-sm text-slate-500 mb-1"><span className="font-medium">你的回答：</span>{q.user_answer}</p>}
                {q.feedback && <p className="text-sm text-slate-500 mb-2"><span className="font-medium">点评：</span>{q.feedback}</p>}

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
              </div>
            );
          })}
        </div>

        <div className="flex gap-3">
          <button onClick={() => navigate('/interviews')} className="flex-1 py-3 bg-slate-100 text-slate-700 rounded-xl font-medium hover:bg-slate-200">
            查看所有记录
          </button>
          <button onClick={() => navigate('/interview-hub')} className="flex-1 py-3 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25">
            再来一次
          </button>
        </div>
      </div>
    );
  }

  if (completed) {
    const evaluating = session?.evaluate_status ? PROCESSING_STATUSES.has(session.evaluate_status) : true;

    return (
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center">
          {evaluating ? (
            <>
              <Clock3 className="w-16 h-16 text-primary-500 mx-auto mb-4 animate-pulse" />
              <h1 className="text-2xl font-bold text-slate-900 mb-2">面试已完成，报告生成中</h1>
              <p className="text-slate-500">AI 正在整理你的回答并生成评估报告，页面会自动刷新。</p>
            </>
          ) : (
            <>
              <AlertCircle className="w-16 h-16 text-red-400 mx-auto mb-4" />
              <h1 className="text-2xl font-bold text-slate-900 mb-2">报告生成失败</h1>
              <p className="text-slate-500">{error || session?.evaluate_error || '请稍后重试或返回列表查看详情。'}</p>
            </>
          )}

          <div className="mt-6 flex gap-3 justify-center">
            <button onClick={() => navigate('/interviews')} className="px-5 py-3 bg-slate-100 text-slate-700 rounded-xl font-medium hover:bg-slate-200">
              返回记录列表
            </button>
            <button onClick={() => navigate(`/interviews/${sessionId}`)} className="px-5 py-3 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25">
              查看详情页
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/interviews')} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-bold text-slate-900">模拟面试</h1>
          <p className="text-sm text-slate-400">
            {session && `第 ${currentQuestion ? currentQuestion.question_index + 1 : '?'} / ${session.total_questions} 题`}
          </p>
        </div>
      </div>

      {session && (
        <div className="mb-6">
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary-500 to-primary-400 rounded-full transition-all duration-500"
              style={{ width: `${((currentQuestion?.question_index || 0) / session.total_questions) * 100}%` }}
            />
          </div>
        </div>
      )}

      {questionHistory.length > 0 && (
        <div className="mb-6 space-y-3 max-h-64 overflow-y-auto">
          {questionHistory.map((item, idx) => (
            <div key={idx} className="bg-slate-50 rounded-xl p-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium text-slate-700">Q{item.question.question_index + 1}. {item.question.question}</p>
                {item.question.is_follow_up && (
                  <span className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">追问</span>
                )}
              </div>
              <p className="text-sm text-slate-500 mt-1 line-clamp-2">{item.answer}</p>
            </div>
          ))}
        </div>
      )}

      {currentQuestion && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-7 h-7 bg-primary-100 text-primary-600 rounded-full flex items-center justify-center text-sm font-medium">
              {currentQuestion.question_index + 1}
            </span>
            {currentQuestion.is_follow_up && (
              <span className="px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full text-xs font-medium">追问</span>
            )}
            {currentQuestion.category && (
              <span className="px-2.5 py-0.5 bg-slate-100 text-slate-500 rounded-full text-xs">{currentQuestion.category}</span>
            )}
            {currentQuestion.question_type === 'project' && (
              <span className="px-2.5 py-0.5 bg-purple-100 text-purple-600 rounded-full text-xs">项目题</span>
            )}
          </div>
          <h2 className="text-lg font-semibold text-slate-900 leading-relaxed">{currentQuestion.question}</h2>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <textarea
          ref={textareaRef}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="请输入你的回答..."
          rows={6}
          className="w-full resize-none border-0 focus:ring-0 focus:outline-none text-slate-800 placeholder:text-slate-300"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              handleSubmit();
            }
          }}
        />
        <div className="flex items-center justify-between pt-3 border-t border-slate-100">
          <span className="text-xs text-slate-400">Ctrl + Enter 提交</span>
          <button
            onClick={handleSubmit}
            disabled={!answer.trim() || submitting}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-medium text-sm transition-all ${
              !answer.trim() || submitting
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-lg shadow-primary-500/25 hover:from-primary-700 hover:to-primary-600'
            }`}
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                提交中...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                提交回答
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
