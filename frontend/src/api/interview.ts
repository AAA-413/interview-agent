import { request } from './request';
import type {
  CreateInterviewRequest,
  InterviewDetailDTO,
  InterviewQuestionDTO,
  InterviewReportDTO,
  InterviewSessionDTO,
  RetryAnswerComparisonDTO,
  SessionListItemDTO,
  SubmitAnswerResponse,
  VoiceTranscriptionDTO,
} from '../types/interview';
import type { InterviewDiagnosisDTO, InterviewDiagnosisRequest } from '../types/diagnosis';
import type { ProjectDrillDTO, ProjectDrillRequest } from '../types/projectDrill';

export const interviewApi = {
  async createDiagnosis(req: InterviewDiagnosisRequest): Promise<InterviewDiagnosisDTO> {
    return request.post<InterviewDiagnosisDTO>('/api/interview/diagnosis', req, {
      timeout: 60000,
    });
  },

  async createProjectDrill(req: ProjectDrillRequest): Promise<ProjectDrillDTO> {
    return request.post<ProjectDrillDTO>('/api/interview/project-drill', req, {
      timeout: 60000,
    });
  },

  async listSessions(): Promise<SessionListItemDTO[]> {
    return request.get<SessionListItemDTO[]>('/api/interview/sessions');
  },

  async createSession(req: CreateInterviewRequest): Promise<InterviewSessionDTO> {
    return request.post<InterviewSessionDTO>('/api/interview/sessions', req, {
      timeout: 180000,
    });
  },

  async createRetrySession(sessionId: string, questionIndex: number): Promise<InterviewSessionDTO> {
    return request.post<InterviewSessionDTO>(`/api/interview/sessions/${sessionId}/retry`, {
      question_index: questionIndex,
    });
  },

  async getRetryComparison(sessionId: string): Promise<RetryAnswerComparisonDTO> {
    return request.get<RetryAnswerComparisonDTO>(`/api/interview/sessions/${sessionId}/retry-comparison`);
  },

  async getSession(sessionId: string): Promise<InterviewSessionDTO> {
    return request.get<InterviewSessionDTO>(`/api/interview/sessions/${sessionId}`);
  },

  async getCurrentQuestion(sessionId: string): Promise<{ completed: boolean; question?: InterviewQuestionDTO; message?: string }> {
    return request.get(`/api/interview/sessions/${sessionId}/question`);
  },

  async submitAnswer(sessionId: string, questionIndex: number, answer: string): Promise<SubmitAnswerResponse> {
    return request.post<SubmitAnswerResponse>(
      `/api/interview/sessions/${sessionId}/answers`,
      { question_index: questionIndex, answer },
      { timeout: 180000 }
    );
  },

  async transcribeVoice(file: File): Promise<VoiceTranscriptionDTO> {
    const formData = new FormData();
    formData.append('file', file);
    return request.upload<VoiceTranscriptionDTO>('/api/interview/voice/transcribe', formData, {
      timeout: 180000,
    });
  },

  async saveAnswer(sessionId: string, questionIndex: number, answer: string): Promise<void> {
    return request.put(`/api/interview/sessions/${sessionId}/answers`, {
      question_index: questionIndex,
      answer,
    });
  },

  async completeInterview(sessionId: string): Promise<void> {
    return request.post(`/api/interview/sessions/${sessionId}/complete`);
  },

  async getReport(sessionId: string): Promise<InterviewReportDTO> {
    return request.get<InterviewReportDTO>(`/api/interview/sessions/${sessionId}/report`, {
      timeout: 180000,
    });
  },

  async getInterviewDetail(sessionId: string): Promise<InterviewDetailDTO> {
    return request.get<InterviewDetailDTO>(`/api/interview/sessions/${sessionId}/details`);
  },

  async findUnfinishedSession(resumeId: number): Promise<InterviewSessionDTO | null> {
    try {
      return await request.get<InterviewSessionDTO>(`/api/interview/sessions/unfinished/${resumeId}`);
    } catch {
      return null;
    }
  },

  async deleteSession(sessionId: string): Promise<void> {
    return request.delete(`/api/interview/sessions/${sessionId}`);
  },

  async exportPdf(sessionId: string): Promise<Blob> {
    const response = await request.getInstance().get(`/api/interview/sessions/${sessionId}/export`, {
      responseType: 'blob',
    });
    return response.data;
  },
};
