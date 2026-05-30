import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  CalendarCheck,
  CheckCircle2,
  ClipboardList,
  Gauge,
  Info,
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
  TrainingTrendDTO,
  TrainingTrendPointDTO,
} from '../types/training';

export default function TrainingPlanPage() {
  const navigate = useNavigate();
  const [plan, setPlan] = useState<PersonalTrainingPlanDTO | null>(null);
  const [trend, setTrend] = useState<TrainingTrendDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatingTaskId, setUpdatingTaskId] = useState<string | null>(null);
  const [error, setError] = useState('');

  const fetchPlan = async () => {
    setLoading(true);
    setError('');
    try {
      const [data, trendData] = await Promise.all([
        trainingApi.getPersonalPlan(7),
        trainingApi.getTrends(),
      ]);
      setPlan(data);
      setTrend(trendData);
    } catch (err) {
      setError(err instanceof Error ? err.message : '训练计划加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlan();
  }, []);

  const handleToggleTask = async (task: TrainingTaskDTO) => {
    if (!plan || updatingTaskId) return;
    const nextStatus = task.status === 'COMPLETED' ? 'TODO' : 'COMPLETED';
    setUpdatingTaskId(task.id);
    setError('');
    try {
      await trainingApi.updateTaskProgress({
        task_id: task.id,
        status: nextStatus,
        title: task.title,
        task_type: task.task_type,
        source_session_id: task.source_session_id,
        question_index: task.question_index,
      });
      const [nextPlan, nextTrend] = await Promise.all([
        trainingApi.getPersonalPlan(7),
        trainingApi.getTrends(),
      ]);
      setPlan(nextPlan);
      setTrend(nextTrend);
    } catch (err) {
      setError(err instanceof Error ? err.message : '训练状态更新失败');
    } finally {
      setUpdatingTaskId(null);
    }
  };

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
        <MetricCard
          label="准备度"
          value={plan.readiness_score}
          helper="个人训练闭环指数"
          hint="由校准后均分、评分可信度和简历分综合计算，用于判断当前训练闭环是否稳定。"
          icon={Target}
        />
        <MetricCard
          label="校准后均分"
          value={calibration.calibrated_score || '-'}
          helper={`原始均分 ${calibration.average_raw_score || '-'}`}
          hint="按单题可信度在原始分和报告基准均分之间加权；低可信分数会更靠近整体均值。"
          icon={Gauge}
        />
        <MetricCard
          label="评分可信度"
          value={calibration.confidence || '-'}
          helper={calibration.confidence_label}
          hint="依据反馈、覆盖要点、项目维度、参考答案等证据字段计算；缺分、缺反馈、短回答会降低可信度。"
          icon={SlidersHorizontal}
        />
        <MetricCard
          label="待复核题"
          value={calibration.review_needed_count}
          helper={`${calibration.high_risk_count} 道高风险`}
          hint="高优先级和中优先级题之和；无有效分、低可信或低原始分都会进入复核。"
          icon={ShieldAlert}
        />
        {trend?.latest_retry_delta !== null && trend?.latest_retry_delta !== undefined && (
          <MetricCard
            label="最近重练"
            value={deltaText(trend.latest_retry_delta)}
            helper="同题再练分差"
            hint="同一道题最新重练分数减去原始分；重练场次不计入校准均分。"
            icon={TrendingUp}
          />
        )}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">评分校准</h2>
              <p className="mt-1 text-sm text-slate-500">{calibration.summary}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">
                原始分来自当次报告；校准分会按可信度回归整体均值，缺少有效分的题仅用于复核提醒。
              </p>
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
          <div className="mb-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-slate-700" />
              <h2 className="text-lg font-semibold text-slate-950">薄弱题型与评分维度</h2>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-400">
              只聚合有有效原始分的样本，按均分从低到高展示；题型来自面试问题分类，项目维度来自项目题细分评分。
            </p>
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
                  <TaskRow
                    key={task.id}
                    task={task}
                    updating={updatingTaskId === task.id}
                    onToggle={() => handleToggleTask(task)}
                    onGo={() => task.action_path && navigate(task.action_path)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {trend && (
        <section className="mt-5 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-slate-700" />
              <h2 className="text-lg font-semibold text-slate-950">分数趋势</h2>
            </div>
            <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
              已完成 {trend.completed_task_count} 个任务
            </span>
          </div>
          <p className="mb-4 text-sm leading-6 text-slate-500">{trend.summary}</p>
          <div className="grid gap-3 md:grid-cols-4">
            <TrendMetric label="最近面试分" value={trend.latest_interview_score ?? '-'} />
            <TrendMetric label="最近简历分" value={trend.latest_resume_score ?? '-'} />
            <TrendMetric label="最近重练" value={deltaText(trend.latest_retry_delta)} />
            <TrendMetric label="完成任务" value={trend.completed_task_count} />
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {trend.trend.slice(-6).map((item, index) => (
              <div key={`${item.date}-${item.metric_type}-${item.source_id || index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-slate-900">{item.label}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.date}</div>
                  </div>
                  <div className={trendValueClass(item)}>{trendValue(item)}</div>
                </div>
              </div>
            ))}
            {trend.trend.length === 0 && (
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500">
                暂无趋势数据。
              </div>
            )}
          </div>
        </section>
      )}

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
  hint,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  helper: string;
  hint?: string;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-sm font-medium text-slate-500">
          {label}
          {hint && <InfoHint text={hint} />}
        </span>
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
  const hasRawScore = question.raw_score !== null && question.raw_score !== undefined;
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <PriorityBadge priority={question.review_priority} />
            <span className="rounded-lg bg-white px-2 py-1 text-xs font-medium text-slate-600">
              {question.score_band}
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-xs font-medium text-slate-600">
              可信度 {question.confidence}
              <InfoHint text="评分依据完整度：反馈、要点覆盖、维度评分、参考答案等越完整，可信度越高。" />
            </span>
            {question.retry_signal && (
              <span className={`rounded-lg px-2 py-1 text-xs font-medium ${deltaBadgeClass(question.latest_retry_delta)}`}>
                {question.retry_signal}
              </span>
            )}
          </div>
          <p className="text-sm font-medium leading-6 text-slate-900">{question.question}</p>
          <p className="mt-2 text-sm leading-6 text-slate-500">{question.action}</p>
          {!hasRawScore && (
            <p className="mt-1 text-xs leading-5 text-slate-400">
              这题没有有效原始分，不参与右侧维度均分，只用于提醒你补评分或人工复核。
            </p>
          )}
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
  const isQuestionType = dimension.name.startsWith('题型：');
  const displayName = isQuestionType ? dimension.name.replace('题型：', '') : dimension.name;
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium text-slate-900">{displayName}</div>
          <div className="mt-1 inline-flex rounded-lg bg-white px-2 py-0.5 text-[11px] font-medium text-slate-500">
            {isQuestionType ? '题型聚合' : '项目维度'}
          </div>
        </div>
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

function TaskRow({
  task,
  updating,
  onToggle,
  onGo,
}: {
  task: TrainingTaskDTO;
  updating: boolean;
  onToggle: () => void;
  onGo: () => void;
}) {
  const completed = task.status === 'COMPLETED';
  return (
    <div className={`rounded-lg border p-4 ${completed ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-white'}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <PriorityBadge priority={task.priority} />
            <span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
              {task.estimate_minutes} 分钟
            </span>
            {task.retry_signal && (
              <span className={`rounded-lg px-2 py-1 text-xs font-medium ${deltaBadgeClass(task.latest_retry_delta)}`}>
                {task.retry_signal}
              </span>
            )}
            {completed && (
              <span className="rounded-lg bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-700">
                已完成
              </span>
            )}
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
        <div className="flex shrink-0 flex-wrap gap-2 sm:flex-col">
          <button
            onClick={onToggle}
            disabled={updating}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${
              completed
                ? 'border border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50'
                : 'bg-emerald-600 text-white hover:bg-emerald-700'
            }`}
          >
            {updating ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {completed ? '取消完成' : '完成'}
          </button>
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
    </div>
  );
}

function TrendMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-slate-950">{value}</div>
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

function InfoHint({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex items-center" title={text}>
      <Info className="h-3.5 w-3.5 text-slate-400" aria-label={text} />
      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-64 -translate-x-1/2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs font-normal leading-5 text-slate-600 shadow-lg group-hover:block">
        {text}
      </span>
    </span>
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

function deltaText(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return '-';
  if (delta > 0) return `+${delta}`;
  if (delta === 0) return '持平';
  return `${delta}`;
}

function deltaBadgeClass(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return 'border border-slate-200 bg-slate-100 text-slate-600';
  if (delta > 0) return 'border border-emerald-100 bg-emerald-50 text-emerald-700';
  if (delta === 0) return 'border border-amber-100 bg-amber-50 text-amber-700';
  return 'border border-red-100 bg-red-50 text-red-700';
}

function trendValue(item: TrainingTrendPointDTO): number | string {
  if (item.metric_type === 'TRAINING_DONE') return item.completed_tasks;
  if (item.metric_type === 'RETRY_DELTA') return deltaText(item.delta);
  return item.score ?? '-';
}

function trendValueClass(item: TrainingTrendPointDTO): string {
  if (item.metric_type === 'TRAINING_DONE') return 'text-lg font-bold text-emerald-600';
  if (item.metric_type === 'RETRY_DELTA') {
    if (item.delta === null || item.delta === undefined) return 'text-lg font-bold text-slate-400';
    if (item.delta > 0) return 'text-lg font-bold text-emerald-600';
    if (item.delta === 0) return 'text-lg font-bold text-amber-600';
    return 'text-lg font-bold text-red-600';
  }
  return item.score === null || item.score === undefined ? 'text-lg font-bold text-slate-400' : scoreClass(item.score);
}
