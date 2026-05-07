import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { LogOut, FileText, MessageSquare, BarChart3, Upload, BookOpen, Database, Sparkles } from 'lucide-react';
import { authApi } from '../api/auth';

const navItems = [
  { path: '/resumes', label: '简历管理', icon: FileText, gradient: 'from-blue-500 to-cyan-500' },
  { path: '/upload', label: '上传简历', icon: Upload, gradient: 'from-violet-500 to-purple-500' },
  { path: '/knowledgebases', label: '知识库管理', icon: Database, gradient: 'from-emerald-500 to-teal-500' },
  { path: '/knowledgebases/upload', label: '上传知识库', icon: BookOpen, gradient: 'from-amber-500 to-orange-500' },
  { path: '/interviews', label: '面试记录', icon: MessageSquare, gradient: 'from-pink-500 to-rose-500' },
  { path: '/interview-hub', label: '开始面试', icon: BarChart3, gradient: 'from-indigo-500 to-blue-500' },
];

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      // 即使接口失败也清除本地状态
    }
    localStorage.removeItem('access_token');
    localStorage.removeItem('token_type');
    navigate('/login');
  };

  return (
    <div className="min-h-screen flex bg-gradient-to-br from-slate-50 via-white to-indigo-50/30">
      <aside className="w-72 bg-white/80 backdrop-blur-xl border-r border-slate-200/60 flex flex-col shadow-xl">
        <div className="p-6 border-b border-slate-100/60">
          <div className="flex items-center gap-3">
            <div className="relative w-12 h-12 bg-gradient-to-br from-primary-500 via-primary-600 to-indigo-600 rounded-2xl flex items-center justify-center shadow-lg shadow-primary-500/30 group-hover:shadow-primary-500/50 transition-shadow">
              <Sparkles className="w-6 h-6 text-white animate-pulse" />
              <div className="absolute inset-0 bg-gradient-to-br from-white/20 to-transparent rounded-2xl" />
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-slate-900 to-slate-700 bg-clip-text text-transparent">AI 面试助手</h1>
              <p className="text-xs text-slate-500 font-medium">智能面试模拟平台</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path || location.pathname.startsWith(item.path + '/');
            const Icon = item.icon;
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`group w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-sm font-medium transition-all duration-300 relative overflow-hidden ${
                  isActive
                    ? 'bg-gradient-to-r from-primary-50 to-indigo-50 text-primary-700 shadow-md shadow-primary-100/50'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 hover:shadow-sm'
                }`}
              >
                {isActive && (
                  <div className="absolute inset-0 bg-gradient-to-r from-primary-500/5 to-indigo-500/5 animate-pulse" />
                )}
                <div className={`relative w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-300 ${
                  isActive
                    ? `bg-gradient-to-br ${item.gradient} shadow-lg`
                    : 'bg-slate-100 group-hover:bg-slate-200'
                }`}>
                  <Icon className={`w-5 h-5 transition-colors ${isActive ? 'text-white' : 'text-slate-500 group-hover:text-slate-700'}`} />
                </div>
                <span className="relative">{item.label}</span>
                {isActive && (
                  <div className="absolute right-3 w-1.5 h-1.5 bg-primary-500 rounded-full animate-pulse" />
                )}
              </button>
            );
          })}
        </nav>
        <div className="p-4 border-t border-slate-100/60 space-y-2">
          <div className="relative px-4 py-3 bg-gradient-to-r from-primary-50 via-indigo-50 to-purple-50 rounded-xl overflow-hidden group hover:shadow-md transition-shadow">
            <div className="absolute inset-0 bg-gradient-to-r from-primary-500/5 to-purple-500/5 opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="relative flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse shadow-lg shadow-green-500/50" />
              <div>
                <p className="text-xs font-semibold text-primary-700">Python FastAPI</p>
                <p className="text-xs text-primary-500">服务运行中</p>
              </div>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-red-500 hover:bg-red-50 transition-all duration-300"
          >
            <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-red-50 group-hover:bg-red-100">
              <LogOut className="w-5 h-5" />
            </div>
            <span>退出登录</span>
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
