import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  BookOpenCheck,
  Brain,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
  Target,
} from 'lucide-react';
import { interviewApi } from '../api/interview';
import { resumeApi } from '../api/resume';
import type { InterviewDiagnosisDTO, DiagnosisItemDTO, PracticeTaskDTO } from '../types/diagnosis';
import type { ResumeListItemDTO } from '../types/resume';

const levelOptions = ['校招', '实习', '转岗/0-1 年', '转岗/1-3 年'];

const severityStyle: Record<string, string> = {
  HIGH: 'bg-red-50 text-red-700 border-red-100',
  MEDIUM: 'bg-amber-50 text-amber-700 border-amber-100',
  LOW: 'bg-emerald-50 text-emerald-700 border-emerald-100',
};

const severityLabel: Record<string, string> = {
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
};

type DiagnosisForm = {
  target_role: string;
  target_company: string;
  level: string;
  resume_id: string;
  jd_text: string;
};

export default function InterviewDiagnosisPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const stateResumeId = (location.state as { resumeId?: number } | null)?.resumeId;

  const [resumes, setResumes] = useState<ResumeListItemDTO[]>([]);
  const [loadingResumes, setLoadingResumes] = useState(true);
  const [resumeLoadError, setResumeLoadError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [diagnosis, setDiagnosis] = useState<InterviewDiagnosisDTO | null>(null);
  const [form, setForm] = useState<DiagnosisForm>({
    target_role: 'Java 后端开发',
    target_company: '',
    level: '校招',
    resume_id: stateResumeId ? String(stateResumeId) : '',
    jd_text: '',
  });

  useEffect(() => {
    resumeApi.listResumes()
      .then(data => {
        setResumes(data);
        if (!stateResumeId) {
          const firstCompleted = data.find(item => item.analyze_status === 'COMPLETED');
          if (firstCompleted) {
            setForm(prev => ({ ...prev, resume_id: String(firstCompleted.id) }));
          }
        }
      })
      .catch(err => setResumeLoadError(err instanceof Error ? err.message : '简历列表加载失败'))
      .finally(() => setLoadingResumes(false));
  }, [stateResumeId]);

  const completedResumes = useMemo(
    () => resumes.filter(item => item.analyze_status === 'COMPLETED'),
    [resumes]
  );

  const selectedResume = useMemo(
    () => resumes.find(item => String(item.id) === form.resume_id),
    [form.resume_id, resumes]
  );

  const updateForm = (key: keyof DiagnosisForm, value: string) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.target_role.trim()) {
      setError('请先填写目标岗位');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      const result = await interviewApi.createDiagnosis({
        resume_id: form.resume_id ? Number(form.resume_id) : null,
        target_role: form.target_role.trim(),
        target_company: form.target_company.trim() || null,
        level: form.level,
        jd_text: form.jd_text.trim() || null,
      });
      setDiagnosis(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '诊断失败');
    } finally {
      setSubmitting(false);
    }
  };

  const goTask = (task: PracticeTaskDTO) => {
    if (!task.action_path) return;
    if (task.action_path.startsWith('/project-drill') && diagnosis) {
      const params = new URLSearchParams();
      if (diagnosis.resume_id) params.set('resumeId', String(diagnosis.resume_id));
      params.set('targetRole', diagnosis.target_role);
      if (diagnosis.target_company) params.set('targetCompany', diagnosis.target_company);
      params.set('level', diagnosis.level);
      navigate(`/project-drill?${params.toString()}`);
      return;
    }
    navigate(task.action_path);
  };

  const startInterview = () => {
    navigate('/interview-hub', {
      state: { resumeId: diagnosis?.resume_id || selectedResume?.id },
    });
  };

  return (
    <div className="animate-in fade-in duration-500">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
            <ClipboardCheck className="h-4 w-4" />
            第一阶段
          </div>
          <h1 className="text-3xl font-bold text-slate-950">面试诊断</h1>
          <p className="mt-2 text-sm text-slate-500">{diagnosis?.weakness_summary || '定位准备度、简历追问风险和今日训练任务'}</p>
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
            onClick={() => {
              if (diagnosis?.resume_id || selectedResume?.id) {
                const params = new URLSearchParams();
                params.set('resumeId', String(diagnosis?.resume_id || selectedResume?.id));
                params.set('targetRole', diagnosis?.target_role || form.target_role);
                params.set('level', diagnosis?.level || form.level);
                if (diagnosis?.target_company || form.target_company) {
                  params.set('targetCompany', diagnosis?.target_company || form.target_company);
                }
                navigate(`/project-drill?${params.toString()}`);
                return;
              }
              startInterview();
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
          >
            <Play className="h-4 w-4" />
            项目深挖
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
            <h2 className="text-base font-semibold text-slate-950">目标信息</h2>
          </div>

          <div className="space-y-4">
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
              <span className="mb-1.5 block text-sm font-medium text-slate-700">目标公司</span>
              <input
                value={form.target_company}
                onChange={event => updateForm('target_company', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                placeholder="可选"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">经验阶段</span>
              <select
                value={form.level}
                onChange={event => updateForm('level', event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              >
                {levelOptions.map(item => <option key={item}>{item}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">简历</span>
              <select
                value={form.resume_id}
                onChange={event => updateForm('resume_id', event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              >
                <option value="">不选择简历</option>
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
              {!loadingResumes && resumes.length > 0 && completedResumes.length === 0 && (
                <span className="mt-2 block text-xs text-amber-600">当前没有已完成解析的简历</span>
              )}
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">岗位 JD</span>
              <textarea
                value={form.jd_text}
                onChange={event => updateForm('jd_text', event.target.value)}
                className="min-h-36 w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                placeholder="粘贴岗位职责和任职要求"
              />
            </label>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            生成诊断
          </button>
        </form>

        {diagnosis ? (
          <div className="space-y-6">
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="grid gap-5 lg:grid-cols-[220px_1fr]">
                <div className="rounded-lg border border-slate-100 bg-slate-50 p-5">
                  <div className="text-sm font-medium text-slate-500">准备度</div>
                  <div className="mt-3 flex items-end gap-2">
                    <span className="text-5xl font-bold text-slate-950">{diagnosis.readiness_score}</span>
                    <span className="pb-2 text-sm text-slate-500">/ 100</span>
                  </div>
                  <div className="mt-3 inline-flex rounded-full bg-slate-900 px-3 py-1 text-sm font-medium text-white">
                    {diagnosis.readiness_level}
                  </div>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-200">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-amber-500 to-red-500"
                      style={{ width: `${diagnosis.readiness_score}%` }}
                    />
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap gap-2">
                    {diagnosis.diagnosis_basis.map(item => (
                      <span key={item} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
                        {item}
                      </span>
                    ))}
                  </div>
                  <h2 className="mt-5 text-xl font-semibold text-slate-950">
                    {diagnosis.target_company ? `${diagnosis.target_company} · ` : ''}{diagnosis.target_role}
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{diagnosis.score_explanation}</p>
                  <div className="mt-5 flex flex-wrap gap-3">
                    {diagnosis.next_actions.map(task => (
                      <button
                        key={task.title}
                        onClick={() => goTask(task)}
                        className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700"
                      >
                        {task.title}
                        <ArrowRight className="h-4 w-4" />
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            <div className="grid gap-6 lg:grid-cols-2">
              <ResultBlock
                icon={<ShieldAlert className="h-5 w-5 text-red-600" />}
                title="关键薄弱项"
                items={diagnosis.weaknesses}
              />
              <ResultBlock
                icon={<Brain className="h-5 w-5 text-primary-600" />}
                title="知识缺口"
                items={diagnosis.knowledge_gaps}
              />
            </div>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <BookOpenCheck className="h-5 w-5 text-emerald-600" />
                <h2 className="text-base font-semibold text-slate-950">今日训练</h2>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {diagnosis.today_tasks.map(task => (
                  <button
                    key={task.title}
                    onClick={() => goTask(task)}
                    className="rounded-lg border border-slate-200 p-4 text-left transition hover:border-emerald-200 hover:bg-emerald-50"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="font-medium text-slate-950">{task.title}</h3>
                      <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
                        {task.minutes} 分钟
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{task.deliverable}</p>
                  </button>
                ))}
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <AlertCircle className="h-5 w-5 text-amber-600" />
                <h2 className="text-base font-semibold text-slate-950">简历追问风险</h2>
              </div>
              <div className="space-y-3">
                {diagnosis.resume_risks.map(item => (
                  <div key={item.question} className="rounded-lg border border-slate-200 p-4">
                    <h3 className="text-sm font-semibold leading-6 text-slate-950">{item.question}</h3>
                    <p className="mt-2 text-sm leading-6 text-red-700">风险：{item.risk}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-600">回答抓手：{item.answer_hint}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-slate-700" />
                <h2 className="text-base font-semibold text-slate-950">7 天计划</h2>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {diagnosis.seven_day_plan.map(day => (
                  <div key={day.day} className="rounded-lg border border-slate-200 p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
                        {day.day}
                      </span>
                      <h3 className="font-semibold text-slate-950">{day.theme}</h3>
                    </div>
                    <ul className="space-y-2">
                      {day.tasks.map(task => (
                        <li key={task} className="flex gap-2 text-sm leading-5 text-slate-600">
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                          <span>{task}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>
          </div>
        ) : (
          <EmptyDiagnosis selectedResume={selectedResume} />
        )}
      </div>
    </div>
  );
}

function ResultBlock({ icon, title, items }: { icon: ReactNode; title: string; items: DiagnosisItemDTO[] }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      </div>
      <div className="space-y-3">
        {items.map(item => (
          <div key={item.title} className="rounded-lg border border-slate-200 p-4">
            <div className="mb-2 flex items-start justify-between gap-3">
              <h3 className="text-sm font-semibold leading-6 text-slate-950">{item.title}</h3>
              <span className={`shrink-0 rounded-full border px-2 py-1 text-xs font-semibold ${severityStyle[item.severity] || severityStyle.MEDIUM}`}>
                {severityLabel[item.severity] || item.severity}
              </span>
            </div>
            <p className="text-sm leading-6 text-slate-600">{item.evidence}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{item.impact}</p>
            <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">{item.action}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function EmptyDiagnosis({ selectedResume }: { selectedResume?: ResumeListItemDTO }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 shadow-sm">
      <div className="flex max-w-xl flex-col gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100">
          <ClipboardCheck className="h-6 w-6 text-slate-600" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-slate-950">等待生成诊断</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {selectedResume ? `当前选择：${selectedResume.filename}` : '可先选择一份已解析简历，也可以只按岗位生成基础诊断。'}
          </p>
        </div>
      </div>
    </div>
  );
}
