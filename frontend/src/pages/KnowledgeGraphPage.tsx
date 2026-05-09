import { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Graph } from '@antv/g6';
import {
  Loader2,
  AlertCircle,
  Network,
  RefreshCw,
  ZoomIn,
  ZoomOut,
  Maximize2,
  X,
  ChevronRight,
  Search,
  Filter,
  Trash2,
} from 'lucide-react';
import { knowledgeGraphApi } from '../api/knowledgeGraph';
import type {
  GraphDataDTO,
  GraphNodeDTO,
  GraphEdgeDTO,
  EntityDetailDTO,
  TripleDTO,
} from '../types/knowledgeGraph';

const ENTITY_COLORS: Record<string, string> = {
  '技术': '#6366f1',
  '概念': '#10b981',
  '工具': '#f59e0b',
  '框架': '#8b5cf6',
  '公司': '#ec4899',
  '人': '#14b8a6',
  '面试题': '#f97316',
};

const ENTITY_TYPE_LIST = ['技术', '概念', '工具', '框架', '公司', '人', '面试题'];

export default function KnowledgeGraphPage() {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphDataDTO | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<EntityDetailDTO | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filterTypes, setFilterTypes] = useState<string[]>([]);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const fetchGraph = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const types = filterTypes.length > 0 ? filterTypes.join(',') : undefined;
      const data = await knowledgeGraphApi.getGraph({ entity_types: types, limit: 300 });
      setGraphData(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '加载图谱数据失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [filterTypes]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    if (graphRef.current) {
      graphRef.current.destroy();
      graphRef.current = null;
    }

    const nodes = graphData.nodes.map((n: GraphNodeDTO) => ({
      id: n.id,
      data: {
        label: n.label,
        type: n.type,
        size: n.size,
        properties: n.properties,
      },
    }));

    const edges = graphData.edges.map((e: GraphEdgeDTO, i: number) => ({
      id: `edge-${i}`,
      source: e.source,
      target: e.target,
      data: {
        relation: e.relation,
        confidence: e.confidence,
      },
    }));

    const graph = new Graph({
      container: containerRef.current,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      data: { nodes, edges },
      node: {
        style: {
          size: (d: any) => Math.max(20, Math.min(50, (d.data?.size || 1) * 6 + 14)),
          fill: (d: any) => ENTITY_COLORS[d.data?.type] || '#94a3b8',
          stroke: '#fff',
          lineWidth: 2,
          labelText: (d: any) => d.data?.label || '',
          labelFontSize: 11,
          labelFill: '#1e293b',
          labelFontWeight: 'bold',
          labelBackground: true,
          labelBackgroundFill: '#fff',
          labelBackgroundOpacity: 0.85,
          labelPadding: [2, 4],
          labelBackgroundRadius: 3,
          cursor: 'pointer',
          shadowColor: 'rgba(0,0,0,0.1)',
          shadowBlur: 8,
          shadowOffsetY: 2,
        },
        state: {
          active: {
            stroke: '#6366f1',
            lineWidth: 3,
            shadowColor: 'rgba(99,102,241,0.3)',
            shadowBlur: 12,
          },
          selected: {
            stroke: '#4f46e5',
            lineWidth: 4,
          },
        },
      },
      edge: {
        style: {
          stroke: '#cbd5e1',
          lineWidth: 1.5,
          endArrow: true,
          endArrowSize: 6,
          endArrowFill: '#cbd5e1',
          labelText: (d: any) => d.data?.relation || '',
          labelFontSize: 9,
          labelFill: '#64748b',
          labelBackground: true,
          labelBackgroundFill: '#fff',
          labelBackgroundOpacity: 0.9,
          labelPadding: [1, 3],
          labelBackgroundRadius: 2,
          cursor: 'pointer',
        },
        state: {
          active: {
            stroke: '#6366f1',
            lineWidth: 2.5,
          },
        },
      },
      layout: {
        type: 'd3-force',
        preventOverlap: true,
        nodeSize: (d: any) => Math.max(20, Math.min(50, (d.data?.size || 1) * 6 + 14)),
        collide: { radius: 30 },
        link: { distance: 120 },
        charge: { strength: -200 },
      },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element', { type: 'hover-activate' }],
      animation: true,
    });

    graph.on('node:click', async (evt: any) => {
      const nodeId = evt.target?.id || evt.data?.id;
      if (!nodeId) return;
      const nodeData = graphData.nodes.find((n) => n.id === nodeId);
      if (!nodeData) return;

      setDetailLoading(true);
      setSidebarOpen(true);
      try {
        const detail = await knowledgeGraphApi.getEntityDetail(nodeData.label, 2);
        setSelectedEntity(detail);
      } catch {
        setSelectedEntity(null);
      } finally {
        setDetailLoading(false);
      }
    });

    graph.render();
    graphRef.current = graph;

    const handleResize = () => {
      if (graphRef.current && containerRef.current) {
        graphRef.current.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (graphRef.current) {
        graphRef.current.destroy();
        graphRef.current = null;
      }
    };
  }, [graphData]);

  const handleZoomIn = () => graphRef.current?.zoomBy(1.2);
  const handleZoomOut = () => graphRef.current?.zoomBy(0.8);
  const handleFitView = () => graphRef.current?.fitView();

  const handleFilterToggle = (type: string) => {
    setFilterTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
    );
  };

  const handleSearch = (keyword: string) => {
    setSearchKeyword(keyword);
    if (!graphRef.current || !graphData) return;

    // 清除所有节点的 selected 状态
    for (const n of graphData.nodes) {
      graphRef.current.setElementState(n.id, 'default');
    }

    if (!keyword) return;

    // 高亮匹配节点
    const matchedIds = graphData.nodes
      .filter(n => n.label.toLowerCase().includes(keyword.toLowerCase()))
      .map(n => n.id);

    for (const id of matchedIds) {
      graphRef.current.setElementState(id, 'selected');
    }

    // 聚焦第一个匹配节点
    if (matchedIds.length > 0) {
      graphRef.current.focusElement(matchedIds[0]);
    }
  };

  const handleDeleteTriple = async (tripleId: number) => {
    if (!confirm('确定删除该三元组？')) return;
    try {
      await knowledgeGraphApi.deleteTriple(tripleId);
      if (selectedEntity) {
        const detail = await knowledgeGraphApi.getEntityDetail(selectedEntity.entity.name, 2);
        setSelectedEntity(detail);
      }
      fetchGraph();
    } catch {
      alert('删除失败');
    }
  };

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-violet-500/30">
            <Network className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">知识图谱</h1>
            <p className="text-sm text-slate-500">可视化知识关系网络</p>
          </div>
        </div>
        <button
          onClick={fetchGraph}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-all shadow-sm"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      {/* Stats bar */}
      {graphData?.stats && (
        <div className="flex items-center gap-4 text-sm">
          <span className="px-3 py-1.5 rounded-lg bg-violet-50 text-violet-700 font-medium">
            {graphData.stats.entity_count} 个实体
          </span>
          <span className="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 font-medium">
            {graphData.stats.triple_count} 条关系
          </span>
          {Object.entries(graphData.stats.type_distribution).map(([type, count]) => (
            <span
              key={type}
              className="px-2 py-1 rounded-lg text-xs font-medium"
              style={{
                backgroundColor: (ENTITY_COLORS[type] || '#94a3b8') + '15',
                color: ENTITY_COLORS[type] || '#94a3b8',
              }}
            >
              {type}: {count}
            </span>
          ))}
        </div>
      )}

      {/* Main area */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left: Graph */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Toolbar */}
          <div className="flex items-center gap-2 mb-3">
            {/* Search */}
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                placeholder="搜索实体..."
                value={searchKeyword}
                onChange={(e) => handleSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
              />
            </div>

            {/* Filter */}
            <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white border border-slate-200">
              <Filter className="w-4 h-4 text-slate-400 mr-1" />
              {ENTITY_TYPE_LIST.map((type) => (
                <button
                  key={type}
                  onClick={() => handleFilterToggle(type)}
                  className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                    filterTypes.includes(type)
                      ? 'text-white'
                      : 'text-slate-500 hover:bg-slate-100'
                  }`}
                  style={
                    filterTypes.includes(type)
                      ? { backgroundColor: ENTITY_COLORS[type] }
                      : undefined
                  }
                >
                  {type}
                </button>
              ))}
            </div>

            {/* Zoom controls */}
            <div className="flex items-center gap-1 px-1 py-1 rounded-lg bg-white border border-slate-200">
              <button onClick={handleZoomIn} className="p-1.5 rounded hover:bg-slate-100" title="放大">
                <ZoomIn className="w-4 h-4 text-slate-600" />
              </button>
              <button onClick={handleZoomOut} className="p-1.5 rounded hover:bg-slate-100" title="缩小">
                <ZoomOut className="w-4 h-4 text-slate-600" />
              </button>
              <button onClick={handleFitView} className="p-1.5 rounded hover:bg-slate-100" title="适应画布">
                <Maximize2 className="w-4 h-4 text-slate-600" />
              </button>
            </div>
          </div>

          {/* Graph canvas */}
          <div className="flex-1 relative rounded-2xl bg-white border border-slate-200/60 shadow-sm overflow-hidden">
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                <Loader2 className="w-8 h-8 text-violet-500 animate-spin" />
              </div>
            )}
            {error && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
                <AlertCircle className="w-10 h-10 text-red-400" />
                <p className="text-sm text-red-600">{error}</p>
                <button onClick={fetchGraph} className="text-sm text-violet-600 hover:underline">
                  重试
                </button>
              </div>
            )}
            {!loading && !error && graphData && graphData.nodes.length === 0 && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-400">
                <Network className="w-16 h-16" />
                <p className="text-lg font-medium">暂无图谱数据</p>
                <p className="text-sm">上传知识库文档后自动构建图谱</p>
                <button
                  onClick={() => navigate('/knowledgebases/upload')}
                  className="mt-2 px-4 py-2 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 text-white text-sm font-medium shadow-lg shadow-violet-500/30 hover:shadow-violet-500/50 transition-shadow"
                >
                  去上传文档
                </button>
              </div>
            )}
            <div ref={containerRef} className="w-full h-full" />
          </div>
        </div>

        {/* Right: Entity detail sidebar */}
        {sidebarOpen && (
          <div className="w-80 flex-shrink-0 bg-white rounded-2xl border border-slate-200/60 shadow-sm overflow-hidden flex flex-col">
            {/* Sidebar header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-900">实体详情</h3>
              <button onClick={() => setSidebarOpen(false)} className="p-1 rounded hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-400" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {detailLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 text-violet-500 animate-spin" />
                </div>
              ) : selectedEntity ? (
                <>
                  {/* Entity info */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="px-2 py-0.5 rounded text-xs font-medium text-white"
                        style={{ backgroundColor: ENTITY_COLORS[selectedEntity.entity.entity_type] || '#94a3b8' }}
                      >
                        {selectedEntity.entity.entity_type}
                      </span>
                      <span className="text-lg font-bold text-slate-900">{selectedEntity.entity.name}</span>
                    </div>
                    {selectedEntity.entity.description && (
                      <p className="text-sm text-slate-600">{selectedEntity.entity.description}</p>
                    )}
                    <p className="text-xs text-slate-400">
                      被提及 {selectedEntity.entity.mention_count} 次
                    </p>
                  </div>

                  {/* Related triples */}
                  <div>
                    <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                      关系 ({selectedEntity.related_triples.length})
                    </h4>
                    <div className="space-y-1.5">
                      {selectedEntity.related_triples.map((triple: TripleDTO) => {
                        const isSubject = triple.subject.name === selectedEntity.entity.name;
                        const other = isSubject ? triple.object : triple.subject;
                        return (
                          <div
                            key={triple.id}
                            className="group flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors text-sm"
                          >
                            <span className="text-slate-500 text-xs flex-shrink-0">
                              {isSubject ? '→' : '←'}
                            </span>
                            <span className="font-medium text-slate-700">{triple.predicate}</span>
                            <ChevronRight className="w-3 h-3 text-slate-300 flex-shrink-0" />
                            <button
                              onClick={() => {
                                knowledgeGraphApi.getEntityDetail(other.name, 2).then((d) => {
                                  setSelectedEntity(d);
                                  setSidebarOpen(true);
                                });
                              }}
                              className="text-violet-600 hover:underline truncate"
                            >
                              {other.name}
                            </button>
                            <button
                              onClick={() => handleDeleteTriple(triple.id)}
                              className="ml-auto opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-50 transition-opacity"
                              title="删除关系"
                            >
                              <Trash2 className="w-3 h-3 text-red-400" />
                            </button>
                          </div>
                        );
                      })}
                      {selectedEntity.related_triples.length === 0 && (
                        <p className="text-xs text-slate-400 py-2">暂无关系</p>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-slate-400 text-center py-8">点击节点查看详情</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span className="font-medium">图例：</span>
        {Object.entries(ENTITY_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
