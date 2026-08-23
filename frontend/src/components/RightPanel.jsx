import { memo, useRef } from "react";
import { AlertTriangle, Check, PanelRightClose } from "lucide-react";
import { useFocusTrap } from "../hooks/useFocusTrap.js";
import LiveSparkline from "./LiveSparkline.jsx";
import { StatTileSkeleton } from "./Skeleton.jsx";
import { INSIGHTS } from "../constants/insights.js";

const RightPanel = memo(function RightPanel({ open, stats, models, conversations, activeId, onSelect, isNarrow, isLoaded, onClose }) {
  const innerRef = useRef(null);
  useFocusTrap(open && isNarrow, innerRef);
  return (
    <aside className={`rightpanel${open ? "" : " collapsed"}`} inert={!open} aria-hidden={!open}>
      <div className="rightpanel-inner" ref={innerRef}>
        {isNarrow && (
          <div className="panel-mobile-head">
            <div className="panel-mobile-title">Telemetry</div>
            <button type="button" className="icon-btn panel-close-btn" onClick={onClose} aria-label="Close telemetry panel">
              <PanelRightClose size={16} />
            </button>
          </div>
        )}
        <div className="panel-block">
          <div className="panel-head">
            <span className="status-dot" /> System status
          </div>
          <div className="status-sub">All systems operational</div>
          <LiveSparkline visible={open} data={stats.sparkline} />
          <div className={`stat-grid${isLoaded ? " stat-grid-loaded" : ""}`}>
            {isLoaded ? (
              <>
                <div className="stat-tile">
                  <div className="stat-label">Agents Online</div>
                  <div className="stat-value">{stats.agentsOnline}</div>
                </div>
                <div className="stat-tile">
                  <div className="stat-label">Total Tokens</div>
                  <div className="stat-value">{stats.tokens >= 1e6 ? (stats.tokens / 1e6).toFixed(2) + "M" : stats.tokens >= 1e3 ? (stats.tokens / 1e3).toFixed(1) + "K" : stats.tokens || 0}</div>
                </div>
                <div className="stat-tile">
                  <div className="stat-label">Avg. Response</div>
                  <div className="stat-value">{stats.avgResponse}{stats.avgResponse !== "—" && "s"}</div>
                </div>
                <div className="stat-tile">
                  <div className="stat-label">Success Rate</div>
                  <div className="stat-value">{stats.successRate}{stats.successRate !== "—" && "%"}</div>
                </div>
              </>
            ) : (
              <>
                <StatTileSkeleton />
                <StatTileSkeleton />
                <StatTileSkeleton />
                <StatTileSkeleton />
              </>
            )}
          </div>
        </div>

        <div className="panel-block">
          <div className="panel-head">Active models</div>
          <div className="model-list">
            {models.map((model) => (
              <div className="model-row" key={model.id}>
                <span>{model.name}</span>
                <span className="model-meta">
                  <span className="mono">{model.latency}</span>
                  <span className={`chip-dot${model.active ? " on" : ""}`} />
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel-block">
          <div className="panel-head">Aetheris insights</div>
          <div className="insight-list">
            {INSIGHTS.map((insight, i) => (
              <div className="insight-row" key={i}>
                {insight.kind === "warn" ? <AlertTriangle size={14} className="ins-warn" /> : <Check size={14} className="ins-ok" />}
                <div>
                  <div className="insight-title">{insight.title}</div>
                  <div className="insight-sub">{insight.sub}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel-block">
          <div className="panel-head-row">
            <span className="panel-head">Recent activity</span>
          </div>
          <div className="activity-list">
            {conversations.slice(0, 5).map((conv) => (
              <button key={conv.id} className={`activity-row${conv.id === activeId ? " active" : ""}`} onClick={() => onSelect(conv)}>
                <div className="activity-title">{conv.title}</div>
                <div className="activity-meta">
                  <span>{conv.mode}</span><span>·</span><span>{conv.agentsCount} agents</span>
                  {conv.score != null && <span className="activity-score">{conv.score}%</span>}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
});

export default RightPanel;
