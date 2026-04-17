export interface ResumeListItemDTO {
  id: number;
  filename: string;
  file_size: number | null;
  uploaded_at: string;
  access_count: number;
  latest_score: number | null;
  last_analyzed_at: string | null;
  interview_count: number;
  analyze_status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  analyze_error: string | null;
}

export interface ScoreDetail {
  content_score: number;
  structure_score: number;
  skill_match_score: number;
  expression_score: number;
  project_score: number;
}

export interface Suggestion {
  category: string;
  priority: string;
  issue: string;
  recommendation: string;
}

export interface AnalysisHistoryDTO {
  id: number;
  overall_score: number | null;
  content_score: number | null;
  structure_score: number | null;
  skill_match_score: number | null;
  expression_score: number | null;
  project_score: number | null;
  summary: string | null;
  analyzed_at: string;
  strengths: string[];
  suggestions: Suggestion[];
}

export interface ResumeDetailDTO {
  id: number;
  filename: string;
  file_size: number | null;
  content_type: string | null;
  storage_url: string | null;
  uploaded_at: string;
  access_count: number;
  resume_text: string | null;
  analyze_status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  analyze_error: string | null;
  analyses: AnalysisHistoryDTO[];
}
