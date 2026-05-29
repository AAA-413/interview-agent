import { request } from './request';
import type {
  PersonalTrainingPlanDTO,
  ScoreCalibrationDTO,
  TrainingTaskProgressDTO,
  TrainingTrendDTO,
  UpdateTrainingTaskProgressRequest,
} from '../types/training';

export const trainingApi = {
  async getCalibration(): Promise<ScoreCalibrationDTO> {
    return request.get<ScoreCalibrationDTO>('/api/training/calibration');
  },

  async getPersonalPlan(days = 7): Promise<PersonalTrainingPlanDTO> {
    return request.get<PersonalTrainingPlanDTO>(`/api/training/plan?days=${days}`);
  },

  async updateTaskProgress(req: UpdateTrainingTaskProgressRequest): Promise<TrainingTaskProgressDTO> {
    return request.put<TrainingTaskProgressDTO>('/api/training/tasks/progress', req);
  },

  async getTrends(): Promise<TrainingTrendDTO> {
    return request.get<TrainingTrendDTO>('/api/training/trends');
  },
};
