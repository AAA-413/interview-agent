import { request } from './request';
import type { ResumeDetailDTO, ResumeListItemDTO } from '../types/resume';

export const resumeApi = {
  async listResumes(): Promise<ResumeListItemDTO[]> {
    return request.get<ResumeListItemDTO[]>('/api/resumes');
  },

  async getResume(id: number): Promise<ResumeDetailDTO> {
    return request.get<ResumeDetailDTO>(`/api/resumes/${id}`);
  },

  async uploadResume(file: File): Promise<ResumeDetailDTO> {
    const formData = new FormData();
    formData.append('file', file);
    return request.upload<ResumeDetailDTO>('/api/resumes', formData);
  },

  async deleteResume(id: number): Promise<void> {
    return request.delete(`/api/resumes/${id}`);
  },

  async reanalyze(id: number): Promise<void> {
    return request.post(`/api/resumes/${id}/reanalyze`);
  },

  async exportPdf(id: number): Promise<Blob> {
    const response = await request.getInstance().get(`/api/resumes/${id}/export-pdf`, {
      responseType: 'blob',
    });
    return response.data;
  },
};
