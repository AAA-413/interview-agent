import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Trash2, RefreshCw, Loader2, AlertCircle, Download, ChevronRight } from 'lucide-react';
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

  const statusMap: Record<string, { label: string; color: string }> = {
    PENDING: { label: '等待分析', color: 'bg-yellow-100 text-yellow-700' },
    PROCESSING: { label: '分析中', color: 'bg-blue-100 text-blue-700' },
    COMPLETED: { label: '已完成', color: 'bg-green-100 text-green-700' },
    FAILED: { label: '分析失败', color: 'bg-red-100 text-red-700' },
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">简历管理</h1>
          <p className="text-slate-500 mt-1">共 {resumes.length} 份简历</p>
        </div>
        <button
          onClick={() => navigate('/upload')}
          className="px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25 hover:from-primary-700 hover:to-primary-600 transition-all"
        >
          上传简历
        </button>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5" />
          <span className="text-sm">{error}</span>
          <button onClick={fetchResumes} className="ml-auto text-sm underline">重试</button>
        </div>
      )}

      {resumes.length === 0 ? (
        <div className="text-center py-20">
          <FileText className="w-16 h-16 text-slate-200 mx-auto mb-4" />
          <p className="text-slate-400 text-lg">暂无简历</p>
          <p className="text-slate-300 text-sm mt-2">上传第一份简历开始使用</p>
        </div>
      ) : (
        <div className="space-y-3">
          {resumes.map((resume) => {
            const status = statusMap[resume.analyze_status] || statusMap.PENDING;
            return (
              <div
                key={resume.id}
                className="bg-white rounded-xl border border-slate-200 p-5 hover:shadow-md transition-all duration-200 cursor-pointer"
                onClick={() => navigate(`/resumes/${resume.id}`)}
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-primary-50 rounded-xl flex items-center justify-center flex-shrink-0">
                    <FileText className="w-6 h-6 text-primary-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <h3 className="font-medium text-slate-900 truncate">{resume.filename}</h3>
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                        {status.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 mt-1 text-sm text-slate-400">
                      <span>{((resume.file_size || 0) / 1024).toFixed(1)} KB</span>
                      <span>{new Date(resume.uploaded_at).toLocaleDateString()}</span>
                      {resume.latest_score !== null && (
                        <span className="text-primary-600 font-medium">评分: {resume.latest_score}</span>
                      )}
                      {resume.interview_count > 0 && (
                        <span>{resume.interview_count} 次面试</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => handleReanalyze(resume.id)} className="p-2 text-slate-400 hover:text-primary-500 rounded-lg hover:bg-slate-50" title="重新分析">
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleExport(resume.id)} className="p-2 text-slate-400 hover:text-primary-500 rounded-lg hover:bg-slate-50" title="导出PDF">
                      <Download className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleDelete(resume.id)} className="p-2 text-slate-400 hover:text-red-500 rounded-lg hover:bg-slate-50" title="删除">
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-4 h-4 text-slate-300" />
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
