export interface InterviewDiagnosisRequest {
  resume_id?: number | null;
  resume_text?: string | null;
  target_role: string;
  target_company?: string | null;
  level?: string;
  jd_text?: string | null;
}

export interface DiagnosisItemDTO {
  title: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  evidence: string;
  impact: string;
  action: string;
}

export interface RiskQuestionDTO {
  question: string;
  risk: string;
  answer_hint: string;
}

export interface PracticeTaskDTO {
  title: string;
  deliverable: string;
  minutes: number;
  action_path: string | null;
}

export interface SevenDayPlanItemDTO {
  day: number;
  theme: string;
  tasks: string[];
}

export interface InterviewDiagnosisDTO {
  target_role: string;
  target_company: string | null;
  level: string;
  resume_id: number | null;
  resume_filename: string | null;
  readiness_score: number;
  readiness_level: string;
  score_explanation: string;
  weakness_summary: string;
  diagnosis_basis: string[];
  weaknesses: DiagnosisItemDTO[];
  resume_risks: RiskQuestionDTO[];
  project_follow_up_questions: string[];
  knowledge_gaps: DiagnosisItemDTO[];
  today_tasks: PracticeTaskDTO[];
  seven_day_plan: SevenDayPlanItemDTO[];
  next_actions: PracticeTaskDTO[];
}
