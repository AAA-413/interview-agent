import { request } from './request';
import type { PersonalTrainingPlanDTO, ScoreCalibrationDTO } from '../types/training';

export const trainingApi = {
  async getCalibration(): Promise<ScoreCalibrationDTO> {
    return request.get<ScoreCalibrationDTO>('/api/training/calibration');
  },

  async getPersonalPlan(days = 7): Promise<PersonalTrainingPlanDTO> {
    return request.get<PersonalTrainingPlanDTO>(`/api/training/plan?days=${days}`);
  },
};
