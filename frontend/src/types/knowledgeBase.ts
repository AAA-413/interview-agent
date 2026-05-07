export type AsyncTaskStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';

export interface KnowledgeChunkDTO {
  id: number;
  chunk_index: number;
  title: string | null;
  content: string;
  content_preview: string | null;
  metadata: Record<string, unknown>;
}

export interface RagReferenceDTO {
  chunk_id: number;
  chunk_index: number;
  title: string | null;
  content: string;
  content_preview: string;
  score: number;
  source_name: string;
  metadata: Record<string, unknown>;
}

export interface RagChatDTO {
  id: number;
  session_id: string;
  question: string;
  rewritten_query: string | null;
  answer: string | null;
  references: RagReferenceDTO[];
  status: 'PENDING' | 'COMPLETED' | 'FAILED';
  error_message: string | null;
  created_at: string;
}

export interface RagChatListItemDTO {
  id: number;
  session_id: string;
  question: string;
  status: 'PENDING' | 'COMPLETED' | 'FAILED';
  created_at: string;
}

export interface KnowledgeBaseListItemDTO {
  id: number;
  name: string;
  description: string | null;
  filename: string;
  file_size: number | null;
  chunk_count: number;
  document_count: number;
  index_status: AsyncTaskStatus;
  index_error: string | null;
  last_indexed_at: string | null;
  created_at: string;
}

export interface KnowledgeBaseDetailDTO {
  id: number;
  name: string;
  description: string | null;
  filename: string;
  file_size: number | null;
  content_type: string | null;
  storage_url: string | null;
  source_text: string | null;
  chunk_count: number;
  document_count: number;
  index_status: AsyncTaskStatus;
  index_error: string | null;
  last_indexed_at: string | null;
  created_at: string;
  chunks: KnowledgeChunkDTO[];
  recent_chats: RagChatDTO[];
}

export interface AskKnowledgeBaseRequest {
  question: string;
  session_id?: string | null;
  top_k?: number;
}

export interface RagAnswerDTO {
  session_id: string;
  rewritten_query: string;
  answer: string;
  references: RagReferenceDTO[];
}

export interface KnowledgeBaseReindexResponse {
  id: number;
  index_status: AsyncTaskStatus;
  index_error: string | null;
}
