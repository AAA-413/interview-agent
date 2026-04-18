/**
 * 智能下载知识库 API
 */

import { request } from './request';

/**
 * 下载步骤
 */
export interface DownloadStep {
  step_id: number;
  action: string;
  params: Record<string, any>;
  description: string;
  source_type: string;
}

/**
 * 下载计划
 */
export interface DownloadPlan {
  plan_id: string;
  user_input: string;
  intent: Record<string, any>;
  steps: DownloadStep[];
  estimated_time: string;
  estimated_size: string;
  total_steps: number;
}

/**
 * 下载进度
 */
export interface DownloadProgress {
  task_id: string;
  status: 'planning' | 'executing' | 'quality_check' | 'indexing' | 'completed' | 'failed';
  current_step: number;
  total_steps: number;
  progress_percent: number;
  message: string;
  retry_count: number;
  downloaded_files: Array<{
    step_id: number;
    description: string;
    size: number;
  }>;
  quality_score?: number;
}

/**
 * 生成下载计划请求
 */
export interface PlanDownloadRequest {
  user_input: string;
  max_downloads?: number;
  kb_id?: number;
}

/**
 * 执行下载请求
 */
export interface ExecuteDownloadRequest {
  plan_id: string;
  kb_id?: number;
  kb_name?: string;
  kb_description?: string;
}

/**
 * 生成下载计划（阶段1）
 */
export const generateDownloadPlan = (data: PlanDownloadRequest) => {
  return request<DownloadPlan>({
    url: '/api/agent/smart-download/plan',
    method: 'POST',
    data,
  });
};

/**
 * 执行下载计划（阶段2）
 */
export const executeDownloadPlan = (data: ExecuteDownloadRequest) => {
  return request<{ task_id: string; message: string; plan_id: string }>({
    url: '/api/agent/smart-download/execute',
    method: 'POST',
    data,
  });
};

/**
 * 查询下载进度
 */
export const getDownloadProgress = (taskId: string) => {
  return request<DownloadProgress>({
    url: `/api/agent/smart-download/progress/${taskId}`,
    method: 'GET',
  });
};
