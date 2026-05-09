import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Trash2, RefreshCw, Loader2, AlertCircle, Download, ChevronRight, Upload, Star, MessageSquare } from 'lucide-react';
import { resumeApi } from '../api/resume';
import type { ResumeListItemDTO } from '../types/resume';

export default function ResumeListPage() {
  const navigate = useNavigate();
  const [resumes, setResumes] = useState<ResumeListItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchResumes = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await resumeApi.listResumes();
      setResumes(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchResumes(); }, []);

  // 当有简历正在分析时，轮询刷新状态
  const hasProcessing = resumes.some(r => r.analyze_status === 'PROCESSING' || r.analyze_status === 'PENDING');
  useEffect(() => {
    if (!hasProcessing) return;
    const timer = setInterval(() => {
      fetchResumes();
    }, 5000);
    return () => clearInterval(timer);
  }, [hasProcessing]);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这份简历吗？')) return;
    try {
      await resumeApi.deleteResume(id);
      setResumes(prev => prev.filter(r => r.id !== id));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleReanalyze = async (id: number) => {
    try {
      await resumeApi.reanalyze(id);
      alert('已提交重新分析请求');
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败');
    }
  };

  const handleExport = async (id: number) => {
    try {
      const blob = await resumeApi.exportPdf(id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `resume-analysis-${id}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : '导出失败');
    }
  };

  const statusMap: Record<string, { label: string; color: string; bgColor: string; icon: string }> = {
    PENDING: { label: '等待分析', color: 'text-amber-700', bgColor: 'bg-amber-50 border-amber-200', icon: '⏳' },
    PROCESSING: { label: '分析中', color: 'text-blue-700', bgColor: 'bg-blue-50 border-blue-200', icon: '⚡' },
    COMPLETED: { label: '已完成', color: 'text-emerald-700', bgColor: 'bg-emerald-50 border-emerald-200', icon: '✓' },
    FAILED: { label: '分析失败', color: 'text-red-700', bgColor: 'bg-red-50 border-red-200', icon: '✕' },
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh]">
        <div className="relative">
          <Loader2 className="w-12 h-12 text-primary-500 animate-spin" />
          <div className="absolute inset-0 w-12 h-12 bg-primary-500/20 rounded-full animate-ping" />
        </div>
        <p className="mt-4 text-sm text-slate-500 animate-pulse">加载简历...</p>
      </div>
    );
  }

  const completedCount = resumes.filter(r => r.analyze_status === 'COMPLETED').length;
  const avgScore = resumes.filter(r => r.latest_score !== null).reduce((sum, r) => sum + (r.latest_score || 0), 0) / resumes.filter(r => r.latest_score !== null).length || 0;

  return (
    <div className="animate-in fade-in duration-500">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-slate-900 via-slate-800 to-slate-700 bg-clip-text text-transparent">
            简历管理
          </h1>
          <div className="flex items-center gap-2 mt-2">
            <div className="flex items-center gap-1.5 px-3 py-1 bg-blue-50 rounded-full">
              <FileText className="w-3.5 h-3.5 text-blue-600" />
              <span className="text-sm font-medium text-blue-700">{resumes.length} 份简历</span>
            </div>
            {completedCount > 0 && (
              <div className="flex items-center gap-1.5 px-3 py-1 bg-emerald-50 rounded-full">
                <Star className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-sm font-medium text-emerald-700">平均 {avgScore.toFixed(0)} 分</span>
              </div>
            )}
          </div>
        </div>
        <button
          onClick={() => navigate('/upload')}
          className="group relative px-6 py-3 bg-gradient-to-r from-blue-600 via-blue-500 to-cyan-500 text-white rounded-xl font-medium shadow-lg shadow-blue-500/30 hover:shadow-xl hover:shadow-blue-500/40 transition-all duration-300 hover:scale-105"
        >
          <div className="absolute inset-0 bg-gradient-to-r from-white/20 to-transparent rounded-xl opacity-0 group-hover:opacity-100 transition-opacity" />
          <div className="relative flex items-center gap-2">
            <Upload className="w-4 h-4" />
            上传简历
          </div>
        </button>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-3 p-4 bg-red-50 border border-red-100 text-red-600 rounded-xl shadow-sm animate-in slide-in-from-top duration-300">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm flex-1">{error}</span>
          <button onClick={fetchResumes} className="text-sm font-medium underline hover:no-underline">重试</button>
        </div>
      )}

      {resumes.length === 0 ? (
        <div className="text-center py-24 bg-white/60 backdrop-blur-sm rounded-2xl border border-slate-200/60 shadow-xl animate-in zoom-in duration-500">
          <div className="relative inline-block">
            <FileText className="w-20 h-20 text-slate-200 mx-auto mb-6" />
            <div className="absolute -top-2 -right-2 w-8 h-8 bg-gradient-to-br from-blue-500 to-cyan-500 rounded-full flex items-center justify-center shadow-lg">
              <Upload className="w-4 h-4 text-white" />
            </div>
          </div>
          <h3 className="text-xl font-semibold text-slate-700 mb-2">还没有简历</h3>
          <p className="text-slate-400 text-sm mb-6">上传简历后即可开始 AI 面试模拟</p>
          <button
            onClick={() => navigate('/upload')}
            className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-cyan-500 text-white rounded-xl font-medium hover:shadow-lg hover:scale-105 transition-all duration-300"
          >
            <Upload className="w-4 h-4" /> 上传第一份简历
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {resumes.map((resume, index) => {
            const status = statusMap[resume.analyze_status] || statusMap.PENDING;
            return (
              <div
                key={resume.id}
                className="group bg-white/80 backdrop-blur-sm rounded-2xl border border-slate-200/60 p-6 hover:shadow-xl hover:border-blue-200/60 transition-all duration-300 cursor-pointer animate-in slide-in-from-bottom"
                style={{ animationDelay: `${index * 50}ms` }}
                onClick={() => navigate(`/resumes/${resume.id}`)}
              >
                <div className="flex items-start gap-5">
                  <div className="relative w-14 h-14 bg-gradient-to-br from-blue-50 to-cyan-50 rounded-2xl flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform duration-300">
                    <FileText className="w-7 h-7 text-blue-500" />
                    {resume.latest_score !== null && (
                      <div className="absolute -top-1 -right-1 w-8 h-8 bg-gradient-to-br from-amber-400 to-orange-500 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-lg">
                        {resume.latest_score}
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-3 mb-2">
                      <h3 className="font-semibold text-slate-900 text-lg truncate flex-1 group-hover:text-blue-600 transition-colors">
                        {resume.filename}
                      </h3>
                      <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${status.bgColor} ${status.color}`}>
                        <span>{status.icon}</span>
                        <span>{status.label}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-slate-500 flex-wrap">
                      <span className="inline-flex items-center gap-1">
                        <div className="w-1 h-1 bg-slate-300 rounded-full" />
                        {((resume.file_size || 0) / 1024).toFixed(1)} KB
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <div className="w-1 h-1 bg-slate-300 rounded-full" />
                        {new Date(resume.uploaded_at).toLocaleDateString()}
                      </span>
                      {resume.interview_count > 0 && (
                        <span className="inline-flex items-center gap-1.5 text-primary-600 font-medium">
                          <MessageSquare className="w-3.5 h-3.5" />
                          {resume.interview_count} 次面试
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => handleReanalyze(resume.id)} className="p-2.5 text-slate-400 hover:text-blue-500 hover:bg-blue-50 rounded-xl transition-all duration-200" title="重新分析">
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleExport(resume.id)} className="p-2.5 text-slate-400 hover:text-emerald-500 hover:bg-emerald-50 rounded-xl transition-all duration-200" title="导出PDF">
                      <Download className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleDelete(resume.id)} className="p-2.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-xl transition-all duration-200" title="删除">
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-blue-500 group-hover:translate-x-1 transition-all duration-300" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
