import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2, Sparkles, AlertCircle } from 'lucide-react';
import { skillApi } from '../api/skill';
import { resumeApi } from '../api/resume';
import type { SkillDTO } from '../types/interview';
import type { ResumeListItemDTO } from '../types/resume';

const difficulties = [
  { value: 'EASY', label: '初级', desc: '基础概念和简单场景' },
  { value: 'MEDIUM', label: '中级', desc: '综合应用和项目经验' },
  { value: 'HARD', label: '高级', desc: '架构设计和深度技术' },
];

export default function InterviewHubPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const stateResumeId = (location.state as { resumeId?: number })?.resumeId;

  const [skills, setSkills] = useState<SkillDTO[]>([]);
  const [resumes, setResumes] = useState<ResumeListItemDTO[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<string>('');
  const [selectedResume, setSelectedResume] = useState<number | null>(stateResumeId || null);
  const [difficulty, setDifficulty] = useState('MEDIUM');
  const [questionCount, setQuestionCount] = useState(8);
  const [creating, setCreating] = useState(false);
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

  const handleStart = async () => {
    if (!selectedSkill) {
      setError('请选择面试方向');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const { interviewApi } = await import('../api/interview');
      const session = await interviewApi.createSession({
        skill_id: selectedSkill,
        resume_id: selectedResume,
        difficulty,
        question_count: questionCount,
      });
      navigate('/interview', { state: { sessionId: session.session_id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建面试失败');
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">开始模拟面试</h1>
        <p className="text-slate-500 mt-2">选择面试方向和难度，AI 将为你生成个性化面试题目</p>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="space-y-8">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 mb-4">选择简历（可选）</h2>
          <div className="grid grid-cols-1 gap-3">
            <button
              onClick={() => setSelectedResume(null)}
              className={`p-4 rounded-xl border text-left transition-all ${
                selectedResume === null
                  ? 'border-primary-400 bg-primary-50 ring-2 ring-primary-100'
                  : 'border-slate-200 hover:border-slate-300 bg-white'
              }`}
            >
              <span className="font-medium text-slate-700">不使用简历</span>
              <p className="text-sm text-slate-400 mt-1">AI 将根据面试方向生成通用题目</p>
            </button>
            {resumes.filter(r => r.analyze_status === 'COMPLETED').map(resume => (
              <button
                key={resume.id}
                onClick={() => setSelectedResume(resume.id)}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedResume === resume.id
                    ? 'border-primary-400 bg-primary-50 ring-2 ring-primary-100'
                    : 'border-slate-200 hover:border-slate-300 bg-white'
                }`}
              >
                <span className="font-medium text-slate-700">{resume.filename}</span>
                <p className="text-sm text-slate-400 mt-1">
                  评分: {resume.latest_score || '-'} · {new Date(resume.uploaded_at).toLocaleDateString()}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-lg font-semibold text-slate-900 mb-4">选择面试方向</h2>
          <div className="grid grid-cols-2 gap-3">
            {skills.map(skill => (
              <button
                key={skill.id}
                onClick={() => setSelectedSkill(skill.id)}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedSkill === skill.id
                    ? 'border-primary-400 bg-primary-50 ring-2 ring-primary-100'
                    : 'border-slate-200 hover:border-slate-300 bg-white'
                }`}
              >
                <span className="font-medium text-slate-700">{skill.display_name || skill.name}</span>
                {skill.description && (
                  <p className="text-sm text-slate-400 mt-1 line-clamp-2">{skill.description}</p>
                )}
                <div className="flex flex-wrap gap-1 mt-2">
                  {skill.categories.slice(0, 3).map(c => (
                    <span key={c.key} className="px-2 py-0.5 bg-slate-100 text-slate-500 rounded text-xs">{c.label}</span>
                  ))}
                  {skill.categories.length > 3 && (
                    <span className="px-2 py-0.5 bg-slate-100 text-slate-400 rounded text-xs">+{skill.categories.length - 3}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-lg font-semibold text-slate-900 mb-4">选择难度</h2>
          <div className="grid grid-cols-3 gap-3">
            {difficulties.map(d => (
              <button
                key={d.value}
                onClick={() => setDifficulty(d.value)}
                className={`p-4 rounded-xl border text-center transition-all ${
                  difficulty === d.value
                    ? 'border-primary-400 bg-primary-50 ring-2 ring-primary-100'
                    : 'border-slate-200 hover:border-slate-300 bg-white'
                }`}
              >
                <span className="font-medium text-slate-700">{d.label}</span>
                <p className="text-xs text-slate-400 mt-1">{d.desc}</p>
              </button>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-lg font-semibold text-slate-900 mb-4">题目数量</h2>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={3}
              max={15}
              value={questionCount}
              onChange={(e) => setQuestionCount(parseInt(e.target.value))}
              className="flex-1 accent-primary-500"
            />
            <span className="text-lg font-bold text-primary-600 w-8 text-center">{questionCount}</span>
          </div>
        </div>

        <button
          onClick={handleStart}
          disabled={creating || !selectedSkill}
          className={`w-full py-4 rounded-xl font-medium text-white text-lg transition-all duration-200 flex items-center justify-center gap-2 ${
            creating || !selectedSkill
              ? 'bg-slate-300 cursor-not-allowed'
              : 'bg-gradient-to-r from-primary-600 to-primary-500 hover:from-primary-700 hover:to-primary-600 shadow-lg shadow-primary-500/25'
          }`}
        >
          {creating ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              AI 正在生成题目...
            </>
          ) : (
            <>
              <Sparkles className="w-5 h-5" />
              开始面试
            </>
          )}
        </button>
      </div>
    </div>
  );
}
