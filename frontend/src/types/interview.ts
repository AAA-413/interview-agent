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
  retry_source_session_id?: string | null;
  retry_source_question_index?: number | null;
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

export interface StructuredJD {
  raw_jd: string;
  quality_score: number;
  quality_level: string;
  missing_parts: string[];
  user_suggestion: string | null;
  role_title: string | null;
  role_domain: string;
  seniority: string;
  required_skills: string[];
  preferred_skills: string[];
  responsibilities: string[];
  domain_keywords: string[];
  topic_weights: Record<string, number>;
  question_type_mix: Record<string, number>;
}

export interface JDParseRequest {
  target_role?: string | null;
  skill_id?: string | null;
  jd_text?: string | null;
}

export interface DynamicInterviewCreateRequest {
  resume_id?: number | null;
  target_role?: string | null;
  target_company?: string | null;
  level?: string | null;
  jd_text?: string | null;
  mode?: 'COACH' | string;
  topic_count?: 4;
  skill_id?: string | null;
  difficulty?: string | null;
  llm_provider?: string | null;
}

export interface DynamicTopicDTO {
  id: number | null;
  topic_key: string;
  topic_title: string;
  skill_key: string;
  question_type: 'PROJECT' | 'KNOWLEDGE' | 'SYSTEM_DESIGN' | string;
  source_type: string;
  evidence_snippet: string | null;
  main_question: string;
  topic_order: number;
  status: string;
  max_turns: number;
  turn_count: number;
  best_score: number | null;
  final_score: number | null;
  followup_goals: string[];
  exit_criteria: string[];
  rubric: Record<string, string>;
}

export interface DynamicTurnDTO {
  id: number | null;
  topic_id: number | null;
  turn_type: 'MAIN' | 'FOLLOW_UP' | 'COACH_RETRY' | string;
  turn_order: number;
  question: string;
  answer: string | null;
  ability_score: number | null;
  decision_action: string | null;
  feedback: string | null;
  signals: Record<string, string[]>;
  evaluation: Record<string, unknown>;
  decision: Record<string, unknown>;
  coach_hint: DynamicCoachHint | null;
  answered_at: string | null;
}

export interface DynamicCoachHint {
  type?: string;
  message?: string;
  structure?: string[];
  focus_gaps?: string[];
  guardrail?: string;
  [key: string]: unknown;
}

export interface DynamicInterviewCreateResponse {
  session_id: string;
  status: string;
  structured_jd: StructuredJD;
  current_topic: DynamicTopicDTO | null;
  current_turn: DynamicTurnDTO | null;
  plan_summary: Record<string, unknown>;
}

export interface SubmitDynamicTurnAnswerRequest {
  answer: string;
}

export interface DynamicTurnEvaluationDTO {
  ability_score: number;
  feedback: string;
  signals: Record<string, string[]>;
  dimension_scores: Record<string, number>;
}

export interface DynamicDecisionDTO {
  action: string;
  reason: string;
  hint: DynamicCoachHint | null;
  next_question: string | null;
}

export interface DynamicTurnAnswerResponse {
  status: string;
  evaluation: DynamicTurnEvaluationDTO;
  decision: DynamicDecisionDTO;
  next_turn: DynamicTurnDTO | null;
  current_topic: DynamicTopicDTO | null;
  topic_progress: Record<string, unknown>;
  report: DynamicReportDTO | null;
}

export interface DynamicSessionDetailDTO {
  session_id: string;
  status: string;
  mode: string;
  target_role: string | null;
  jd_text: string | null;
  structured_jd: StructuredJD | null;
  topics: DynamicTopicDTO[];
  turns: DynamicTurnDTO[];
  current_topic: DynamicTopicDTO | null;
  current_turn: DynamicTurnDTO | null;
  plan_summary: Record<string, unknown>;
  final_report: DynamicReportDTO | null;
}

export interface DynamicTopicSummaryDTO {
  topic_id: number | null;
  topic_key: string;
  topic_title: string;
  question_type: string;
  evidence_snippet: string | null;
  main_question: string;
  initial_score: number | null;
  final_score: number | null;
  best_score: number | null;
  score_delta: number | null;
  strengths: string[];
  risks: string[];
  gaps: string[];
  next_training_action: string;
}

export interface TomorrowTaskDTO {
  task_type: string;
  topic_key: string;
  evidence_hash: string | null;
  weakness_type: string;
  priority_score: number;
  title: string;
  reason: string;
  action: string;
  status: string;
}

export interface DynamicReportDTO {
  session_id: string;
  readiness_score: number;
  type_scores: Record<string, number | null>;
  ability_scores: Record<string, number>;
  top_risks: string[];
  topic_summaries: DynamicTopicSummaryDTO[];
  tomorrow_tasks: TomorrowTaskDTO[];
  retry_deltas: Record<string, unknown>[];
  resume_fix_suggestions: string[];
}

export interface DynamicRagCitationDTO {
  knowledge_base_id: number;
  chunk_id: number;
  source_name: string;
  title: string | null;
  content_preview: string;
  score: number;
}

export interface DynamicTopicRagInsightDTO {
  topic_id: number | null;
  topic_key: string;
  topic_title: string;
  question_type: string;
  source_status: 'PERSONAL_KB_HIT' | 'SYSTEM_KB_HIT' | 'NO_KB_HIT' | 'MIXED_HIT' | string;
  retrieval_confidence: number;
  fallback_reason: string | null;
  answer_issue: string;
  explanation: string;
  citations: DynamicRagCitationDTO[];
  recommended_materials: string[];
  study_steps: string[];
  next_practice: string;
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

export interface VoiceTranscriptionDTO {
  text: string;
  language: string | null;
  duration: number | null;
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
  interviewer_judgement?: string | null;
  answer_issues?: string[] | null;
  answer_framework?: string[] | null;
  answer_80?: string | null;
  answer_90?: string | null;
  next_practice_question?: string | null;
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

export interface RetryAnswerComparisonDTO {
  session_id: string;
  source_session_id: string;
  source_question_index: number;
  retry_question_index: number;
  source_question: string;
  retry_question: string;
  original_answer: string | null;
  retry_answer: string | null;
  original_score: number | null;
  retry_score: number | null;
  score_delta: number | null;
  original_feedback: string | null;
  retry_feedback: string | null;
  improvement_summary: string;
  next_action: string;
  status: 'WAITING_ANSWER' | 'PENDING_EVALUATION' | 'READY' | string;
}
