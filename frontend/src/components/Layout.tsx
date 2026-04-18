import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { LayoutDashboard, FileText, MessageSquare, BarChart3, Upload, BookOpen, Database } from 'lucide-react';

const navItems = [
  { path: '/resumes', label: '简历管理', icon: FileText },
  { path: '/upload', label: '上传简历', icon: Upload },
  { path: '/knowledgebases', label: '知识库管理', icon: Database },
  { path: '/knowledgebases/upload', label: '上传知识库', icon: BookOpen },
  { path: '/interviews', label: '面试记录', icon: MessageSquare },
  { path: '/interview-hub', label: '开始面试', icon: BarChart3 },
];

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="min-h-screen flex">
      <aside className="w-64 bg-white border-r border-slate-200 flex flex-col">
        <div className="p-6 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-primary-700 rounded-xl flex items-center justify-center">
              <LayoutDashboard className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900">AI 面试助手</h1>
              <p className="text-xs text-slate-500">智能面试模拟平台</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path || location.pathname.startsWith(item.path + '/');
            const Icon = item.icon;
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'bg-primary-50 text-primary-700 shadow-sm'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`}
              >
                <Icon className={`w-5 h-5 ${isActive ? 'text-primary-600' : 'text-slate-400'}`} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="p-4 border-t border-slate-100">
          <div className="px-4 py-3 bg-gradient-to-r from-primary-50 to-indigo-50 rounded-xl">
            <p className="text-xs font-medium text-primary-700">Python FastAPI 版</p>
            <p className="text-xs text-primary-500 mt-1">后端服务运行中</p>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
