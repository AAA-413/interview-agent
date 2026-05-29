import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2, Sparkles, AlertCircle, Zap, Target, TrendingUp, FileText, Bot, Layers3, Briefcase } from 'lucide-react';
import { skillApi } from '../api/skill';
import { resumeApi } from '../api/resume';
import type { SkillDTO } from '../types/interview';
import type { ResumeListItemDTO } from '../types/resume';

const difficulties = [
  { value: 'EASY', label: '初级', desc: '基础概念和简单场景', icon: '🌱', color: 'from-green-500 to-emerald-500' },
  { value: 'MEDIUM', label: '中级', desc: '综合应用和项目经验', icon: '🎯', color: 'from-blue-500 to-cyan-500' },
  { value: 'HARD', label: '高级', desc: '架构设计和深度技术', icon: '🚀', color: 'from-purple-500 to-pink-500' },
];

const interviewModes = [
  {
    value: 'STATIC',
    label: '模拟面试',
    desc: '一次生成固定题单，适合完整自测',
    icon: Layers3,
  },
  {
    value: 'COACH',
    label: '教练模式',
    desc: '4 个 topic，回答后给提示并支持同题重答',
    icon: Bot,
  },
  {
    value: 'STRICT',
    label: '严厉模式',
    desc: '4 个 topic，每题追问两轮，不给提示，验证真实水平',
    icon: Zap,
  },
];

const coachGenerationSteps = [
  '正在分析简历项目',
  '正在匹配 JD 重点',
  '正在选择面试主题',
  '正在准备第一题',
];

export default function InterviewHubPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const stateResumeId = (location.state as { resumeId?: number })?.resumeId;

  const [skills, setSkills] = useState<SkillDTO[]>([]);
  const [resumes, setResumes] = useState<ResumeListItemDTO[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<string>('');
  const [selectedResume, setSelectedResume] = useState<number | null>(stateResumeId || null);
  const [interviewMode, setInterviewMode] = useState<'STATIC' | 'COACH' | 'STRICT'>('STATIC');
  const [difficulty, setDifficulty] = useState('MEDIUM');
  const [questionCount, setQuestionCount] = useState(8);
  const [targetRole, setTargetRole] = useState('');
  const [jdText, setJdText] = useState('');
  const [creating, setCreating] = useState(false);
  const [generationStepIndex, setGenerationStepIndex] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([skillApi.listSkills(), resumeApi.listResumes()])
      .then(([skillsData, resumesData]) => {
        setSkills(skillsData);
        setResumes(resumesData);
        if (skillsData.length > 0 && !selectedSkill) {
          setSelectedSkill(skillsData[0].id);
        }
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!creating || interviewMode === 'STATIC') {
      setGenerationStepIndex(0);
      return;
    }

    const timer = window.setInterval(() => {
      setGenerationStepIndex(index => Math.min(index + 1, coachGenerationSteps.length - 1));
    }, 1200);

    return () => window.clearInterval(timer);
  }, [creating, interviewMode]);

  const handleStart = async () => {
    if (!selectedSkill) {
      setError('请选择面试方向');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const { interviewApi } = await import('../api/interview');
      if (interviewMode === 'COACH' || interviewMode === 'STRICT') {
        const session = await interviewApi.createDynamicSession({
          skill_id: selectedSkill,
          resume_id: selectedResume,
          difficulty,
          target_role: targetRole.trim() || null,
          jd_text: jdText.trim() || null,
          mode: interviewMode,
          topic_count: 4,
        });
        if (session.status === 'FAILED') {
          const generationError = session.plan_summary.generation_error;
          setError(typeof generationError === 'string' ? generationError : '面试计划生成失败，可以重试');
          return;
        }
        sessionStorage.setItem(`interview_mode_${session.session_id}`, 'dynamic');
        if (session.status !== 'PLANNING' && (!session.current_topic || !session.current_turn)) {
          setError('面试计划生成完成，但没有拿到第一题，请重试');
          return;
        }
        navigate('/interview', { state: { sessionId: session.session_id, mode: 'dynamic' } });
        return;
      }

      const session = await interviewApi.createSession({
        skill_id: selectedSkill,
        resume_id: selectedResume,
        difficulty,
        question_count: questionCount,
        jd_text: jdText.trim() || null,
        target_role: targetRole.trim() || null,
      });
      sessionStorage.setItem(`interview_mode_${session.session_id}`, 'static');
      navigate('/interview', { state: { sessionId: session.session_id, mode: 'static' } });
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建面试失败');
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh]">
        <div className="relative">
          <Loader2 className="w-12 h-12 text-primary-500 animate-spin" />
          <div className="absolute inset-0 w-12 h-12 bg-primary-500/20 rounded-full animate-ping" />
        </div>
        <p className="mt-4 text-sm text-slate-500 animate-pulse">准备面试环境...</p>
      </div>
    );
  }

  const selectedDifficulty = difficulties.find(d => d.value === difficulty) || difficulties[1];

  return (
    <div className="max-w-4xl mx-auto animate-in fade-in duration-500">
      <div className="mb-10 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-50 to-indigo-50 rounded-full mb-4">
          <Sparkles className="w-4 h-4 text-primary-600 animate-pulse" />
          <span className="text-sm font-medium text-primary-700">AI 智能面试</span>
        </div>
        <h1 className="text-4xl font-bold bg-gradient-to-r from-slate-900 via-slate-800 to-slate-700 bg-clip-text text-transparent mb-3">
          开始模拟面试
        </h1>
        <p className="text-slate-500 text-lg">选择面试方向和难度，AI 将为你生成个性化面试题目</p>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-3 p-4 bg-red-50 border border-red-100 text-red-600 rounded-xl shadow-sm animate-in slide-in-from-top duration-300">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm flex-1">{error}</span>
        </div>
      )}

      <div className="space-y-8">
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 shadow-lg">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 bg-gradient-to-br from-violet-500 to-purple-500 rounded-lg flex items-center justify-center">
              <Target className="w-4 h-4 text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">选择简历（可选）</h2>
          </div>
          <div className="grid grid-cols-1 gap-3">
            <button
              onClick={() => setSelectedResume(null)}
              className={`group p-5 rounded-xl border-2 text-left transition-all duration-300 ${
                selectedResume === null
                  ? 'border-primary-400 bg-gradient-to-r from-primary-50 to-indigo-50 shadow-md'
                  : 'border-slate-200 hover:border-slate-300 bg-white hover:shadow-sm'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
                  selectedResume === null ? 'bg-gradient-to-br from-primary-500 to-indigo-500' : 'bg-slate-100 group-hover:bg-slate-200'
                }`}>
                  <Zap className={`w-5 h-5 ${selectedResume === null ? 'text-white' : 'text-slate-500'}`} />
                </div>
                <div className="flex-1">
                  <span className="font-semibold text-slate-800">不使用简历</span>
                  <p className="text-sm text-slate-500 mt-0.5">AI 将根据面试方向生成通用题目</p>
                </div>
              </div>
            </button>
            {resumes.filter(r => r.analyze_status === 'COMPLETED').map(resume => (
              <button
                key={resume.id}
                onClick={() => setSelectedResume(resume.id)}
                className={`group p-5 rounded-xl border-2 text-left transition-all duration-300 ${
                  selectedResume === resume.id
                    ? 'border-primary-400 bg-gradient-to-r from-primary-50 to-indigo-50 shadow-md'
                    : 'border-slate-200 hover:border-slate-300 bg-white hover:shadow-sm'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`relative w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
                    selectedResume === resume.id ? 'bg-gradient-to-br from-primary-500 to-indigo-500' : 'bg-slate-100 group-hover:bg-slate-200'
                  }`}>
                    <span className={`text-lg ${selectedResume === resume.id ? 'text-white' : 'text-slate-500'}`}>📄</span>
                    {resume.latest_score !== null && (
                      <div className="absolute -top-1 -right-1 w-5 h-5 bg-gradient-to-br from-amber-400 to-orange-500 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-lg">
                        {resume.latest_score}
                      </div>
                    )}
                  </div>
                  <div className="flex-1">
                    <span className="font-semibold text-slate-800">{resume.filename}</span>
                    <p className="text-sm text-slate-500 mt-0.5">
                      评分: {resume.latest_score || '-'} · {new Date(resume.uploaded_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 shadow-lg">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 bg-gradient-to-br from-emerald-500 to-teal-500 rounded-lg flex items-center justify-center">
              <Target className="w-4 h-4 text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">选择面试方向</h2>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {skills.map(skill => (
              <button
                key={skill.id}
                onClick={() => setSelectedSkill(skill.id)}
                className={`group p-5 rounded-xl border-2 text-left transition-all duration-300 ${
                  selectedSkill === skill.id
                    ? 'border-primary-400 bg-gradient-to-r from-primary-50 to-indigo-50 shadow-md'
                    : 'border-slate-200 hover:border-slate-300 bg-white hover:shadow-sm'
                }`}
              >
                <span className="font-semibold text-slate-800 block mb-2">{skill.display_name || skill.name}</span>
                {skill.description && (
                  <p className="text-sm text-slate-500 line-clamp-2 mb-3">{skill.description}</p>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {skill.categories.slice(0, 3).map(c => (
                    <span key={c.key} className="px-2 py-1 bg-slate-100 text-slate-600 rounded-md text-xs font-medium">{c.label}</span>
                  ))}
                  {skill.categories.length > 3 && (
                    <span className="px-2 py-1 bg-slate-100 text-slate-500 rounded-md text-xs">+{skill.categories.length - 3}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 shadow-lg">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-blue-500 rounded-lg flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">选择面试模式</h2>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {interviewModes.map(mode => {
              const Icon = mode.icon;
              return (
                <button
                  key={mode.value}
                  onClick={() => setInterviewMode(mode.value as 'STATIC' | 'COACH' | 'STRICT')}
                  className={`group p-5 rounded-xl border-2 text-left transition-all duration-300 ${
                    interviewMode === mode.value
                      ? 'border-primary-400 bg-gradient-to-r from-primary-50 to-indigo-50 shadow-md'
                      : 'border-slate-200 hover:border-slate-300 bg-white hover:shadow-sm'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
                      interviewMode === mode.value ? 'bg-gradient-to-br from-primary-500 to-indigo-500' : 'bg-slate-100 group-hover:bg-slate-200'
                    }`}>
                      <Icon className={`w-5 h-5 ${interviewMode === mode.value ? 'text-white' : 'text-slate-500'}`} />
                    </div>
                    <div>
                      <span className="font-semibold text-slate-800">{mode.label}</span>
                      <p className="text-sm text-slate-500 mt-0.5">{mode.desc}</p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 shadow-lg">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 bg-gradient-to-br from-amber-500 to-orange-500 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">选择难度</h2>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {difficulties.map(d => (
              <button
                key={d.value}
                onClick={() => setDifficulty(d.value)}
                className={`group p-5 rounded-xl border-2 text-center transition-all duration-300 ${
                  difficulty === d.value
                    ? 'border-primary-400 bg-gradient-to-r from-primary-50 to-indigo-50 shadow-md'
                    : 'border-slate-200 hover:border-slate-300 bg-white hover:shadow-sm'
                }`}
              >
                <div className="text-3xl mb-2">{d.icon}</div>
                <span className="font-semibold text-slate-800 block mb-1">{d.label}</span>
                <p className="text-xs text-slate-500">{d.desc}</p>
              </button>
            ))}
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 shadow-lg">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 bg-gradient-to-br from-sky-500 to-cyan-500 rounded-lg flex items-center justify-center">
              <FileText className="w-4 h-4 text-white" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">岗位 JD（可选）</h2>
          </div>
          <div className="mb-4">
            <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
              <Briefcase className="w-4 h-4 text-slate-400" />
              目标岗位
            </label>
            <input
              value={targetRole}
              onChange={(event) => setTargetRole(event.target.value.slice(0, 120))}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-primary-400 focus:ring-4 focus:ring-primary-100"
              placeholder="例如：AI Agent 开发实习生、Java 后端开发"
            />
          </div>
          <textarea
            value={jdText}
            onChange={(event) => setJdText(event.target.value.slice(0, 10000))}
            rows={6}
            className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-primary-400 focus:ring-4 focus:ring-primary-100"
            placeholder="粘贴岗位职责、任职要求和加分项，AI 会优先生成与目标岗位相关的题目"
          />
          <div className="mt-2 flex justify-between text-xs text-slate-400">
            <span>不填则按所选面试方向生成通用题目</span>
            <span>{jdText.length}/10000</span>
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 shadow-lg">
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-gradient-to-br from-pink-500 to-rose-500 rounded-lg flex items-center justify-center">
                <span className="text-white text-sm font-bold">#</span>
              </div>
              <h2 className="text-lg font-semibold text-slate-900">题目数量</h2>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-3xl font-bold bg-gradient-to-r from-primary-600 to-indigo-600 bg-clip-text text-transparent">
                {interviewMode === 'COACH' || interviewMode === 'STRICT' ? 4 : questionCount}
              </span>
              <span className="text-sm text-slate-500">{interviewMode === 'COACH' || interviewMode === 'STRICT' ? 'topic' : '题'}</span>
            </div>
          </div>
          <input
            type="range"
            min={3}
            max={15}
            value={questionCount}
            onChange={(e) => setQuestionCount(parseInt(e.target.value))}
            disabled={interviewMode === 'COACH' || interviewMode === 'STRICT'}
            className="w-full h-2 bg-slate-200 rounded-full appearance-none cursor-pointer accent-primary-500"
          />
          <div className="flex justify-between text-xs text-slate-400 mt-2">
            {interviewMode === 'COACH' || interviewMode === 'STRICT' ? (
              interviewMode === 'STRICT' ? (
                <>
                  <span>固定 2 个项目 topic + 追问</span>
                  <span>1 个知识 + 1 个系统设计</span>
                </>
              ) : (
              <>
                <span>固定 2 个项目 topic</span>
                <span>1 个知识 topic + 1 个系统设计 topic</span>
              </>
            )) : (
              <>
                <span>3 题</span>
                <span>15 题</span>
              </>
            )}
          </div>
        </div>

        {creating && (interviewMode === 'COACH' || interviewMode === 'STRICT') && (
          <div className="rounded-2xl border border-primary-100 bg-primary-50/70 p-5">
            <div className="mb-4 flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-primary-600" />
              <span className="font-medium text-primary-800">{coachGenerationSteps[generationStepIndex]}</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">
              {coachGenerationSteps.map((step, index) => {
                const active = index === generationStepIndex;
                const done = index < generationStepIndex;
                return (
                  <div
                    key={step}
                    className={`h-2 rounded-full transition-colors ${
                      done ? 'bg-primary-500' : active ? 'bg-primary-300' : 'bg-white'
                    }`}
                    title={step}
                  />
                );
              })}
            </div>
          </div>
        )}

        <button
          onClick={handleStart}
          disabled={creating || !selectedSkill}
          className={`group relative w-full py-5 rounded-2xl font-semibold text-white text-lg transition-all duration-300 flex items-center justify-center gap-3 overflow-hidden ${
            creating || !selectedSkill
              ? 'bg-slate-300 cursor-not-allowed'
              : 'bg-gradient-to-r from-primary-600 via-primary-500 to-indigo-500 hover:shadow-2xl hover:shadow-primary-500/40 hover:scale-[1.02] active:scale-[0.98]'
          }`}
        >
          {!creating && !selectedSkill && (
            <div className="absolute inset-0 bg-gradient-to-r from-primary-500/10 to-indigo-500/10 animate-pulse" />
          )}
          {creating ? (
            <>
              <Loader2 className="w-6 h-6 animate-spin" />
              <span>{interviewMode === 'STRICT' ? '正在生成严厉面试计划...' : interviewMode === 'COACH' ? '正在生成教练计划...' : 'AI 正在生成题目...'}</span>
            </>
          ) : (
            <>
              <Sparkles className="w-6 h-6" />
              <span>{interviewMode === 'STRICT' ? '开始严厉模式' : interviewMode === 'COACH' ? '开始教练模式' : '开始面试'}</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
