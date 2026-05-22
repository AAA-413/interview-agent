import { apiUrl, request } from './request';
import type {
  AskKnowledgeBaseRequest,
  KnowledgeBaseDetailDTO,
  KnowledgeBaseListItemDTO,
  KnowledgeBaseReindexResponse,
  RagAnswerDTO,
  RagChatDTO,
  RagChatListItemDTO,
} from '../types/knowledgeBase';

export const knowledgeBaseApi = {
  async listKnowledgeBases(): Promise<KnowledgeBaseListItemDTO[]> {
    return request.get<KnowledgeBaseListItemDTO[]>('/api/knowledgebase');
  },

  async getKnowledgeBase(id: number): Promise<KnowledgeBaseDetailDTO> {
    return request.get<KnowledgeBaseDetailDTO>(`/api/knowledgebase/${id}`);
  },

  async uploadKnowledgeBase(file: File, payload?: { name?: string; description?: string }): Promise<KnowledgeBaseDetailDTO> {
    const formData = new FormData();
    formData.append('file', file);
    if (payload?.name) {
      formData.append('name', payload.name);
    }
    if (payload?.description) {
      formData.append('description', payload.description);
    }
    return request.upload<KnowledgeBaseDetailDTO>('/api/knowledgebase', formData);
  },

  async fetchFromUrl(payload: { url: string; name?: string; description?: string; max_length?: number }): Promise<KnowledgeBaseDetailDTO> {
    return request.post<KnowledgeBaseDetailDTO>('/api/knowledgebase/fetch', payload);
  },

  async reindexKnowledgeBase(id: number): Promise<KnowledgeBaseReindexResponse> {
    return request.post<KnowledgeBaseReindexResponse>(`/api/knowledgebase/${id}/reindex`);
  },

  async deleteKnowledgeBase(id: number): Promise<void> {
    return request.delete(`/api/knowledgebase/${id}`);
  },

  async askKnowledgeBase(id: number, payload: AskKnowledgeBaseRequest): Promise<RagAnswerDTO> {
    return request.post<RagAnswerDTO>(`/api/knowledgebase/${id}/chat`, payload, {
      timeout: 180000,
    });
  },

  async listChats(id: number): Promise<RagChatListItemDTO[]> {
    return request.get<RagChatListItemDTO[]>(`/api/knowledgebase/${id}/chats`);
  },

  async streamKnowledgeBaseAnswer(
    id: number,
    payload: AskKnowledgeBaseRequest,
    handlers: {
      onMeta?: (data: Record<string, unknown>) => void;
      onChunk?: (chunk: string) => void;
      onReferences?: (refs: unknown[]) => void;
      onDone?: (data: Record<string, unknown>) => void;
    },
  ): Promise<void> {
    const token = localStorage.getItem('access_token');
    const response = await fetch(apiUrl(`/api/knowledgebase/${id}/chat/stream`), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token_type');
        window.location.href = '/login';
        throw new Error('登录已过期，请重新登录');
      }
      throw new Error('流式问答连接失败');
    }
    if (!response.body) {
      throw new Error('流式问答连接失败');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const processEvent = (eventBlock: string) => {
      const lines = eventBlock.split('\n').map(line => line.trim()).filter(Boolean);
      const eventLine = lines.find(line => line.startsWith('event:'));
      const dataLine = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('');
      if (!eventLine || !dataLine) return;

      const eventName = eventLine.slice(6).trim();
      const data = JSON.parse(dataLine);

      switch (eventName) {
        case 'meta':
          handlers.onMeta?.(data);
          break;
        case 'chunk':
          handlers.onChunk?.(typeof data.content === 'string' ? data.content : '');
          break;
        case 'references':
          handlers.onReferences?.(Array.isArray(data.items) ? data.items : []);
          break;
        case 'done':
          handlers.onDone?.(data);
          break;
        default:
          break;
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const event of events) {
        processEvent(event);
      }
    }

    if (buffer.trim()) {
      processEvent(buffer);
    }
  },

  async listCrossKBChats(): Promise<RagChatListItemDTO[]> {
    return request.get<RagChatListItemDTO[]>('/api/cross-knowledgebase/cross/chats');
  },

  async getCrossKBSessionHistory(sessionId: string): Promise<RagChatDTO[]> {
    return request.get<RagChatDTO[]>('/api/cross-knowledgebase/cross/chat/history', { params: { session_id: sessionId } });
  },

  async deleteCrossKBSession(sessionId: string): Promise<{ deleted: number }> {
    return request.delete<{ deleted: number }>(`/api/cross-knowledgebase/cross/chats/${sessionId}`);
  },

  async getKBSessionHistory(kbId: number, sessionId: string): Promise<RagChatDTO[]> {
    return request.get<RagChatDTO[]>(`/api/knowledgebase/${kbId}/chat/history`, { params: { session_id: sessionId } });
  },

  async deleteKBSession(kbId: number, sessionId: string): Promise<{ deleted: number }> {
    return request.delete<{ deleted: number }>(`/api/knowledgebase/${kbId}/chats/${sessionId}`);
  },

  async streamCrossKBAnswer(
    payload: AskKnowledgeBaseRequest,
    handlers: {
      onMeta?: (data: Record<string, unknown>) => void;
      onChunk?: (chunk: string) => void;
      onReferences?: (refs: unknown[]) => void;
      onDone?: (data: Record<string, unknown>) => void;
    },
  ): Promise<void> {
    const token = localStorage.getItem('access_token');
    const response = await fetch(apiUrl('/api/cross-knowledgebase/cross/chat/stream'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token_type');
        window.location.href = '/login';
        throw new Error('登录已过期，请重新登录');
      }
      throw new Error('流式问答连接失败');
    }
    if (!response.body) {
      throw new Error('流式问答连接失败');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const processEvent = (eventBlock: string) => {
      const lines = eventBlock.split('\n').map(line => line.trim()).filter(Boolean);
      const eventLine = lines.find(line => line.startsWith('event:'));
      const dataLine = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('');
      if (!eventLine || !dataLine) return;

      const eventName = eventLine.slice(6).trim();
      const data = JSON.parse(dataLine);

      switch (eventName) {
        case 'meta':
          handlers.onMeta?.(data);
          break;
        case 'chunk':
          handlers.onChunk?.(typeof data.content === 'string' ? data.content : '');
          break;
        case 'references':
          handlers.onReferences?.(Array.isArray(data.items) ? data.items : []);
          break;
        case 'done':
          handlers.onDone?.(data);
          break;
        default:
          break;
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const event of events) {
        processEvent(event);
      }
    }

    if (buffer.trim()) {
      processEvent(buffer);
    }
  },
};
