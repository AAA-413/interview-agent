import { request } from './request';
import type { CategoryDTO, SkillDTO } from '../types/interview';

export const skillApi = {
  async listSkills(): Promise<SkillDTO[]> {
    return request.get<SkillDTO[]>('/api/interview/skills');
  },

  async getSkill(id: string): Promise<SkillDTO> {
    return request.get<SkillDTO>(`/api/interview/skills/${id}`);
  },

  async parseJd(jdText: string): Promise<CategoryDTO[]> {
    return request.post<CategoryDTO[]>('/api/interview/skills/parse-jd', { jd_text: jdText });
  },
};
