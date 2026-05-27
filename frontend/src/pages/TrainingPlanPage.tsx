import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  CalendarCheck,
  CheckCircle2,
  ClipboardList,
  Gauge,
  Loader2,
  RefreshCw,
  ShieldAlert,
  SlidersHorizontal,
  Target,
  Timer,
  TrendingUp,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { trainingApi } from '../api/training';
import type {
  CalibrationDimensionDTO,
  CalibrationQuestionDTO,
  PersonalTrainingPlanDTO,
  TrainingTaskDTO,
} from '../types/training';

export default function TrainingPlanPage() {
  const navigate = useNavigate();
  const [plan, setPlan] = useState<PersonalTrainingPlanDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchPlan = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await trainingApi.getPersonalPlan(7);
      setPlan(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '训练计划加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlan();
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-[55vh] flex-col items-center justify-center">
        <Loader2 className="h-10 w-10 animate-spin text-primary-500" />
        <p className="mt-4 text-sm text-slate-500">正在生成个人训练计划...</p>
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="rounded-lg border border-amber-100 bg-amber-50 p-5 text-amber-800">
        <div className="flex items-center gap-2 font-semibold">
          <AlertCircle className="h-5 w-5" />
          训练计划暂不可用
        </div>
        <p className="mt-2 text-sm">{error || '请稍后刷新。'}</p>
      </div>
    );
  }

  const calibration = plan.calibration;
  const topQuestions = calibration.questions.slice(0, 5);
  const topDimensions = calibration.dimensions.slice(0, 6);

  return (
    <div className="animate-in fade-in duration-500">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1 text-sm font-medium text-slate-700 shadow-sm">
            <CalendarCheck className="h-4 w-4 text-emerald-600" />
            个人训练计划
          </div>
          <h1 className="text-3xl font-bold text-slate-950">评分校准与 7 天训练安排</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{plan.summary}</p>
        </div>
        <button
          onClick={fetchPlan}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </div>

      {error && (
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-amber-100 bg-amber-50 p-4 text-amber-700">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="准备度" value={plan.readiness_score} helper="个人训练闭环指数" icon={Target} />
        <MetricCard label="校准后均分" value={calibration.calibrated_score || '-'} helper={`原始均分 ${calibration.average_raw_score || '-'}`} icon={Gauge} />
        <MetricCard label="评分可信度" value={calibration.confidence || '-'} helper={calibration.confidence_label} icon={SlidersHorizontal} />
        <MetricCard label="待复核题" value={calibration.review_needed_count} helper={`${calibration.high_risk_count} 道高风险`} icon={ShieldAlert} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">评分校准</h2>
              <p className="mt-1 text-sm text-slate-500">{calibration.summary}</p>
            </div>
            <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
              {calibration.total_questions} 题
            </span>
          </div>
          <div className="space-y-3">
            {topQuestions.map(question => (
              <QuestionRow key={`${question.session_id}-${question.question_index}`} question={question} />
            ))}
            {topQuestions.length === 0 && (
              <EmptyState
                title="暂无评分样本"
                detail="完成一次模拟面试并生成报告后，这里会显示校准结果。"
                action="去面试"
                onClick={() => navigate('/interview-hub')}
              />
            )}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-slate-700" />
            <h2 className="text-lg font-semibold text-slate-950">能力短板</h2>
          </div>
          <div className="space-y-3">
            {topDimensions.map(dimension => (
              <DimensionRow key={dimension.name} dimension={dimension} />
            ))}
            {topDimensions.length === 0 && (
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500">
                暂无维度样本。
              </div>
            )}
          </div>
          {calibration.next_actions.length > 0 && (
            <div className="mt-5 rounded-lg border border-emerald-100 bg-emerald-50 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-800">
                <CheckCircle2 className="h-4 w-4" />
                下一步
              </div>
              <ul className="space-y-2 text-sm leading-6 text-emerald-800">
                {calibration.next_actions.map(action => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>

      <section className="mt-5 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-slate-700" />
            <h2 className="text-lg font-semibold text-slate-950">7 天计划</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {plan.generated_from.map(item => (
              <span key={item} className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                {item}
              </span>
            ))}
          </div>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          {plan.plan.map(day => (
            <div key={day.day} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-950">{day.title}</h3>
                  <p className="mt-1 text-sm text-slate-500">{day.focus}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1 rounded-lg bg-white px-2.5 py-1 text-xs font-medium text-slate-600">
                  <Timer className="h-3.5 w-3.5" />
                  {day.total_minutes} 分钟
                </div>
              </div>
              <div className="space-y-3">
                {day.tasks.map(task => (
                  <TaskRow key={task.id} task={task} onGo={() => task.action_path && navigate(task.action_path)} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {plan.quick_wins.length > 0 && (
        <section className="mt-5 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            <h2 className="text-lg font-semibold text-slate-950">快速收益</h2>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {plan.quick_wins.map(item => (
              <div key={item} className="rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800">
                {item}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  helper,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  helper: string;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-slate-500">{label}</span>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className="text-3xl font-bold text-slate-950">{value}</div>
      <p className="mt-1 text-xs text-slate-500">{helper}</p>
    </div>
  );
}

function QuestionRow({ question }: { question: CalibrationQuestionDTO }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <PriorityBadge priority={question.review_priority} />
            <span className="rounded-lg bg-white px-2 py-1 text-xs font-medium text-slate-600">
              {question.score_band}
            </span>
            <span className="rounded-lg bg-white px-2 py-1 text-xs font-medium text-slate-600">
              可信度 {question.confidence}
            </span>
          </div>
          <p className="text-sm font-medium leading-6 text-slate-900">{question.question}</p>
          <p className="mt-2 text-sm leading-6 text-slate-500">{question.action}</p>
          {question.reasons.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {question.reasons.map(reason => (
                <span key={reason} className="rounded-lg bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">
                  {reason}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 gap-2 sm:flex-col sm:items-end">
          <ScorePill label="原始" value={question.raw_score} />
          <ScorePill label="校准" value={question.calibrated_score} />
        </div>
      </div>
    </div>
  );
}

function DimensionRow({ dimension }: { dimension: CalibrationDimensionDTO }) {
  const width = Math.min(100, Math.max(4, dimension.average_score));
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="font-medium text-slate-900">{dimension.name}</div>
        <div className={scoreClass(dimension.average_score)}>{dimension.average_score}</div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${width}%` }} />
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-500">{dimension.suggested_action}</p>
      <div className="mt-2 text-xs text-slate-400">
        {dimension.question_count} 个样本，{dimension.weak_count} 个低分样本
      </div>
    </div>
  );
}

function TaskRow({ task, onGo }: { task: TrainingTaskDTO; onGo: () => void }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <PriorityBadge priority={task.priority} />
            <span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
              {task.estimate_minutes} 分钟
            </span>
          </div>
          <h4 className="font-medium text-slate-950">{task.title}</h4>
          <p className="mt-1 text-sm leading-6 text-slate-500">{task.reason}</p>
          <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
            {task.checklist.map(item => (
              <div key={item} className="flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                <span className="min-w-0">{item}</span>
              </div>
            ))}
          </div>
        </div>
        {task.action_path && (
          <button
            onClick={onGo}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            进入
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const className =
    priority === 'HIGH'
      ? 'border-red-100 bg-red-50 text-red-700'
      : priority === 'MEDIUM'
        ? 'border-amber-100 bg-amber-50 text-amber-700'
        : 'border-emerald-100 bg-emerald-50 text-emerald-700';
  const label = priority === 'HIGH' ? '高优先级' : priority === 'MEDIUM' ? '中优先级' : '低优先级';
  return <span className={`rounded-lg border px-2 py-1 text-xs font-medium ${className}`}>{label}</span>;
}

function ScorePill({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg bg-white px-3 py-2 text-right shadow-sm">
      <div className="text-[11px] text-slate-400">{label}</div>
      <div className={scoreClass(value || 0)}>{value ?? '-'}</div>
    </div>
  );
}

function EmptyState({
  title,
  detail,
  action,
  onClick,
}: {
  title: string;
  detail: string;
  action: string;
  onClick: () => void;
}) {
  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-5">
      <div className="font-medium text-slate-900">{title}</div>
      <p className="mt-1 text-sm text-slate-500">{detail}</p>
      <button
        onClick={onClick}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
      >
        {action}
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}

function scoreClass(score: number): string {
  if (score >= 80) return 'text-lg font-bold text-emerald-600';
  if (score >= 70) return 'text-lg font-bold text-blue-600';
  if (score >= 60) return 'text-lg font-bold text-amber-600';
  return 'text-lg font-bold text-red-600';
}
