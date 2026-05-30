export interface ProjectDrillRequest {
  resume_id: number;
  target_role: string;
  project_name?: string | null;
  target_company?: string | null;
  level?: string;
  jd_text?: string | null;
}

export interface ProjectCandidateDTO {
  name: string;
  role: string | null;
  tech_stack: string[];
  reason: string;
}

export interface ProjectDrillQuestionDTO {
  category: string;
  question: string;
  risk: string;
  answer_framework: string[];
  strong_answer_signals: string[];
  red_flags: string[];
}

export interface ProjectDrillQualityDTO {
  score: number;
  verdict: string;
  checks: string[];
  suggestions: string[];
}

export interface ProjectDrillDTO {
  resume_id: number;
  resume_filename: string;
  target_role: string;
  target_company: string | null;
  level: string;
  selected_project: ProjectCandidateDTO;
  project_candidates: ProjectCandidateDTO[];
  risk_summary: string;
  warmup_prompt: string;
  project_pitch: string;
  proof_points: string[];
  gap_fixes: string[];
  quality: ProjectDrillQualityDTO;
  questions: ProjectDrillQuestionDTO[];
  practice_checklist: string[];
}
