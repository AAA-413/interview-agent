import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  BookOpenCheck,
  ClipboardCheck,
  Database,
  FileText,
  Loader2,
  MessageSquareText,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  Upload,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { interviewApi } from '../api/interview';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import { resumeApi } from '../api/resume';
import { skillApi } from '../api/skill';
import { demoApi } from '../api/demo';
import type { SessionListItemDTO, SkillDTO } from '../types/interview';
import type { KnowledgeBaseListItemDTO } from '../types/knowledgeBase';
import type { ResumeListItemDTO } from '../types/resume';

type DashboardData = {
  resumes: ResumeListItemDTO[];
  sessions: SessionListItemDTO[];
  knowledgeBases: KnowledgeBaseListItemDTO[];
  skills: SkillDTO[];
};

const emptyData: DashboardData = {
  resumes: [],
  sessions: [],
  knowledgeBases: [],
  skills: [],
};

const marketSegments = [
  { title: '个人求职', value: '简历诊断 + 模拟面试', tone: 'border-blue-100 bg-blue-50 text-blue-700' },
  { title: '高校就业', value: '批量训练 + 能力画像', tone: 'border-emerald-100 bg-emerald-50 text-emerald-700' },
  { title: '培训机构', value: '学员陪跑 + 复盘报告', tone: 'border-amber-100 bg-amber-50 text-amber-700' },
  { title: '企业内推', value: '岗位匹配 + 面试预演', tone: 'border-rose-100 bg-rose-50 text-rose-700' },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardData>(emptyData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [seedingDemo, setSeedingDemo] = useState(false);

  const fetchDashboard = async () => {
    setLoading(true);
    setError('');
    const [resumesResult, sessionsResult, kbResult, skillsResult] = await Promise.allSettled([
      resumeApi.listResumes(),
      interviewApi.listSessions(),
      knowledgeBaseApi.listKnowledgeBases(),
      skillApi.listSkills(),
    ]);

    setData({
      resumes: resumesResult.status === 'fulfilled' ? resumesResult.value : [],
      sessions: sessionsResult.status === 'fulfilled' ? sessionsResult.value : [],
      knowledgeBases: kbResult.status === 'fulfilled' ? kbResult.value : [],
      skills: skillsResult.status === 'fulfilled' ? skillsResult.value : [],
    });

    const firstError = [resumesResult, sessionsResult, kbResult, skillsResult].find(result => result.status === 'rejected');
    setError(firstError && firstError.status === 'rejected' && firstError.reason instanceof Error ? firstError.reason.message : '');
    setLoading(false);
  };

  useEffect(() => {
    fetchDashboard();
  }, []);

  const handleSeedDemo = async () => {
    if (seedingDemo) return;
    setSeedingDemo(true);
    setError('');
    try {
      const result = await demoApi.seedDemoData();
      navigate(result.interview_report_path);
    } catch (err) {
      setError(err instanceof Error ? err.message : '演示数据生成失败');
    } finally {
      setSeedingDemo(false);
    }
  };

  const stats = useMemo(() => {
    const completedResumes = data.resumes.filter(item => item.analyze_status === 'COMPLETED');
    const scoredResumes = data.resumes.filter(item => item.latest_score !== null);
    const avgResumeScore = scoredResumes.length
      ? Math.round(scoredResumes.reduce((sum, item) => sum + (item.latest_score || 0), 0) / scoredResumes.length)
      : 0;
    const completedSessions = data.sessions.filter(item => item.status === 'COMPLETED' || item.status === 'EVALUATED');
    const readyKnowledgeBases = data.knowledgeBases.filter(item => item.index_status === 'COMPLETED');

    const readinessScore =
      Math.min(completedResumes.length, 1) * 28 +
      Math.min(completedSessions.length, 1) * 24 +
      Math.min(readyKnowledgeBases.length, 1) * 18 +
      Math.min(data.skills.length, 1) * 15 +
      (avgResumeScore >= 70 ? 15 : Math.round(avgResumeScore * 0.18));

    return {
      completedResumes,
      completedSessions,
      readyKnowledgeBases,
      avgResumeScore,
      readinessScore: Math.min(100, readinessScore),
    };
  }, [data]);

  const nextAction = useMemo(() => {
    if (stats.completedResumes.length === 0) {
      return {
        title: '先上传一份简历',
        detail: '让系统建立候选人画像，后续诊断、项目深挖和模拟面试会更精准。',
        label: '上传简历',
        path: '/upload',
        icon: Upload,
      };
    }
    if (stats.completedSessions.length === 0) {
      return {
        title: '生成第一份面试诊断',
        detail: '把目标岗位、公司和 JD 放进来，得到当天最该训练的题型。',
        label: '开始诊断',
        path: '/diagnosis',
        icon: ClipboardCheck,
      };
    }
    return {
      title: '生成个人训练计划',
      detail: '用评分校准找出低可信题和薄弱维度，把下一周练习排清楚。',
      label: '查看训练计划',
      path: '/training-plan',
      icon: TrendingUp,
    };
  }, [stats.completedResumes.length, stats.completedSessions.length]);

  if (loading) {
    return (
      <div className="flex min-h-[55vh] flex-col items-center justify-center">
        <Loader2 className="h-10 w-10 animate-spin text-primary-500" />
        <p className="mt-4 text-sm text-slate-500">正在整理工作台...</p>
      </div>
    );
  }

  const NextIcon = nextAction.icon;

  return (
    <div className="animate-in fade-in duration-500">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1 text-sm font-medium text-slate-700 shadow-sm">
            <Sparkles className="h-4 w-4 text-primary-600" />
            OfferPilot 工作台
          </div>
          <h1 className="text-3xl font-bold text-slate-950">从简历到 Offer 的训练闭环</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            面向求职者、高校就业中心和培训机构，把简历诊断、项目深挖、知识库和模拟面试组织成可交付的训练产品。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={handleSeedDemo}
            disabled={seedingDemo}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-medium text-emerald-700 shadow-sm transition hover:border-emerald-300 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {seedingDemo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            演示模式
          </button>
          <button
            onClick={fetchDashboard}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
          >
            <RefreshCw className="h-4 w-4" />
            刷新
          </button>
          <button
            onClick={() => navigate('/diagnosis')}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
          >
            <Play className="h-4 w-4" />
            开始训练
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-amber-100 bg-amber-50 p-4 text-amber-700">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span className="text-sm">部分数据暂不可用：{error}</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="简历资产" value={data.resumes.length} helper={`${stats.completedResumes.length} 份已完成分析`} icon={FileText} />
        <MetricCard label="平均简历分" value={stats.avgResumeScore || '-'} helper="用于判断改稿空间" icon={Target} />
        <MetricCard label="面试记录" value={data.sessions.length} helper={`${stats.completedSessions.length} 次已完成`} icon={MessageSquareText} />
        <MetricCard label="知识库" value={data.knowledgeBases.length} helper={`${stats.readyKnowledgeBases.length} 个可检索`} icon={Database} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">商业化交付路径</h2>
              <p className="mt-1 text-sm text-slate-500">把一次体验拆成清晰步骤，方便演示、成交和复购。</p>
            </div>
            <div className="rounded-lg bg-slate-950 px-3 py-2 text-right text-white">
              <div className="text-2xl font-bold">{stats.readinessScore}</div>
              <div className="text-[11px] text-slate-300">准备度</div>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-5">
            <FlowStep active={data.resumes.length > 0} title="简历导入" detail="建立画像" />
            <FlowStep active={stats.completedResumes.length > 0} title="面试诊断" detail="定位差距" />
            <FlowStep active={data.sessions.length > 0} title="模拟面试" detail="实战问答" />
            <FlowStep active={stats.readyKnowledgeBases.length > 0} title="知识库" detail="补齐材料" />
            <FlowStep active={stats.completedSessions.length > 0} title="复盘报告" detail="形成闭环" />
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
              <NextIcon className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-950">{nextAction.title}</h2>
              <p className="text-sm text-slate-500">下一步建议</p>
            </div>
          </div>
          <p className="mb-5 text-sm leading-6 text-slate-600">{nextAction.detail}</p>
          <button
            onClick={() => navigate(nextAction.path)}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700"
          >
            {nextAction.label}
            <ArrowRight className="h-4 w-4" />
          </button>
        </section>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-slate-700" />
            <h2 className="text-lg font-semibold text-slate-950">可售卖场景</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {marketSegments.map(segment => (
              <div key={segment.title} className={`rounded-lg border px-4 py-3 ${segment.tone}`}>
                <div className="text-sm font-semibold">{segment.title}</div>
                <div className="mt-1 text-xs opacity-80">{segment.value}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <BookOpenCheck className="h-5 w-5 text-slate-700" />
              <h2 className="text-lg font-semibold text-slate-950">能力库存</h2>
            </div>
            <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
              {data.skills.length} 个方向
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {data.skills.slice(0, 6).map(skill => (
              <div key={skill.id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                <div className="truncate text-sm font-medium text-slate-800">{skill.display_name || skill.name}</div>
                <div className="mt-1 text-xs text-slate-500">{skill.categories.length} 个考察模块</div>
              </div>
            ))}
            {data.skills.length === 0 && (
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                面试方向暂未加载，稍后刷新即可。
              </div>
            )}
          </div>
        </section>
      </div>
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

function FlowStep({ active, title, detail }: { active: boolean; title: string; detail: string }) {
  return (
    <div className={`rounded-lg border p-3 ${active ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
      <div className={`mb-2 h-2 w-10 rounded-full ${active ? 'bg-emerald-500' : 'bg-slate-300'}`} />
      <div className={`text-sm font-semibold ${active ? 'text-emerald-800' : 'text-slate-700'}`}>{title}</div>
      <div className="mt-1 text-xs text-slate-500">{detail}</div>
    </div>
  );
}
