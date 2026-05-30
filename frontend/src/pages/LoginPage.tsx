import { FormEvent, useState } from 'react';
import {
  ArrowRight,
  Brain,
  CheckCircle2,
  FileText,
  Loader2,
  Lock,
  Mail,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  Target,
  User,
  UserPlus,
} from 'lucide-react';
import { authApi } from '../api/auth';

type AuthMode = 'login' | 'register';

const proofPoints = [
  { label: '简历诊断', icon: FileText },
  { label: '项目打磨', icon: Target },
  { label: '模拟面试', icon: MessageSquareText },
  { label: '训练复盘', icon: Brain },
];

export default function LoginPage() {
  const [mode, setMode] = useState<AuthMode>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isRegister = mode === 'register';

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (isRegister) {
        await authApi.register({
          username: username.trim(),
          email: email.trim(),
          full_name: fullName.trim() || undefined,
          password,
        });
      }

      const response = await authApi.login({ username: username.trim(), password });
      localStorage.setItem('access_token', response.access_token);
      localStorage.setItem('token_type', response.token_type);
      window.location.replace('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : isRegister ? '注册失败，请稍后重试' : '登录失败，请检查账号和密码');
    } finally {
      setLoading(false);
    }
  };

  const toggleMode = () => {
    setError('');
    setMode(prev => (prev === 'login' ? 'register' : 'login'));
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <div className="grid min-h-screen lg:grid-cols-[1.05fr_0.95fr]">
        <section className="relative flex flex-col justify-between overflow-hidden border-b border-white/10 bg-slate-950 p-6 lg:border-b-0 lg:border-r lg:p-10">
          <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(16,185,129,0.12),transparent_34%,rgba(59,130,246,0.10))]" />
          <div className="relative">
            <div className="mb-14 flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-white text-slate-950">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <div className="text-lg font-bold">OfferPilot</div>
                <div className="text-xs text-slate-400">AI 面试训练工作台</div>
              </div>
            </div>

            <div className="max-w-2xl">
              <div className="mb-4 inline-flex items-center gap-2 rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-3 py-1.5 text-sm font-medium text-emerald-200">
                <ShieldCheck className="h-4 w-4" />
                面向求职训练、就业服务和培训交付
              </div>
              <h1 className="text-4xl font-bold tracking-normal text-white sm:text-5xl">
                把简历、项目和面试变成可复盘的训练产品
              </h1>
              <p className="mt-5 max-w-xl text-base leading-7 text-slate-300">
                从简历解析到模拟面试报告，围绕目标岗位生成训练路径，让个人和组织都能稳定交付面试提升效果。
              </p>
            </div>

            <div className="mt-10 grid max-w-2xl gap-3 sm:grid-cols-2">
              {proofPoints.map(point => {
                const Icon = point.icon;
                return (
                  <div key={point.label} className="rounded-lg border border-white/10 bg-white/5 p-4">
                    <Icon className="mb-3 h-5 w-5 text-emerald-300" />
                    <div className="text-sm font-semibold text-white">{point.label}</div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="relative mt-10 grid gap-3 text-sm text-slate-300 sm:grid-cols-3">
            <div className="rounded-lg border border-white/10 bg-white/5 p-4">
              <div className="text-2xl font-bold text-white">10+</div>
              <div className="mt-1">面试方向</div>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/5 p-4">
              <div className="text-2xl font-bold text-white">5D</div>
              <div className="mt-1">简历评分</div>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/5 p-4">
              <div className="text-2xl font-bold text-white">RAG</div>
              <div className="mt-1">知识库增强</div>
            </div>
          </div>
        </section>

        <main className="flex items-center justify-center bg-slate-50 p-6 text-slate-950 lg:p-10">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-xl sm:p-8">
            <div className="mb-7">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-primary-700">
                {isRegister ? <UserPlus className="h-4 w-4" /> : <User className="h-4 w-4" />}
                {isRegister ? '创建工作台账号' : '登录工作台'}
              </div>
              <h2 className="text-2xl font-bold text-slate-950">{isRegister ? '开始搭建你的训练闭环' : '欢迎回来'}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">
                {isRegister ? '注册后会自动登录，直接进入产品工作台。' : '继续管理简历、题库、知识库和面试复盘。'}
              </p>
            </div>

            <form className="space-y-4" onSubmit={handleSubmit}>
              {error && (
                <div className="rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">用户名或邮箱</span>
                <div className="relative">
                  <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    value={username}
                    onChange={event => setUsername(event.target.value)}
                    className="w-full rounded-lg border border-slate-200 px-10 py-3 text-sm outline-none transition focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                    placeholder="例如：offerpilot"
                    required
                  />
                </div>
              </label>

              {isRegister && (
                <>
                  <label className="block">
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">邮箱</span>
                    <div className="relative">
                      <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                      <input
                        value={email}
                        onChange={event => setEmail(event.target.value)}
                        className="w-full rounded-lg border border-slate-200 px-10 py-3 text-sm outline-none transition focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                        placeholder="you@example.com"
                        type="email"
                        required
                      />
                    </div>
                  </label>

                  <label className="block">
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">姓名</span>
                    <input
                      value={fullName}
                      onChange={event => setFullName(event.target.value)}
                      className="w-full rounded-lg border border-slate-200 px-3 py-3 text-sm outline-none transition focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                      placeholder="可选"
                    />
                  </label>
                </>
              )}

              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">密码</span>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    value={password}
                    onChange={event => setPassword(event.target.value)}
                    className="w-full rounded-lg border border-slate-200 px-10 py-3 text-sm outline-none transition focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                    placeholder={isRegister ? '至少 6 位' : '请输入密码'}
                    type="password"
                    minLength={6}
                    required
                  />
                </div>
              </label>

              <button
                type="submit"
                disabled={loading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                {loading ? (isRegister ? '正在创建...' : '登录中...') : isRegister ? '注册并进入工作台' : '进入工作台'}
              </button>
            </form>

            <div className="mt-6 flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-4 py-3 text-sm">
              <div className="flex items-center gap-2 text-slate-500">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                {isRegister ? '已有账号？' : '还没有账号？'}
              </div>
              <button onClick={toggleMode} className="font-semibold text-primary-700 hover:text-primary-800">
                {isRegister ? '去登录' : '立即注册'}
              </button>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
