import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  FileText,
  Loader2,
  MessageSquareText,
  Play,
  RefreshCw,
  ShieldAlert,
  Target,
} from 'lucide-react';
import { interviewApi } from '../api/interview';
import { resumeApi } from '../api/resume';
import type { ProjectDrillDTO, ProjectDrillQuestionDTO } from '../types/projectDrill';
import type { ResumeListItemDTO } from '../types/resume';

const levelOptions = ['校招', '实习', '转岗/0-1 年', '转岗/1-3 年'];

type DrillForm = {
  resume_id: string;
  target_role: string;
  target_company: string;
  level: string;
  project_name: string;
  jd_text: string;
};

export default function ProjectDrillPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [resumes, setResumes] = useState<ResumeListItemDTO[]>([]);
  const [loadingResumes, setLoadingResumes] = useState(true);
  const [resumeLoadError, setResumeLoadError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [error, setError] = useState('');
  const [drill, setDrill] = useState<ProjectDrillDTO | null>(null);
  const [form, setForm] = useState<DrillForm>({
    resume_id: searchParams.get('resumeId') || '',
    target_role: searchParams.get('targetRole') || 'Java 后端开发',
    target_company: searchParams.get('targetCompany') || '',
    level: searchParams.get('level') || '校招',
    project_name: searchParams.get('projectName') || '',
    jd_text: '',
  });

  useEffect(() => {
    resumeApi.listResumes()
      .then(data => {
        setResumes(data);
        if (!form.resume_id) {
          const firstCompleted = data.find(item => item.analyze_status === 'COMPLETED');
          if (firstCompleted) {
            setForm(prev => ({ ...prev, resume_id: String(firstCompleted.id) }));
          }
        }
      })
      .catch(err => setResumeLoadError(err instanceof Error ? err.message : '简历列表加载失败'))
      .finally(() => setLoadingResumes(false));
  }, []);

  const completedResumes = useMemo(
    () => resumes.filter(item => item.analyze_status === 'COMPLETED'),
    [resumes]
  );

  const updateForm = (key: keyof DrillForm, value: string) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.resume_id) {
      setError('项目打磨需要先选择一份已解析简历');
      return;
    }
    if (!form.target_role.trim()) {
      setError('请填写目标岗位');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      const result = await interviewApi.createProjectDrill({
        resume_id: Number(form.resume_id),
        target_role: form.target_role.trim(),
        target_company: form.target_company.trim() || null,
        level: form.level,
        project_name: form.project_name.trim() || null,
        jd_text: form.jd_text.trim() || null,
      });
      setDrill(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成项目打磨失败');
    } finally {
      setSubmitting(false);
    }
  };

  const startProjectDrillInterview = async () => {
    const resumeId = drill?.resume_id || Number(form.resume_id);
    if (!resumeId) {
      setError('请先选择一份已解析简历');
      return;
    }
    setCreatingSession(true);
    setError('');
    try {
      const session = await interviewApi.createSession({
        resume_id: resumeId,
        skill_id: 'project-drill',
        interview_mode: 'project_drill',
        question_count: 6,
        force_create: true,
        target_role: drill?.target_role || form.target_role,
        target_company: drill?.target_company || form.target_company || null,
        level: drill?.level || form.level,
        project_name: drill?.selected_project.name || form.project_name || null,
        jd_text: form.jd_text || null,
      });
      navigate('/interview', { state: { sessionId: session.session_id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建项目专项答题失败');
    } finally {
      setCreatingSession(false);
    }
  };

  return (
    <div className="animate-in fade-in duration-500">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <button
            onClick={() => navigate('/diagnosis')}
            className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-slate-500 transition hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            返回诊断
          </button>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-primary-100 bg-primary-50 px-3 py-1 text-sm font-medium text-primary-700">
            <MessageSquareText className="h-4 w-4" />
            项目打磨
          </div>
          <h1 className="text-3xl font-bold text-slate-950">项目素材打磨</h1>
          <p className="mt-2 text-sm text-slate-500">先把项目讲法、证据和风险补齐，再进入完整模拟面试</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => navigate('/upload')}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
          >
            <FileText className="h-4 w-4" />
            上传简历
          </button>
          <button
            onClick={startProjectDrillInterview}
            disabled={creatingSession}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
          >
            {creatingSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            专项答题
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-red-100 bg-red-50 p-4 text-red-700">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[390px_1fr]">
        <form onSubmit={handleSubmit} className="h-fit rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <Target className="h-5 w-5 text-slate-700" />
            <h2 className="text-base font-semibold text-slate-950">训练目标</h2>
          </div>

          <div className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">简历</span>
              <select
                value={form.resume_id}
                onChange={event => updateForm('resume_id', event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              >
                <option value="">选择已解析简历</option>
                {completedResumes.map(item => (
                  <option key={item.id} value={item.id}>
                    {item.filename}{item.latest_score !== null ? ` · ${item.latest_score} 分` : ''}
                  </option>
                ))}
              </select>
              {loadingResumes && <span className="mt-2 block text-xs text-slate-400">简历加载中...</span>}
              {!loadingResumes && resumeLoadError && (
                <span className="mt-2 block text-xs text-amber-600">简历列表暂不可用：{resumeLoadError}</span>
              )}
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">目标岗位</span>
              <input
                value={form.target_role}
                onChange={event => updateForm('target_role', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                placeholder="例如：Java 后端开发"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">项目名</span>
              <input
                value={form.project_name}
                onChange={event => updateForm('project_name', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                placeholder="可选，默认选择简历中的首个项目"
              />
            </label>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-1">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">目标公司</span>
                <input
                  value={form.target_company}
                  onChange={event => updateForm('target_company', event.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                  placeholder="可选"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">阶段</span>
                <select
                  value={form.level}
                  onChange={event => updateForm('level', event.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                >
                  {levelOptions.map(item => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">岗位 JD</span>
              <textarea
                value={form.jd_text}
                onChange={event => updateForm('jd_text', event.target.value)}
                className="min-h-28 w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                placeholder="可选，用于对齐岗位关键词"
              />
            </label>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            生成打磨方案
          </button>
        </form>

        {drill ? <DrillResult drill={drill} onStart={startProjectDrillInterview} creating={creatingSession} /> : <EmptyDrill />}
      </div>
    </div>
  );
}

function DrillResult({ drill, onStart, creating }: { drill: ProjectDrillDTO; onStart: () => void; creating: boolean }) {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap gap-2">
              <span className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600">
                {drill.resume_filename}
              </span>
              <span className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600">
                {drill.target_role}
              </span>
              <span className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600">
                {drill.level}
              </span>
            </div>
            <h2 className="mt-4 text-2xl font-semibold text-slate-950">{drill.selected_project.name}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">{drill.selected_project.reason}</p>
          </div>
          <div className="rounded-lg border border-amber-100 bg-amber-50 p-4 text-sm leading-6 text-amber-800 lg:max-w-md">
            {drill.risk_summary}
          </div>
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <button
            onClick={onStart}
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:bg-slate-300"
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            进入专项答题
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <ClipboardList className="h-5 w-5 text-primary-600" />
          <h2 className="text-base font-semibold text-slate-950">打磨质量判断</h2>
        </div>
        <div className="grid gap-4 lg:grid-cols-[160px_1fr]">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm text-slate-500">素材可用度</p>
            <p className="mt-2 text-4xl font-bold text-slate-950">{drill.quality.score}</p>
            <p className="mt-2 text-sm font-medium text-slate-700">{drill.quality.verdict}</p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-4">
              <div className="mb-2 text-sm font-semibold text-emerald-800">已具备</div>
              <div className="space-y-2">
                {drill.quality.checks.map(item => (
                  <p key={item} className="text-sm leading-6 text-emerald-800">- {item}</p>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50 p-4">
              <div className="mb-2 text-sm font-semibold text-amber-800">先补强</div>
              <div className="space-y-2">
                {drill.quality.suggestions.map(item => (
                  <p key={item} className="text-sm leading-6 text-amber-800">- {item}</p>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <FileText className="h-5 w-5 text-slate-700" />
          <h2 className="text-base font-semibold text-slate-950">项目讲法草稿</h2>
        </div>
        <p className="rounded-lg bg-slate-50 p-4 text-sm leading-7 text-slate-700">{drill.project_pitch}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">可证明的能力点</h3>
            <div className="space-y-2">
              {drill.proof_points.map(item => (
                <p key={item} className="rounded-lg border border-slate-200 p-3 text-sm leading-6 text-slate-600">{item}</p>
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">需要补齐的素材</h3>
            <div className="space-y-2">
              {drill.gap_fixes.map(item => (
                <p key={item} className="rounded-lg border border-slate-200 p-3 text-sm leading-6 text-slate-600">{item}</p>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <MessageSquareText className="h-5 w-5 text-primary-600" />
          <h2 className="text-base font-semibold text-slate-950">2 分钟讲法入口</h2>
        </div>
        <p className="rounded-lg bg-slate-50 p-4 text-sm leading-6 text-slate-700">{drill.warmup_prompt}</p>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-red-600" />
          <h2 className="text-base font-semibold text-slate-950">追问风险清单</h2>
        </div>
        <div className="space-y-4">
          {drill.questions.map((question, index) => (
            <QuestionCard key={`${question.category}-${question.question}`} question={question} index={index + 1} />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <ClipboardList className="h-5 w-5 text-emerald-600" />
          <h2 className="text-base font-semibold text-slate-950">练习清单</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {drill.practice_checklist.map(item => (
            <div key={item} className="flex gap-2 rounded-lg border border-slate-200 p-4 text-sm leading-6 text-slate-600">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function QuestionCard({ question, index }: { question: ProjectDrillQuestionDTO; index: number }) {
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
          {index}
        </span>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
          {question.category}
        </span>
      </div>
      <h3 className="text-base font-semibold leading-7 text-slate-950">{question.question}</h3>
      <p className="mt-2 text-sm leading-6 text-red-700">风险：{question.risk}</p>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <ListPanel title="回答框架" items={question.answer_framework} tone="slate" />
        <ListPanel title="加分信号" items={question.strong_answer_signals} tone="emerald" />
        <ListPanel title="扣分雷区" items={question.red_flags} tone="red" />
      </div>
    </div>
  );
}

function ListPanel({ title, items, tone }: { title: string; items: string[]; tone: 'slate' | 'emerald' | 'red' }) {
  const toneClass = {
    slate: 'bg-slate-50 text-slate-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    red: 'bg-red-50 text-red-700',
  }[tone];

  return (
    <div className={`rounded-lg p-3 ${toneClass}`}>
      <h4 className="mb-2 text-sm font-semibold">{title}</h4>
      <ul className="space-y-2">
        {items.map(item => (
          <li key={item} className="flex gap-2 text-sm leading-5">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-60" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EmptyDrill() {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 shadow-sm">
      <div className="flex max-w-xl flex-col gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100">
          <MessageSquareText className="h-6 w-6 text-slate-600" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-slate-950">等待生成项目打磨方案</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            选择已解析简历后，系统会先整理项目讲法、能力证据和待补素材，再生成追问风险清单。
          </p>
        </div>
      </div>
    </div>
  );
}
