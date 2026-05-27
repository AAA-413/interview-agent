import { request } from './request';

export interface DemoSeedResponse {
  resume_id: number;
  interview_session_id: string;
  resume_path: string;
  interview_report_path: string;
  message: string;
}

export const demoApi = {
  async seedDemoData(): Promise<DemoSeedResponse> {
    return request.post<DemoSeedResponse>('/api/demo/seed');
  },
};
