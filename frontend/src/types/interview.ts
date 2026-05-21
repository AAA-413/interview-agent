export interface KeyPoint {
  point: string;
  score_range: string;
  weight: string;
}

export interface InterviewQuestionDTO {
  question_index: number;
  question: string;
  type: string;
  category: string | null;
  topic_summary: string | null;
  is_follow_up: boolean;
  parent_question_index: number | null;
  answer: string | null;
  question_type: string;
  reference_answer: string | null;
  key_points: KeyPoint[] | null;
}

export interface CategoryDTO {
  key: string;
  label: string;
  priority: string;
  ref: string | null;
  shared: boolean | null;
}

export interface SkillCategoryDTO {
  key: string;
  label: string;
  priority: string;
  ref: string | null;
  shared: boolean;
}

export interface SkillDTO {
  id: string;
  name: string;
  description: string | null;
  categories: SkillCategoryDTO[];
  is_preset: boolean;
  source_jd: string | null;
  display_name: string | null;
  persona: string | null;
}

export interface CreateInterviewRequest {
  resume_id?: number | null;
  resume_text?: string | null;
  skill_id?: string | null;
  difficulty?: string | null;
  question_count?: number;
  force_create?: boolean;
  llm_provider?: string | null;
  custom_categories?: CategoryDTO[] | null;
  jd_text?: string | null;
  interview_mode?: string | null;
  project_name?: string | null;
  target_role?: string | null;
  target_company?: string | null;
  level?: string | null;
}

export interface InterviewSessionDTO {
  session_id: string;
  resume_text: string;
  total_questions: number;
  current_question_index: number;
  questions: InterviewQuestionDTO[];
  status: string;
  evaluate_status: string | null;
  evaluate_error: string | null;
}

export interface SubmitAnswerResponse {
  has_next_question: boolean;
  next_question: InterviewQuestionDTO | null;
  current_question_index: number;
  total_questions: number;
}

export interface SessionListItemDTO {
  id: number;
  session_id: string;
  skill_id: string | null;
  difficulty: string | null;
  resume_id: number | null;
  total_questions: number | null;
  current_question_index: number;
  status: string;
  evaluate_status: string | null;
  evaluate_error: string | null;
  overall_score: number | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface ProjectDimensions {
  authenticity: number;
  technical_depth: number;
  depth: number;
  expression: number;
}

export interface QuestionEvaluationDTO {
  question_index: number;
  question: string;
  category: string | null;
  user_answer: string | null;
  score: number;
  feedback: string | null;
  question_type?: string;
  covered_points?: string[];
  missed_points?: string[];
  errors?: string[];
  dimensions?: ProjectDimensions;
}

export interface ReferenceAnswerDTO {
  question_index: number;
  question: string;
  reference_answer: string | null;
  key_points: string[];
}

export interface CategoryScoreDTO {
  category: string;
  average_score: number;
  question_count: number;
}

export interface InterviewReportDTO {
  session_id: string;
  total_questions: number;
  overall_score: number;
  category_scores: CategoryScoreDTO[];
  question_evaluations: QuestionEvaluationDTO[];
  overall_feedback: string | null;
  strengths: string[];
  improvements: string[];
  reference_answers: ReferenceAnswerDTO[];
}

export interface InterviewDetailDTO {
  session_id: string;
  skill_id: string | null;
  difficulty: string | null;
  resume_id: number | null;
  total_questions: number | null;
  current_question_index: number;
  status: string;
  evaluate_status: string | null;
  evaluate_error: string | null;
  overall_score: number | null;
  overall_feedback: string | null;
  strengths: string[];
  improvements: string[];
  questions: InterviewQuestionDTO[];
  question_evaluations: QuestionEvaluationDTO[];
  reference_answers: ReferenceAnswerDTO[];
  created_at: string | null;
  completed_at: string | null;
}
