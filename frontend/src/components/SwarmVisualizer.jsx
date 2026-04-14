import React from 'react';

const NODES = [
  { i: 0, id: 'Scout', label: 'Scout', x: 20, y: 70, w: 90, h: 32 },
  { i: 1, id: 'Architect', label: 'Architect', x: 140, y: 70, w: 90, h: 32 },
  { i: 2, id: 'Builder', label: 'Builder', x: 260, y: 70, w: 90, h: 32 },
  { i: 3, id: 'QA', label: 'QA Verifier', x: 380, y: 70, w: 100, h: 32 },
  { i: 4, id: 'Critic', label: 'Critic', x: 260, y: 130, w: 90, h: 32 },
  { i: 5, id: 'Integrator', label: 'Integrator', x: 510, y: 70, w: 100, h: 32 },
  { i: 6, id: 'Goal', label: '⚡ User Goal', x: 240, y: 10, w: 130, h: 32 }
];

const EDGES = [
  { id: 'e1', d: 'M 110 86 L 140 86', source: 0, target: 1 },
  { id: 'e2', d: 'M 230 86 L 260 86', source: 1, target: 2 },
  { id: 'e3', d: 'M 350 86 L 380 86', source: 2, target: 3 },
  { id: 'e4', d: 'M 480 86 L 510 86', source: 3, target: 5 },
  { id: 'e5', d: 'M 295 102 L 295 130', source: 2, target: 4 },
  { id: 'e6', d: 'M 315 130 L 315 102', source: 4, target: 2 },
  
  // Guardian lines (subtle dashed connections overhead)
  { id: 'g0', d: 'M 260 26 Q 160 26, 65 70', source: 6, target: 0, dashed: true },
  { id: 'g5', d: 'M 350 26 Q 450 26, 560 70', source: 6, target: 5, dashed: true }
];

export default function SwarmVisualizer({ agentStates }) {
  return (
    <div className="swarm-visualizer-container">
      <svg viewBox="0 0 630 170" className="swarm-svg">
        <defs>
          <filter id="node-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Render Edges */}
        {EDGES.map(edge => {
          // An edge lights up if either of its connected nodes is active
          const sActive = agentStates[edge.source] === 'active';
          const tActive = agentStates[edge.target] === 'active';
          const activeEdge = sActive || tActive;
          return (
            <path
              key={edge.id}
              d={edge.d}
              className={`edge-path ${activeEdge ? 'active-flow' : ''} ${edge.dashed ? 'dashed' : ''}`}
            />
          );
        })}

        {/* Render Nodes */}
        {NODES.map(node => {
          const state = agentStates[node.i] || 'idle';
          const isGoal = node.id === 'Goal';
          return (
            <g key={node.id} transform={`translate(${node.x}, ${node.y})`} className={`node-group state-${state}${isGoal ? ' node-goal' : ''}`}>
              <rect width={node.w} height={node.h} rx={6} ry={6} className="node-rect" />
              <circle cx={14} cy={16} r={4} className="node-dot" />
              <text x={24} y={20} className="node-text">{node.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
