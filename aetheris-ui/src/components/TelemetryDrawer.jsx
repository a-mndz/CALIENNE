import { useState, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import FocusTrap from 'focus-trap-react';
import {
  X,
  Clock,
  Gauge,
  Server,
  BarChart3,
  Activity,
  Download,
  Filter,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useSettingsStore } from '../store/useSettingsStore';

const TABS = [
  { key: 'metrics', label: 'Metrics', icon: BarChart3 },
  { key: 'events', label: 'Events', icon: Activity },
  { key: 'providers', label: 'Providers', icon: Server },
  { key: 'export', label: 'Export', icon: Download },
];

function formatLatency(ms) {
  if (ms == null || isNaN(ms)) return '\u2014';
  if (ms < 1000) return `${ms}ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds >= 60) {
    const roundedSeconds = Math.round(totalSeconds);
    const minutes = Math.floor(roundedSeconds / 60);
    const seconds = roundedSeconds % 60;
    return `${minutes}m ${seconds}s`;
  }
  return `${totalSeconds.toFixed(1)}s`;
}

function formatTimestamp(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function Stat({ label, value, icon: Icon }) {
  return (
    <div className="rounded-xl glass-panel p-3">
      <div className="flex items-center gap-1.5 mb-1">
        {Icon && <Icon className="h-3 w-3 text-slate-500" />}
        <p className="text-[11px] text-slate-500">{label}</p>
      </div>
      <p className="text-lg font-semibold text-slate-100">{value}</p>
    </div>
  );
}

function MetricsTab({ telemetry }) {
  const totalCalls = telemetry.length;
  const avgLatencyVal = totalCalls
    ? Math.round(telemetry.reduce((sum, t) => sum + (t.latencyMs || 0), 0) / totalCalls)
    : 0;
  const avgConfidence = totalCalls
    ? (telemetry.reduce((sum, t) => sum + (t.confidence ?? 0), 0) / totalCalls * 100).toFixed(0)
    : 0;

  const confidenceDistribution = useMemo(() => {
    const dist = { high: 0, medium: 0, low: 0, none: 0 };
    for (const t of telemetry) {
      if (t.confidence == null) { dist.none++; continue; }
      if (t.confidence >= 0.8) dist.high++;
      else if (t.confidence >= 0.5) dist.medium++;
      else dist.low++;
    }
    return dist;
  }, [telemetry]);

  const totalLatency = telemetry.reduce((sum, t) => sum + (t.latencyMs || 0), 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat icon={Server} label="API calls" value={totalCalls} />
        <Stat icon={Clock} label="Avg latency" value={formatLatency(avgLatencyVal)} />
        <Stat icon={Gauge} label="Avg conf." value={`${avgConfidence}%`} />
      </div>

      <div className="rounded-xl glass-panel p-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-2">
          Confidence Distribution
        </p>
        <div className="space-y-1.5">
          {[
            { label: 'High (\u226580%)', count: confidenceDistribution.high, color: 'bg-emerald-400' },
            { label: 'Medium (50-79%)', count: confidenceDistribution.medium, color: 'bg-amber-400' },
            { label: 'Low (<50%)', count: confidenceDistribution.low, color: 'bg-rose-400' },
          ].map((row) => (
            <div key={row.label} className="flex items-center gap-2">
              <span className="text-[11px] text-slate-400 w-28 flex-shrink-0">{row.label}</span>
              <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                <div
                  className={`h-full ${row.color} rounded-full transition-all duration-300`}
                  style={{ width: totalCalls > 0 ? `${(row.count / totalCalls) * 100}%` : '0%' }}
                />
              </div>
              <span className="text-[11px] text-slate-400 font-mono w-6 text-right">{row.count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl glass-panel p-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-2">
          Total Execution Time
        </p>
        <p className="text-lg font-semibold text-slate-100 font-mono">{formatLatency(totalLatency)}</p>
      </div>

      <div className="space-y-2">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
          Query History (last 20)
        </p>
        <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
          {telemetry.slice(0, 20).map((t) => (
            <div key={t.id} className={`rounded-lg glass-panel p-2.5 text-xs ${t.error ? 'ring-1 ring-rose-400/20' : ''}`}>
              <div className="flex items-center gap-1.5 mb-1.5">
                {t.error && <XCircle className="h-3 w-3 text-rose-400 flex-shrink-0" aria-label="Error" />}
                <p className="truncate text-slate-300 font-medium flex-1">{t.query}</p>
              </div>
              {t.error && (
                <p className="text-[10px] text-rose-300/80 mb-1.5 leading-relaxed line-clamp-2">{t.error}</p>
              )}
              <div className="grid grid-cols-1 gap-x-3 gap-y-0.5 text-slate-500 sm:grid-cols-2">
                <div className="flex justify-between">
                  <span>Latency</span>
                  <span className="text-slate-300 font-mono">{formatLatency(t.latencyMs)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Confidence</span>
                  <span className="text-slate-300 font-mono">
                    {t.confidence != null ? `${(t.confidence * 100).toFixed(0)}%` : '\u2014'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Bias Risk</span>
                  <span className={`font-medium ${
                    t.biasRisk?.toLowerCase() === 'low' ? 'text-emerald-400' :
                    t.biasRisk?.toLowerCase() === 'medium' ? 'text-amber-400' :
                    t.biasRisk?.toLowerCase() === 'high' ? 'text-rose-400' : 'text-slate-400'
                  }`}>
                    {t.biasRisk ?? '\u2014'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Provider</span>
                  <span className="text-slate-300">{t.provider ?? '\u2014'}</span>
                </div>
              </div>
            </div>
          ))}
          {telemetry.length === 0 && (
            <div className="text-center py-6">
              <p className="text-sm text-slate-500">No requests yet</p>
              <p className="text-xs text-slate-600 mt-1">Send a query to see telemetry data</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EventsTab({ liveEvents }) {
  const [filter, setFilter] = useState('');
  const scrollRef = useRef(null);

  const events = liveEvents || [];
  const filteredEvents = filter
    ? events.filter((e) => e.event === filter)
    : events;

  const eventTypes = useMemo(() => {
    const types = new Set(events.map((e) => e.event));
    return [...types];
  }, [events]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredEvents.length]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Filter className="h-3 w-3 text-slate-500" />
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="input-field touch-target text-xs rounded-md px-2 py-1 flex-1"
          aria-label="Filter events by type"
        >
          <option value="">All events</option>
          {eventTypes.map((type) => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
        <span className="text-[10px] text-slate-500 font-mono">{filteredEvents.length}</span>
      </div>

      <div ref={scrollRef} className="space-y-1 max-h-[calc(100vh-280px)] overflow-y-auto pr-1">
        {filteredEvents.map((event, i) => (
          <div key={`${event.timestamp}-${i}`} className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-2 text-xs font-mono">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-slate-500 text-[10px]">{formatTimestamp(event.timestamp)}</span>
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                event.event === 'error' ? 'bg-rose-500/10 text-rose-300' :
                event.event === 'result' ? 'bg-emerald-500/10 text-emerald-300' :
                'bg-cyan-500/10 text-cyan-300'
              }`}>
                {event.event}
              </span>
            </div>
            <pre className="text-[10px] text-slate-400 whitespace-pre-wrap break-all line-clamp-3">
              {JSON.stringify(event.payload || {}, null, 1)}
            </pre>
          </div>
        ))}
        {filteredEvents.length === 0 && (
          <div className="text-center py-6">
            <p className="text-sm text-slate-500">No events captured</p>
            <p className="text-xs text-slate-600 mt-1">Events will appear here during pipeline execution</p>
          </div>
        )}
      </div>
    </div>
  );
}

function ProvidersTab({ providers }) {
  const providerList = providers || [];

  return (
    <div className="space-y-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
        Provider Status
      </p>
      <div className="space-y-2">
        {providerList.map((p) => (
          <div key={p.name} className="rounded-xl glass-panel p-3 flex items-center gap-3">
            <div className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${
              p.status === 'online' ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]' :
              p.status === 'offline' ? 'bg-rose-400 shadow-[0_0_6px_rgba(251,113,133,0.5)]' :
              'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.5)]'
            }`} />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-200">{p.name}</p>
              <p className="text-[10px] text-slate-500 capitalize">{p.status}</p>
            </div>
            {p.status === 'online' && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
            {p.status === 'offline' && <XCircle className="h-4 w-4 text-rose-400" />}
            {p.status === 'unknown' && <AlertTriangle className="h-4 w-4 text-amber-400" />}
          </div>
        ))}
        {providerList.length === 0 && (
          <div className="text-center py-6">
            <WifiOff className="h-6 w-6 text-slate-600 mx-auto mb-2" />
            <p className="text-sm text-slate-500">No provider data</p>
          </div>
        )}
      </div>

      <div className="rounded-xl glass-panel p-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-2">
          Selection Logic
        </p>
        <p className="text-xs text-slate-400 leading-relaxed">
          Providers are selected based on availability and health status. The system falls back to
          alternative providers when the primary is unavailable. Health is polled every 30 seconds.
        </p>
      </div>
    </div>
  );
}

function ExportTab({ telemetry, providers }) {
  const handleExportTelemetry = () => {
    const data = JSON.stringify({ telemetry, exportedAt: new Date().toISOString() }, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `calienne-telemetry-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportProviders = () => {
    const data = JSON.stringify({ providers, exportedAt: new Date().toISOString() }, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `calienne-providers-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportAll = () => {
    const data = JSON.stringify({
      telemetry,
      providers,
      exportedAt: new Date().toISOString(),
    }, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `calienne-full-export-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
        Export Telemetry Data
      </p>

      <button
        onClick={handleExportTelemetry}
        className="w-full flex items-center gap-3 rounded-xl glass-panel p-3 text-left hover:bg-white/[0.04] transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-offset-2 focus:ring-offset-surface-900"
      >
        <div className="h-8 w-8 rounded-lg bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
          <Download className="h-4 w-4 text-cyan-400" />
        </div>
        <div>
          <p className="text-sm font-medium text-slate-200">Export Telemetry</p>
          <p className="text-[10px] text-slate-500">{telemetry.length} entries as JSON</p>
        </div>
      </button>

      <button
        onClick={handleExportProviders}
        className="w-full flex items-center gap-3 rounded-xl glass-panel p-3 text-left hover:bg-white/[0.04] transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-offset-2 focus:ring-offset-surface-900"
      >
        <div className="h-8 w-8 rounded-lg bg-violet-500/10 flex items-center justify-center flex-shrink-0">
          <Server className="h-4 w-4 text-violet-400" />
        </div>
        <div>
          <p className="text-sm font-medium text-slate-200">Export Providers</p>
          <p className="text-[10px] text-slate-500">{providers?.length || 0} providers as JSON</p>
        </div>
      </button>

      <button
        onClick={handleExportAll}
        className="w-full flex items-center gap-3 rounded-xl glass-panel p-3 text-left hover:bg-white/[0.04] transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-offset-2 focus:ring-offset-surface-900"
      >
        <div className="h-8 w-8 rounded-lg bg-emerald-500/10 flex items-center justify-center flex-shrink-0">
          <BarChart3 className="h-4 w-4 text-emerald-400" />
        </div>
        <div>
          <p className="text-sm font-medium text-slate-200">Export All</p>
          <p className="text-[10px] text-slate-500">Complete telemetry + provider data</p>
        </div>
      </button>
    </div>
  );
}

export default function TelemetryDrawer({ open, onClose, telemetry, liveEvents, providers }) {
  const [activeTab, setActiveTab] = useState('metrics');
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <FocusTrap active={open}>
          <div>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={onClose}
              className="fixed inset-0 z-40 bg-black/40"
              aria-hidden="true"
            />
            <motion.aside
              role="dialog"
              aria-label="Telemetry Dashboard"
              aria-modal="true"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 300, damping: 32 }}
              className="fixed right-0 top-0 z-50 h-full w-full sm:max-w-[400px] border-l border-white/10 bg-surface-800/95 backdrop-blur-xl flex flex-col"
            >
              <div className="flex items-center justify-between p-4 border-b border-white/[0.06]">
                <h3 className="text-sm font-semibold text-slate-200">Telemetry Dashboard</h3>
                <button
                  onClick={onClose}
                  aria-label="Close telemetry panel"
                  className="btn-icon touch-target"
                >
                  <X className="h-5 w-5" aria-hidden="true" />
                </button>
              </div>

              <div role="tablist" aria-label="Telemetry sections" className="flex border-b border-white/[0.06] px-2">
                {TABS.map((tab) => {
                  const Icon = tab.icon;
                  const isActive = activeTab === tab.key;
                  return (
                    <button
                      key={tab.key}
                      role="tab"
                      aria-selected={isActive}
                      aria-controls={`tabpanel-${tab.key}`}
                      id={`tab-${tab.key}`}
                      onClick={() => setActiveTab(tab.key)}
                      className={`flex touch-target items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-inset ${
                        isActive
                          ? 'border-cyan-400 text-cyan-300'
                          : 'border-transparent text-slate-500 hover:text-slate-300'
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="hidden sm:inline">{tab.label}</span>
                    </button>
                  );
                })}
              </div>

              <div className="flex-1 overflow-y-auto p-4">
                <div
                  role="tabpanel"
                  id={`tabpanel-${activeTab}`}
                  aria-labelledby={`tab-${activeTab}`}
                  tabIndex={0}
                >
                  {activeTab === 'metrics' && <MetricsTab telemetry={telemetry || []} />}
                  {activeTab === 'events' && <EventsTab liveEvents={liveEvents} />}
                  {activeTab === 'providers' && <ProvidersTab providers={providers} />}
                  {activeTab === 'export' && <ExportTab telemetry={telemetry || []} providers={providers} />}
                </div>
              </div>
            </motion.aside>
          </div>
        </FocusTrap>
      )}
    </AnimatePresence>
  );
}
