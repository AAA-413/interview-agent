import { useEffect, useState } from 'react';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  BarChart3,
  BookOpen,
  CalendarCheck,
  ClipboardCheck,
  Database,
  FileText,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  MessageSquareText,
  Network,
  Sparkles,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { authApi } from '../api/auth';
import { apiUrl } from '../api/request';

type NavItem = {
  path: string;
  label: string;
  icon: LucideIcon;
  gradient: string;
  exact?: boolean;
};

const navItems: NavItem[] = [
  { path: '/dashboard', label: '工作台', icon: LayoutDashboard, gradient: 'from-slate-700 to-slate-900', exact: true },
  { path: '/diagnosis', label: '面试诊断', icon: ClipboardCheck, gradient: 'from-emerald-500 to-teal-500' },
  { path: '/project-drill', label: '项目深挖', icon: MessageSquareText, gradient: 'from-rose-500 to-pink-500' },
  { path: '/interview-hub', label: '开始面试', icon: BarChart3, gradient: 'from-indigo-500 to-blue-500' },
  { path: '/training-plan', label: '训练计划', icon: CalendarCheck, gradient: 'from-emerald-500 to-lime-500' },
  { path: '/resumes', label: '简历管理', icon: FileText, gradient: 'from-blue-500 to-cyan-500' },
  { path: '/knowledgebases', label: '知识库', icon: Database, gradient: 'from-emerald-500 to-teal-500' },
  { path: '/knowledge-graph', label: '知识图谱', icon: Network, gradient: 'from-violet-500 to-purple-500' },
  { path: '/knowledgebases/smart-download', label: '智能下载', icon: BookOpen, gradient: 'from-amber-500 to-orange-500' },
  { path: '/interviews', label: '面试记录', icon: MessageSquare, gradient: 'from-pink-500 to-rose-500' },
];

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [serviceOnline, setServiceOnline] = useState<boolean | null>(null);

  useEffect(() => {
    if (!localStorage.getItem('access_token')) {
      navigate('/login', { replace: true });
    }
  }, [navigate]);

  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl('/api/health'))
      .then(response => {
        if (!cancelled) setServiceOnline(response.ok);
      })
      .catch(() => {
        if (!cancelled) setServiceOnline(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isActivePath = (item: NavItem) => {
    if (item.exact) return location.pathname === item.path;
    if (item.path === '/knowledgebases') {
      return location.pathname === item.path || /^\/knowledgebases\/\d+/.test(location.pathname);
    }
    return location.pathname === item.path || location.pathname.startsWith(item.path + '/');
  };

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

  const renderDesktopNavItem = (item: NavItem) => {
    const isActive = isActivePath(item);
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
  };

  const renderMobileNavItem = (item: NavItem) => {
    const isActive = isActivePath(item);
    const Icon = item.icon;
    return (
      <button
        key={item.path}
        onClick={() => navigate(item.path)}
        className={`shrink-0 w-20 h-16 flex flex-col items-center justify-center gap-1 rounded-2xl text-[11px] font-medium transition-colors ${
          isActive ? 'bg-primary-50 text-primary-700' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'
        }`}
      >
        <Icon className={`w-5 h-5 ${isActive ? 'text-primary-600' : 'text-slate-500'}`} />
        <span className="max-w-full truncate px-1">{item.label}</span>
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 lg:flex">
      <header className="fixed inset-x-0 top-0 z-40 lg:hidden border-b border-slate-200/70 bg-white/90 backdrop-blur-xl">
        <div className="flex h-16 items-center justify-between px-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 via-primary-600 to-indigo-600 shadow-lg shadow-primary-500/25">
              <Sparkles className="h-5 w-5 text-white" />
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/20 to-transparent" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-base font-bold text-slate-900">OfferPilot</h1>
              <p className="truncate text-xs text-slate-500">AI 面试训练工作台</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-red-500 transition-colors hover:bg-red-50"
            aria-label="退出登录"
          >
            <LogOut className="h-5 w-5" />
          </button>
        </div>
      </header>

      <aside className="hidden w-72 shrink-0 bg-white/80 backdrop-blur-xl border-r border-slate-200/60 lg:flex flex-col shadow-xl">
        <div className="p-6 border-b border-slate-100/60">
          <div className="flex items-center gap-3">
            <div className="relative w-12 h-12 bg-gradient-to-br from-primary-500 via-primary-600 to-indigo-600 rounded-2xl flex items-center justify-center shadow-lg shadow-primary-500/30 group-hover:shadow-primary-500/50 transition-shadow">
              <Sparkles className="w-6 h-6 text-white animate-pulse" />
              <div className="absolute inset-0 bg-gradient-to-br from-white/20 to-transparent rounded-2xl" />
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-slate-900 to-slate-700 bg-clip-text text-transparent">OfferPilot</h1>
              <p className="text-xs text-slate-500 font-medium">AI 面试训练工作台</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          {navItems.map(renderDesktopNavItem)}
        </nav>
        <div className="p-4 border-t border-slate-100/60 space-y-2">
          <div className="relative px-4 py-3 bg-gradient-to-r from-primary-50 via-indigo-50 to-purple-50 rounded-xl overflow-hidden group hover:shadow-md transition-shadow">
            <div className="absolute inset-0 bg-gradient-to-r from-primary-500/5 to-purple-500/5 opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="relative flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse shadow-lg shadow-green-500/50" />
              <div>
                <p className="text-xs font-semibold text-primary-700">Python FastAPI</p>
                <p className="text-xs text-primary-500">
                  {serviceOnline === null ? '服务检测中' : serviceOnline ? '服务运行中' : '服务未连接'}
                </p>
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
      <main className="min-w-0 flex-1 overflow-auto pt-20 pb-24 lg:pt-0 lg:pb-0">
        <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
          <Outlet />
        </div>
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200/70 bg-white/95 px-3 py-2 shadow-[0_-12px_30px_-24px_rgba(15,23,42,0.6)] backdrop-blur-xl lg:hidden">
        <div className="flex gap-2 overflow-x-auto">
          {navItems.map(renderMobileNavItem)}
        </div>
      </nav>
    </div>
  );
}
