import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Loader2, AlertCircle, Download, Play } from 'lucide-react';
import { resumeApi } from '../api/resume';
import type { ResumeDetailDTO } from '../types/resume';

export default function ResumeDetailPage() {
  const { resumeId } = useParams<{ resumeId: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ResumeDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!resumeId) return;
    const id = parseInt(resumeId, 10);
    resumeApi.getResume(id)
      .then(data => setDetail(data))
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [resumeId]);

  const handleExport = async () => {
    if (!resumeId) return;
    try {
      const blob = await resumeApi.exportPdf(parseInt(resumeId, 10));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `resume-analysis-${resumeId}.pdf`;
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
          <p className="text-red-500">{error || '简历不存在'}</p>
          <button onClick={() => navigate('/resumes')} className="mt-4 px-5 py-2 bg-primary-500 text-white rounded-xl">返回列表</button>
        </div>
      </div>
    );
  }

  const latestAnalysis = detail.analyses.length > 0 ? detail.analyses[0] : null;
  const statusMap: Record<string, { label: string; color: string }> = {
    PENDING: { label: '等待分析', color: 'bg-yellow-100 text-yellow-700' },
    PROCESSING: { label: '分析中', color: 'bg-blue-100 text-blue-700' },
    COMPLETED: { label: '已完成', color: 'bg-green-100 text-green-700' },
    FAILED: { label: '分析失败', color: 'bg-red-100 text-red-700' },
  };
  const status = statusMap[detail.analyze_status] || statusMap.PENDING;

  return (
    <div>
      <div className="flex items-center gap-3 mb-8">
        <button onClick={() => navigate('/resumes')} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-slate-900">{detail.filename}</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-slate-400">
            <span>{((detail.file_size || 0) / 1024).toFixed(1)} KB</span>
            <span>{new Date(detail.uploaded_at).toLocaleString()}</span>
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>{status.label}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={handleExport} className="flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl hover:bg-slate-200 text-sm">
            <Download className="w-4 h-4" /> 导出PDF
          </button>
          <button
            onClick={() => navigate('/interview-hub', { state: { resumeId: detail.id } })}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl hover:from-primary-700 hover:to-primary-600 text-sm shadow-lg shadow-primary-500/25"
          >
            <Play className="w-4 h-4" /> 开始面试
          </button>
        </div>
      </div>

      {detail.analyze_status === 'FAILED' && detail.analyze_error && (
        <div className="mb-6 p-4 bg-red-50 text-red-600 rounded-xl text-sm">
          <AlertCircle className="w-4 h-4 inline mr-2" />
          分析失败: {detail.analyze_error}
        </div>
      )}

      {latestAnalysis && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-2xl border border-slate-200 p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">综合评分</h2>
            <div className="flex items-center justify-center mb-6">
              <div className="relative w-32 h-32">
                <svg className="w-32 h-32 -rotate-90" viewBox="0 0 120 120">
                  <circle cx="60" cy="60" r="50" fill="none" stroke="#e2e8f0" strokeWidth="10" />
                  <circle cx="60" cy="60" r="50" fill="none" stroke="#6366f1" strokeWidth="10"
                    strokeDasharray={`${(latestAnalysis.overall_score || 0) * 3.14} 314`} strokeLinecap="round" />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-3xl font-bold text-primary-600">{latestAnalysis.overall_score || 0}</span>
                </div>
              </div>
            </div>
            <div className="space-y-3">
              {[
                { label: '内容完整性', score: latestAnalysis.content_score },
                { label: '结构清晰度', score: latestAnalysis.structure_score },
                { label: '技能匹配度', score: latestAnalysis.skill_match_score },
                { label: '表达专业性', score: latestAnalysis.expression_score },
                { label: '项目经验', score: latestAnalysis.project_score },
              ].map(item => (
                <div key={item.label} className="flex items-center gap-3">
                  <span className="text-sm text-slate-500 w-24">{item.label}</span>
                  <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-primary-500 to-primary-400 rounded-full" style={{ width: `${(item.score || 0)}%` }} />
                  </div>
                  <span className="text-sm font-medium text-slate-700 w-10 text-right">{item.score || 0}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-6">
            <div className="bg-white rounded-2xl border border-slate-200 p-6">
              <h2 className="text-lg font-semibold text-slate-900 mb-3">分析摘要</h2>
              <p className="text-slate-600 text-sm leading-relaxed">{latestAnalysis.summary}</p>
            </div>

            {latestAnalysis.strengths.length > 0 && (
              <div className="bg-white rounded-2xl border border-slate-200 p-6">
                <h2 className="text-lg font-semibold text-slate-900 mb-3">优势</h2>
                <ul className="space-y-2">
                  {latestAnalysis.strengths.map((s, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                      <span className="w-5 h-5 bg-green-100 text-green-600 rounded-full flex items-center justify-center text-xs flex-shrink-0 mt-0.5">✓</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {latestAnalysis.suggestions.length > 0 && (
              <div className="bg-white rounded-2xl border border-slate-200 p-6">
                <h2 className="text-lg font-semibold text-slate-900 mb-3">改进建议</h2>
                <ul className="space-y-3">
                  {latestAnalysis.suggestions.map((s, i) => (
                    <li key={i} className="text-sm">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          s.priority === '高' ? 'bg-red-100 text-red-600' :
                          s.priority === '中' ? 'bg-yellow-100 text-yellow-600' :
                          'bg-slate-100 text-slate-600'
                        }`}>{s.priority}</span>
                        <span className="text-slate-700 font-medium">{s.issue}</span>
                      </div>
                      <p className="text-slate-500 pl-12">{s.recommendation}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {!latestAnalysis && detail.analyze_status !== 'COMPLETED' && (
        <div className="text-center py-16">
          {detail.analyze_status === 'PROCESSING' ? (
            <>
              <Loader2 className="w-12 h-12 text-primary-500 animate-spin mx-auto mb-4" />
              <p className="text-slate-500">AI 正在分析简历...</p>
            </>
          ) : detail.analyze_status === 'PENDING' ? (
            <p className="text-slate-400">简历正在排队等待分析</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
