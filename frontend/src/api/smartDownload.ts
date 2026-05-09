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
  status: 'planning' | 'executing' | 'quality_check' | 'summarizing' | 'indexing' | 'completed' | 'failed' | 'cancelled';
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
  quality_details?: {
    passed_count: number;
    failed_count: number;
    phase: string;
    total: number;
  };
  task_statuses?: Record<number, string>;
  integrated_doc?: {
    title: string;
    summary: string;
    source_count: number;
    total_length: number;
    sources: string[];
    content?: string;
    source_summaries?: Array<{
      source: string;
      description: string;
      summary: string;
    }>;
  };
  kb_info?: {
    kb_id: number;
    kb_name: string;
    doc_id: number;
  };
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
  return request.post<DownloadPlan>('/api/agent/smart-download/plan', data);
};

/**
 * 执行下载计划（阶段2）
 */
export const executeDownloadPlan = (data: ExecuteDownloadRequest) => {
  return request.post<{ task_id: string; message: string; plan_id: string }>(
    '/api/agent/smart-download/execute',
    data
  );
};

/**
 * 查询下载进度
 */
export const getDownloadProgress = (taskId: string) => {
  return request.get<DownloadProgress>(`/api/agent/smart-download/progress/${taskId}`);
};

/**
 * 取消下载任务
 */
export const cancelDownloadTask = (taskId: string) => {
  return request.post<{ message: string; task_id: string }>(
    `/api/agent/smart-download/cancel/${taskId}`
  );
};
