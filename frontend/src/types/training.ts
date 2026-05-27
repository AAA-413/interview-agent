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
