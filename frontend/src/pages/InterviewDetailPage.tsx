import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Loader2, AlertCircle, Award, TrendingUp, Target, Clock3, ClipboardList, RotateCcw } from 'lucide-react';
import { interviewApi } from '../api/interview';
import type { InterviewDetailDTO, QuestionEvaluationDTO } from '../types/interview';

const PROCESSING_STATUSES = new Set(['PENDING', 'PROCESSING']);
const FEEDBACK_LABELS = ['面试官判断', '当前风险点', '80分改法', '下一步追问'];

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
  const coachActions = hasReport ? buildCoachActions(detail) : [];
  const averageAnswerChars = hasReport ? getAverageAnswerChars(detail.question_evaluations) : 0;
  const projectQuestionCount = detail.question_evaluations.filter(q => q.question_type === 'project').length;

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
          <div className="bg-white rounded-2xl border border-slate-200 p-6 mb-8">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-50">
                  <ClipboardList className="h-5 w-5 text-primary-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">先改这 3 件事</h2>
                  <p className="mt-1 text-sm leading-6 text-slate-500">
                    本次平均回答 {averageAnswerChars} 字{projectQuestionCount > 0 ? `，项目题 ${projectQuestionCount} 道` : ''}。
                    优先把低分题补成“证据 + 取舍 + 结果”的回答。
                  </p>
                </div>
              </div>
              <button
                onClick={() => navigate(detail.resume_id ? `/project-drill?resumeId=${detail.resume_id}` : '/interview-hub')}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
              >
                <RotateCcw className="h-4 w-4" />
                重练项目深挖
              </button>
            </div>
            <div className="mt-5 grid gap-5 border-t border-slate-100 pt-5 lg:grid-cols-3">
              {coachActions.map(action => (
                <div key={action.title} className="border-l-2 border-primary-200 pl-3">
                  <div className="mb-2 text-xs font-medium text-slate-400">{action.source}</div>
                  <h3 className="text-sm font-semibold text-slate-900">{action.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{action.detail}</p>
                </div>
              ))}
            </div>
          </div>

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
                {detail.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-green-500 mt-0.5">✓</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-6">
              <Target className="w-8 h-8 text-orange-500 mb-3" />
              <h3 className="font-semibold text-slate-900 mb-2">待改进</h3>
              <ul className="text-sm text-slate-600 space-y-1">
                {detail.improvements.map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-orange-500 mt-0.5">→</span>
                    <span>{s}</span>
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
                    {q.feedback && <FeedbackBlocks feedback={q.feedback} />}

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

type CoachAction = {
  title: string;
  detail: string;
  source: string;
};

function buildCoachActions(detail: InterviewDetailDTO): CoachAction[] {
  const actions: CoachAction[] = [];
  const seen = new Set<string>();
  const lowScoreQuestions = [...detail.question_evaluations]
    .filter(q => q.score < 60)
    .sort((a, b) => a.score - b.score);

  for (const question of lowScoreQuestions) {
    const action = coachActionForQuestion(question);
    if (seen.has(action.title)) continue;
    seen.add(action.title);
    actions.push({
      ...action,
      source: `Q${question.question_index + 1} · ${question.category || '综合'} · ${question.score} 分`,
    });
    if (actions.length >= 3) break;
  }

  if (actions.length === 0) {
    actions.push({
      title: '复盘高频扣分点',
      detail: '把每道题的回答压缩成背景、个人贡献、技术取舍、结果指标四段，再进行下一轮重答。',
      source: '本次报告',
    });
  }

  return actions;
}

function coachActionForQuestion(question: QuestionEvaluationDTO): Omit<CoachAction, 'source'> {
  const category = question.category || '';
  if (category.includes('技术取舍')) {
    return {
      title: '补技术选型证据',
      detail: '准备 FastAPI、Redis、PGVector、LangChain 的选型理由，对比 1 个替代方案，再说明如果重做会保留什么、改什么。',
    };
  }
  if (category.includes('结果指标')) {
    return {
      title: '补量化指标',
      detail: '给项目补 3 类指标：任务完成率、报告生成耗时、用户反馈满意度；没有历史数据也要说明下一步如何采集。',
    };
  }
  if (category.includes('异常') || category.includes('边界')) {
    return {
      title: '补异常兜底链路',
      detail: '按“大模型失败、搜索失败、Redis 入队失败、报告生成失败”列触发条件、降级策略和验证方式。',
    };
  }
  if (category.includes('岗位')) {
    return {
      title: '补岗位能力映射',
      detail: '把项目能力映射到 AI 应用开发：RAG、Agent 编排、结构化输出、评估指标、工程部署各准备一句证据。',
    };
  }
  if (category.includes('个人贡献')) {
    return {
      title: '补个人贡献边界',
      detail: '明确你独立完成的模块、关键决策、踩坑过程和可验证产出，避免只说“全栈开发、全面了解”。',
    };
  }
  return {
    title: '补项目介绍证据',
    detail: '把开场回答改成 2 分钟版本：项目目标、核心架构、你的贡献、一个难点、一个结果。',
  };
}

function getAverageAnswerChars(questions: QuestionEvaluationDTO[]): number {
  const answers = questions.map(q => q.user_answer?.trim().length || 0).filter(Boolean);
  if (answers.length === 0) return 0;
  return Math.round(answers.reduce((sum, item) => sum + item, 0) / answers.length);
}

function FeedbackBlocks({ feedback }: { feedback: string }) {
  const sections = parseFeedbackSections(feedback);
  if (sections.length <= 1) {
    return (
      <p className="text-sm text-slate-500 mb-2">
        <span className="font-medium text-slate-700">点评：</span>{feedback}
      </p>
    );
  }

  return (
    <div className="mb-2 grid gap-2 lg:grid-cols-2">
      {sections.map(section => (
        <div key={section.label} className={`rounded-lg p-3 text-sm leading-6 ${feedbackTone(section.label)}`}>
          <div className="mb-1 text-xs font-semibold">{section.label}</div>
          <p>{section.content}</p>
        </div>
      ))}
    </div>
  );
}

function parseFeedbackSections(feedback: string): { label: string; content: string }[] {
  const text = feedback
    .replace(/\*\*/g, '')
    .replace(/【([^】]+)】/g, '$1：')
    .replace(/\s+/g, ' ')
    .trim();

  const matches = FEEDBACK_LABELS
    .map(label => {
      const marker = new RegExp(`${label}[：:]`).exec(text);
      return marker && marker.index !== undefined
        ? { label, index: marker.index, marker: marker[0] }
        : null;
    })
    .filter((item): item is { label: string; index: number; marker: string } => Boolean(item))
    .sort((a, b) => a.index - b.index);

  if (matches.length === 0) {
    return [{ label: '点评', content: text }];
  }

  return matches
    .map((match, index) => {
      const start = match.index + match.marker.length;
      const end = matches[index + 1]?.index ?? text.length;
      return {
        label: match.label,
        content: text.slice(start, end).trim(),
      };
    })
    .filter(section => section.content);
}

function feedbackTone(label: string): string {
  if (label === '当前风险点') return 'bg-orange-50 text-orange-800';
  if (label === '80分改法') return 'bg-emerald-50 text-emerald-800';
  if (label === '下一步追问') return 'bg-indigo-50 text-indigo-800';
  return 'bg-slate-50 text-slate-700';
}
