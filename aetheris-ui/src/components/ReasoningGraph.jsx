import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

const AGENT_COLORS = {
  Logician: { fill: '#22d3ee', stroke: '#22d3ee', bg: 'rgba(34,211,238,0.15)' },
  Creative: { fill: '#8b5cf6', stroke: '#8b5cf6', bg: 'rgba(139,92,246,0.15)' },
  Judge: { fill: '#f59e0b', stroke: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
  Judge_Logic: { fill: '#f59e0b', stroke: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
  Judge_Factual: { fill: '#34d399', stroke: '#34d399', bg: 'rgba(52,211,153,0.15)' },
  Breaker: { fill: '#34d399', stroke: '#34d399', bg: 'rgba(52,211,153,0.15)' },
};

const EDGE_COLORS = {
  supports: '#34d399',
  contradicts: '#fb7185',
  refines: '#8b5cf6',
};

function truncateText(text, maxLen) {
  if (!text) return '';
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text;
}

function buildGraphLayout(nodes) {
  if (nodes.length === 0) return [];

  const laid = [];
  const cols = Math.ceil(Math.sqrt(nodes.length));
  const rows = Math.ceil(nodes.length / cols);
  const spacingX = 200;
  const spacingY = 120;
  const offsetX = 60;
  const offsetY = 60;

  for (let i = 0; i < nodes.length; i++) {
    const col = i % cols;
    const row = Math.floor(i / cols);
    laid.push({
      ...nodes[i],
      x: offsetX + col * spacingX,
      y: offsetY + row * spacingY,
    });
  }

  return laid;
}

function NodeTooltip({ node, x, y }) {
  if (!node) return null;
  const colors = AGENT_COLORS[node.agent] || AGENT_COLORS.Logician;

  return (
    <div
      className="absolute z-10 pointer-events-none rounded-lg border border-white/10 bg-surface-800/95 backdrop-blur-xl p-3 shadow-xl max-w-[240px]"
      style={{ left: x + 12, top: y - 12 }}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <div className="h-2 w-2 rounded-full" style={{ backgroundColor: colors.fill }} />
        <span className="text-[10px] font-medium" style={{ color: colors.fill }}>{node.agent}</span>
        {typeof node.confidence === 'number' && (
          <span className="text-[10px] text-slate-500 ml-auto font-mono">
            {(node.confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>
      <p className="text-xs text-slate-300 leading-relaxed">{node.fullText || node.label}</p>
      {node.validationStatus && (
        <span className={`inline-block mt-1.5 text-[10px] font-medium px-1.5 py-0.5 rounded ${
          node.validationStatus === 'validated' ? 'bg-emerald-500/10 text-emerald-300' :
          node.validationStatus === 'rejected' ? 'bg-rose-500/10 text-rose-300' :
          'bg-amber-500/10 text-amber-300'
        }`}>
          {node.validationStatus}
        </span>
      )}
    </div>
  );
}

export default function ReasoningGraph({ nodes: inputNodes, edges: inputEdges }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [hoveredNode, setHoveredNode] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });

  const nodes = useMemo(() => buildGraphLayout(inputNodes || []), [inputNodes]);
  const edges = inputEdges || [];

  const connectedNodeIds = useMemo(() => {
    if (!selectedNodeId) return new Set();
    const ids = new Set([selectedNodeId]);
    for (const edge of edges) {
      if (edge.source === selectedNodeId) ids.add(edge.target);
      if (edge.target === selectedNodeId) ids.add(edge.source);
    }
    return ids;
  }, [selectedNodeId, edges]);

  const nodeMap = useMemo(() => {
    const map = {};
    for (const n of nodes) map[n.id] = n;
    return map;
  }, [nodes]);

  const handleZoomIn = useCallback(() => {
    setTransform((t) => ({ ...t, scale: Math.min(t.scale * 1.25, 4) }));
  }, []);

  const handleZoomOut = useCallback(() => {
    setTransform((t) => ({ ...t, scale: Math.max(t.scale / 1.25, 0.25) }));
  }, []);

  const handleReset = useCallback(() => {
    setTransform({ x: 0, y: 0, scale: 1 });
    setSelectedNodeId(null);
  }, []);

  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform((t) => ({
      ...t,
      scale: Math.min(Math.max(t.scale * delta, 0.25), 4),
    }));
  }, []);

  const handleMouseDown = useCallback((e) => {
    if (e.target.closest('.graph-node')) return;
    setIsPanning(true);
    panStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
  }, [transform]);

  const handleMouseMove = useCallback((e) => {
    if (!isPanning) return;
    const dx = e.clientX - panStart.current.x;
    const dy = e.clientY - panStart.current.y;
    setTransform((t) => ({ ...t, x: panStart.current.tx + dx, y: panStart.current.ty + dy }));
  }, [isPanning]);

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const handleTouchStart = useCallback((e) => {
    if (e.touches.length === 1) {
      const touch = e.touches[0];
      panStart.current = { x: touch.clientX, y: touch.clientY, tx: transform.x, ty: transform.y };
      setIsPanning(true);
    }
  }, [transform]);

  const handleTouchMove = useCallback((e) => {
    if (!isPanning || e.touches.length !== 1) return;
    const touch = e.touches[0];
    const dx = touch.clientX - panStart.current.x;
    const dy = touch.clientY - panStart.current.y;
    setTransform((t) => ({ ...t, x: panStart.current.tx + dx, y: panStart.current.ty + dy }));
  }, [isPanning]);

  const handleTouchEnd = useCallback(() => {
    setIsPanning(false);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  const handleNodeHover = useCallback((node, e) => {
    if (!node) {
      setHoveredNode(null);
      return;
    }
    const rect = containerRef.current?.getBoundingClientRect();
    if (rect) {
      setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    }
    setHoveredNode(node);
  }, []);

  const handleNodeClick = useCallback((nodeId) => {
    setSelectedNodeId((prev) => (prev === nodeId ? null : nodeId));
  }, []);

  if (!nodes.length) {
    return (
      <div className="flex items-center justify-center h-64 text-sm text-slate-500">
        <p>No reasoning graph data available</p>
      </div>
    );
  }

  const svgWidth = 800;
  const svgHeight = 500;

  return (
    <div className="relative" ref={containerRef}>
      <div className="absolute top-2 right-2 z-10 flex flex-col gap-1">
        <button
          onClick={handleZoomIn}
          aria-label="Zoom in"
          className="touch-target flex items-center justify-center rounded-lg bg-surface-700/80 border border-white/10 text-slate-400 hover:text-slate-200 hover:bg-surface-600 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan"
        >
          <ZoomIn className="h-4 w-4" />
        </button>
        <button
          onClick={handleZoomOut}
          aria-label="Zoom out"
          className="touch-target flex items-center justify-center rounded-lg bg-surface-700/80 border border-white/10 text-slate-400 hover:text-slate-200 hover:bg-surface-600 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan"
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <button
          onClick={handleReset}
          aria-label="Reset view"
          className="touch-target flex items-center justify-center rounded-lg bg-surface-700/80 border border-white/10 text-slate-400 hover:text-slate-200 hover:bg-surface-600 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan"
        >
          <Maximize2 className="h-4 w-4" />
        </button>
      </div>

      <div className="absolute bottom-2 left-2 z-10 flex items-center gap-2">
        {Object.entries(AGENT_COLORS).slice(0, 4).map(([agent, colors]) => (
          <div key={agent} className="flex items-center gap-1">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: colors.fill }} />
            <span className="text-[10px] text-slate-500">{agent}</span>
          </div>
        ))}
      </div>

      <NodeTooltip node={hoveredNode} x={tooltipPos.x} y={tooltipPos.y} />

      <svg
        ref={svgRef}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="w-full h-64 sm:h-80 rounded-xl bg-surface-900/50 border border-white/[0.06] cursor-grab active:cursor-grabbing touch-none"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        role="img"
        aria-label="Reasoning graph showing claims and their relationships between agents"
      >
        <title>Reasoning Graph</title>
        <desc>Interactive graph visualization showing claims as nodes and their relationships as edges, color-coded by agent type</desc>
        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.scale})`}>
          {edges.map((edge) => {
            const source = nodeMap[edge.source];
            const target = nodeMap[edge.target];
            if (!source || !target) return null;

            const isHighlighted = selectedNodeId && (
              connectedNodeIds.has(edge.source) && connectedNodeIds.has(edge.target)
            );
            const edgeColor = EDGE_COLORS[edge.type] || '#475569';
            const opacity = selectedNodeId ? (isHighlighted ? 0.8 : 0.1) : 0.4;

            return (
              <line
                key={edge.id}
                x1={source.x + 30}
                y1={source.y + 20}
                x2={target.x + 30}
                y2={target.y + 20}
                stroke={edgeColor}
                strokeWidth={isHighlighted ? 2 : 1}
                opacity={opacity}
                strokeDasharray={edge.type === 'contradicts' ? '4 4' : 'none'}
              />
            );
          })}

          {nodes.map((node) => {
            const colors = AGENT_COLORS[node.agent] || AGENT_COLORS.Logician;
            const isSelected = selectedNodeId === node.id;
            const isConnected = connectedNodeIds.has(node.id);
            const opacity = selectedNodeId ? (isConnected ? 1 : 0.25) : 1;

            return (
              <g
                key={node.id}
                className="graph-node"
                style={{ cursor: 'pointer', opacity }}
                onMouseEnter={(e) => handleNodeHover(node, e)}
                onMouseMove={(e) => handleNodeHover(node, e)}
                onMouseLeave={() => handleNodeHover(null)}
                onClick={() => handleNodeClick(node.id)}
              >
                <rect
                  x={node.x}
                  y={node.y}
                  width={120}
                  height={40}
                  rx={8}
                  fill={colors.bg}
                  stroke={isSelected ? colors.fill : `${colors.stroke}40`}
                  strokeWidth={isSelected ? 2 : 1}
                />
                <circle
                  cx={node.x + 12}
                  cy={node.y + 14}
                  r={4}
                  fill={colors.fill}
                />
                <text
                  x={node.x + 22}
                  y={node.y + 17}
                  fill={colors.fill}
                  fontSize={9}
                  fontWeight={600}
                >
                  {node.agent}
                </text>
                <text
                  x={node.x + 8}
                  y={node.y + 32}
                  fill="#cbd5e1"
                  fontSize={8}
                >
                  {truncateText(node.label, 18)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
