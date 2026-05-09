import { request } from './request';
import type {
  GraphDataDTO,
  EntityDTO,
  EntityDetailDTO,
  TripleDTO,
  CreateTripleRequest,
} from '../types/knowledgeGraph';

interface EntityListResponse {
  items: EntityDTO[];
  total: number;
  page: number;
  size: number;
}

interface ExtractResultDTO {
  kb_id: number;
  entity_count: number;
  triple_count: number;
  duration_ms: number;
}

export const knowledgeGraphApi = {
  /** 获取图谱可视化数据 */
  getGraph(params?: { kb_id?: number; entity_types?: string; limit?: number }): Promise<GraphDataDTO> {
    const searchParams = new URLSearchParams();
    if (params?.kb_id) searchParams.set('kb_id', String(params.kb_id));
    if (params?.entity_types) searchParams.set('entity_types', params.entity_types);
    if (params?.limit) searchParams.set('limit', String(params.limit));
    const qs = searchParams.toString();
    return request.get<GraphDataDTO>(`/api/knowledge-graph/graph${qs ? `?${qs}` : ''}`);
  },

  /** 实体列表（分页） */
  getEntities(params?: { entity_type?: string; keyword?: string; page?: number; size?: number }): Promise<EntityListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.entity_type) searchParams.set('entity_type', params.entity_type);
    if (params?.keyword) searchParams.set('keyword', params.keyword);
    if (params?.page) searchParams.set('page', String(params.page));
    if (params?.size) searchParams.set('size', String(params.size));
    const qs = searchParams.toString();
    return request.get<EntityListResponse>(`/api/knowledge-graph/entities${qs ? `?${qs}` : ''}`);
  },

  /** 实体详情 + N跳关系 */
  getEntityDetail(name: string, depth = 2): Promise<EntityDetailDTO> {
    return request.get<EntityDetailDTO>(`/api/knowledge-graph/entity/${encodeURIComponent(name)}?depth=${depth}`);
  },

  /** 三元组列表 */
  getTriples(params?: { entity?: string; predicate?: string; kb_id?: number }): Promise<TripleDTO[]> {
    const searchParams = new URLSearchParams();
    if (params?.entity) searchParams.set('entity', params.entity);
    if (params?.predicate) searchParams.set('predicate', params.predicate);
    if (params?.kb_id) searchParams.set('kb_id', String(params.kb_id));
    const qs = searchParams.toString();
    return request.get<TripleDTO[]>(`/api/knowledge-graph/triples${qs ? `?${qs}` : ''}`);
  },

  /** 手动添加三元组 */
  createTriple(data: CreateTripleRequest): Promise<TripleDTO> {
    return request.post<TripleDTO>('/api/knowledge-graph/triples', data);
  },

  /** 删除三元组 */
  deleteTriple(tripleId: number): Promise<null> {
    return request.delete<null>(`/api/knowledge-graph/triples/${tripleId}`);
  },

  /** 重新抽取图谱 */
  reextract(kbId: number): Promise<ExtractResultDTO> {
    return request.post<ExtractResultDTO>(`/api/knowledge-graph/reextract/${kbId}`, {}, { timeout: 180000 });
  },
};
