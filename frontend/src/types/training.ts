export interface CalibrationQuestionDTO {
  session_id: string;
  question_index: number;
  question: string;
  category: string | null;
  question_type: string;
  raw_score: number | null;
  calibrated_score: number | null;
  confidence: number;
  confidence_label: string;
  review_priority: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  score_band: string;
  reasons: string[];
  evidence_count: number;
  missing_count: number;
  action: string;
  retry_attempt_count: number;
  latest_retry_score: number | null;
  latest_retry_delta: number | null;
  retry_signal: string | null;
}

export interface CalibrationDimensionDTO {
  name: string;
  average_score: number;
  question_count: number;
  weak_count: number;
  suggested_action: string;
}

export interface ScoreCalibrationDTO {
  total_sessions: number;
  evaluated_sessions: number;
  total_questions: number;
  average_raw_score: number;
  calibrated_score: number;
  confidence: number;
  confidence_label: string;
  review_needed_count: number;
  high_risk_count: number;
  summary: string;
  questions: CalibrationQuestionDTO[];
  dimensions: CalibrationDimensionDTO[];
  next_actions: string[];
}

export interface TrainingTaskDTO {
  id: string;
  day: number;
  title: string;
  task_type: string;
  priority: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  estimate_minutes: number;
  reason: string;
  source_session_id: string | null;
  question_index: number | null;
  action_path: string | null;
  checklist: string[];
  status: 'TODO' | 'COMPLETED' | string;
  completed_at: string | null;
  retry_attempt_count: number;
  latest_retry_delta: number | null;
  retry_signal: string | null;
}

export interface TrainingDayDTO {
  day: number;
  title: string;
  focus: string;
  total_minutes: number;
  tasks: TrainingTaskDTO[];
}

export interface PersonalTrainingPlanDTO {
  days: number;
  generated_from: string[];
  readiness_score: number;
  summary: string;
  calibration: ScoreCalibrationDTO;
  plan: TrainingDayDTO[];
  quick_wins: string[];
}

export interface UpdateTrainingTaskProgressRequest {
  task_id: string;
  status: 'TODO' | 'COMPLETED';
  title?: string | null;
  task_type?: string | null;
  source_session_id?: string | null;
  question_index?: number | null;
  notes?: string | null;
}

export interface TrainingTaskProgressDTO {
  task_id: string;
  status: 'TODO' | 'COMPLETED' | string;
  completed_at: string | null;
  notes: string | null;
}

export interface TrainingTrendPointDTO {
  date: string;
  occurred_at: string | null;
  label: string;
  metric_type: 'INTERVIEW_SCORE' | 'RESUME_SCORE' | 'RETRY_DELTA' | 'TRAINING_DONE' | string;
  score: number | null;
  delta: number | null;
  completed_tasks: number;
  source_id: string | null;
}

export interface TrainingTrendDTO {
  summary: string;
  latest_interview_score: number | null;
  latest_resume_score: number | null;
  latest_retry_delta: number | null;
  completed_task_count: number;
  trend: TrainingTrendPointDTO[];
}
