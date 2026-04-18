import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  generateDownloadPlan,
  executeDownloadPlan,
  getDownloadProgress,
  DownloadPlan,
  DownloadProgress,
  DownloadStep,
} from '../api/smartDownload';

/**
 * 智能下载知识库页面
 *
 * 两阶段流程：
 * 1. 用户输入需求 → 生成下载计划 → 用户确认
 * 2. 执行下载 → 实时显示进度 → 完成
 */
const SmartDownloadPage: React.FC = () => {
  const navigate = useNavigate();

  // 阶段控制
  const [stage, setStage] = useState<'input' | 'plan' | 'executing'>('input');

  // 阶段1：用户输入
  const [userInput, setUserInput] = useState('');
  const [maxDownloads, setMaxDownloads] = useState(10);
  const [kbId, setKbId] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  // 阶段2：下载计划
  const [plan, setPlan] = useState<DownloadPlan | null>(null);
  const [selectedSteps, setSelectedSteps] = useState<Set<number>>(new Set());

  // 阶段3：执行下载
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const [progressInterval, setProgressInterval] = useState<NodeJS.Timeout | null>(null);

  // 生成下载计划
  const handleGeneratePlan = async () => {
    if (!userInput.trim()) {
      alert('请输入您的需求');
      return;
    }

    setLoading(true);
    try {
      const result = await generateDownloadPlan({
        user_input: userInput,
        max_downloads: maxDownloads,
        kb_id: kbId,
      });

      setPlan(result);
      // 默认全选
      setSelectedSteps(new Set(result.steps.map(s => s.step_id)));
      setStage('plan');
    } catch (error: any) {
      alert(`生成计划失败: ${error.message || '未知错误'}`);
    } finally {
      setLoading(false);
    }
  };

  // 执行下载计划
  const handleExecutePlan = async () => {
    if (!plan) return;

    // 过滤用户选择的步骤
    const filteredSteps = plan.steps.filter(s => selectedSteps.has(s.step_id));
    if (filteredSteps.length === 0) {
      alert('请至少选择一个下载任务');
      return;
    }

    setLoading(true);
    try {
      const result = await executeDownloadPlan({
        plan_id: plan.plan_id,
        kb_id: kbId,
        kb_name: kbId ? undefined : `${plan.intent.target_resources?.[0] || '智能下载'} - 知识库`,
        kb_description: `自动下载：${userInput}`,
      });

      setTaskId(result.task_id);
      setStage('executing');

      // 开始轮询进度
      const interval = setInterval(async () => {
        try {
          const progressData = await getDownloadProgress(result.task_id);
          setProgress(progressData);

          // 如果完成或失败，停止轮询
          if (progressData.status === 'completed' || progressData.status === 'failed') {
            clearInterval(interval);
          }
        } catch (error) {
          console.error('查询进度失败:', error);
        }
      }, 1000); // 每秒查询一次

      setProgressInterval(interval);
    } catch (error: any) {
      alert(`启动下载失败: ${error.message || '未知错误'}`);
    } finally {
      setLoading(false);
    }
  };

  // 切换步骤选择
  const toggleStep = (stepId: number) => {
    const newSelected = new Set(selectedSteps);
    if (newSelected.has(stepId)) {
      newSelected.delete(stepId);
    } else {
      newSelected.add(stepId);
    }
    setSelectedSteps(newSelected);
  };

  // 重新开始
  const handleReset = () => {
    setStage('input');
    setUserInput('');
    setPlan(null);
    setTaskId(null);
    setProgress(null);
    setSelectedSteps(new Set());
    if (progressInterval) {
      clearInterval(progressInterval);
      setProgressInterval(null);
    }
  };

  // 清理定时器
  useEffect(() => {
    return () => {
      if (progressInterval) {
        clearInterval(progressInterval);
      }
    };
  }, [progressInterval]);

  // 渲染阶段1：用户输入
  const renderInputStage = () => (
    <div className="max-w-3xl mx-auto">
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-2xl font-bold mb-6">智能下载知识库</h2>

        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            描述您的需求
          </label>
          <textarea
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="例如：我想学习 FastAPI 框架，帮我下载官方文档和优质教程"
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            rows={4}
          />
          <p className="mt-2 text-sm text-gray-500">
            支持：官方文档、CSDN、掘金、知乎、Medium 等知名博客
          </p>
        </div>

        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            最大下载数量
          </label>
          <input
            type="number"
            value={maxDownloads}
            onChange={(e) => setMaxDownloads(Number(e.target.value))}
            min={1}
            max={20}
            className="w-32 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          />
          <p className="mt-2 text-sm text-gray-500">
            建议 5-10 个，避免下载过多
          </p>
        </div>

        <button
          onClick={handleGeneratePlan}
          disabled={loading || !userInput.trim()}
          className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? '正在生成计划...' : '生成下载计划'}
        </button>
      </div>
    </div>
  );

  // 渲染阶段2：下载计划
  const renderPlanStage = () => {
    if (!plan) return null;

    return (
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-2xl font-bold mb-4">下载计划</h2>

          <div className="mb-6 p-4 bg-blue-50 rounded-lg">
            <p className="text-sm text-gray-700">
              <strong>需求：</strong>{plan.user_input}
            </p>
            <p className="text-sm text-gray-700 mt-2">
              <strong>意图：</strong>{plan.intent.reasoning || '分析中...'}
            </p>
            <div className="flex gap-4 mt-2 text-sm text-gray-600">
              <span>预计时间：{plan.estimated_time}</span>
              <span>预计大小：{plan.estimated_size}</span>
              <span>共 {plan.total_steps} 个任务</span>
            </div>
          </div>

          <div className="mb-6">
            <h3 className="text-lg font-semibold mb-3">下载任务（请选择需要的）</h3>
            <div className="space-y-3">
              {plan.steps.map((step) => (
                <div
                  key={step.step_id}
                  className={`p-4 border rounded-lg cursor-pointer transition-colors ${
                    selectedSteps.has(step.step_id)
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-300 hover:border-gray-400'
                  }`}
                  onClick={() => toggleStep(step.step_id)}
                >
                  <div className="flex items-start">
                    <input
                      type="checkbox"
                      checked={selectedSteps.has(step.step_id)}
                      onChange={() => toggleStep(step.step_id)}
                      className="mt-1 mr-3"
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">步骤 {step.step_id}</span>
                        <span className="px-2 py-1 text-xs bg-gray-200 rounded">
                          {step.source_type}
                        </span>
                        <span className="px-2 py-1 text-xs bg-green-200 rounded">
                          {step.action}
                        </span>
                      </div>
                      <p className="text-sm text-gray-700 mt-1">{step.description}</p>
                      {step.params.url && (
                        <p className="text-xs text-gray-500 mt-1 truncate">
                          URL: {step.params.url}
                        </p>
                      )}
                      {step.params.query && (
                        <p className="text-xs text-gray-500 mt-1">
                          搜索: {step.params.query}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex gap-4">
            <button
              onClick={handleReset}
              className="flex-1 bg-gray-200 text-gray-700 py-3 rounded-lg hover:bg-gray-300 transition-colors"
            >
              重新输入
            </button>
            <button
              onClick={handleExecutePlan}
              disabled={loading || selectedSteps.size === 0}
              className="flex-1 bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? '启动中...' : `确认下载（${selectedSteps.size} 个任务）`}
            </button>
          </div>
        </div>
      </div>
    );
  };

  // 渲染阶段3：执行进度
  const renderExecutingStage = () => {
    if (!progress) return null;

    const statusText = {
      planning: '规划中',
      executing: '下载中',
      quality_check: '质量检查',
      indexing: '建立索引',
      completed: '完成',
      failed: '失败',
    };

    const statusColor = {
      planning: 'text-blue-600',
      executing: 'text-blue-600',
      quality_check: 'text-yellow-600',
      indexing: 'text-purple-600',
      completed: 'text-green-600',
      failed: 'text-red-600',
    };

    return (
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-2xl font-bold mb-6">下载进度</h2>

          <div className="mb-6">
            <div className="flex justify-between items-center mb-2">
              <span className={`font-semibold ${statusColor[progress.status]}`}>
                {statusText[progress.status]}
              </span>
              <span className="text-sm text-gray-600">
                {progress.current_step} / {progress.total_steps}
              </span>
            </div>

            <div className="w-full bg-gray-200 rounded-full h-4 mb-2">
              <div
                className="bg-blue-600 h-4 rounded-full transition-all duration-300"
                style={{ width: `${progress.progress_percent}%` }}
              />
            </div>

            <p className="text-sm text-gray-700">{progress.message}</p>

            {progress.retry_count > 0 && (
              <p className="text-sm text-yellow-600 mt-2">
                重试次数: {progress.retry_count} / 3
              </p>
            )}

            {progress.quality_score !== undefined && (
              <p className="text-sm text-gray-600 mt-2">
                质量评分: {(progress.quality_score * 100).toFixed(0)}%
              </p>
            )}
          </div>

          {progress.downloaded_files.length > 0 && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold mb-3">已下载文件</h3>
              <div className="space-y-2">
                {progress.downloaded_files.map((file, index) => (
                  <div key={index} className="p-3 bg-gray-50 rounded-lg">
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-gray-700">{file.description}</span>
                      <span className="text-xs text-gray-500">
                        {(file.size / 1024).toFixed(1)} KB
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {progress.status === 'completed' && (
            <div className="p-4 bg-green-50 border border-green-200 rounded-lg mb-4">
              <p className="text-green-800 font-semibold">✅ 下载完成！</p>
              <p className="text-sm text-green-700 mt-1">
                成功下载 {progress.downloaded_files.length} 个文件
              </p>
            </div>
          )}

          {progress.status === 'failed' && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-lg mb-4">
              <p className="text-red-800 font-semibold">❌ 下载失败</p>
              <p className="text-sm text-red-700 mt-1">{progress.message}</p>
            </div>
          )}

          {(progress.status === 'completed' || progress.status === 'failed') && (
            <div className="flex gap-4">
              <button
                onClick={handleReset}
                className="flex-1 bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 transition-colors"
              >
                继续下载
              </button>
              <button
                onClick={() => navigate('/knowledge-base')}
                className="flex-1 bg-gray-200 text-gray-700 py-3 rounded-lg hover:bg-gray-300 transition-colors"
              >
                返回知识库
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      {stage === 'input' && renderInputStage()}
      {stage === 'plan' && renderPlanStage()}
      {stage === 'executing' && renderExecutingStage()}
    </div>
  );
};

export default SmartDownloadPage;
