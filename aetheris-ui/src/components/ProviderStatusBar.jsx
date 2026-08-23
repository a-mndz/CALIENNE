import { Activity, Menu, Settings, LayoutDashboard } from 'lucide-react';

const STATUS_COLOR = {
  online: 'bg-emerald-400',
  degraded: 'bg-amber-400',
  offline: 'bg-rose-400',
  unknown: 'bg-amber-400',
};

const STATUS_LABEL = {
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Offline',
  unknown: 'Unknown',
};

export default function ProviderStatusBar({
  providers,
  executionMode = 'Multi-Agent',
  onToggleTelemetry,
  onToggleSidebar,
  onToggleMissionControl,
  onToggleSettings,
  missionControlActive,
}) {
  return (
    <header className="flex items-center justify-between border-b border-white/5 bg-surface-800/40 px-4 py-2.5 md:px-8" role="banner">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="btn-icon touch-target md:hidden"
          aria-label="Open sidebar"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
        <span className="text-sm font-semibold text-slate-200 md:hidden">Calienne</span>
        <div className="hidden items-center gap-2 md:flex">
          <span className="text-xs text-slate-500">Adaptive Multi-Model Reasoning Orchestrator</span>
          <span className="rounded-md bg-surface-700/80 px-2 py-0.5 text-xs font-medium text-accent-cyan ring-1 ring-accent-cyan/20">
            {executionMode}
          </span>
        </div>
        <span className="rounded-md bg-surface-700/80 px-2 py-0.5 text-[11px] font-medium text-accent-cyan ring-1 ring-accent-cyan/20 md:hidden">
          {executionMode}
        </span>
      </div>

      <div className="flex items-center gap-4">
        <div className="hidden items-center gap-3 sm:flex">
          {providers.map((provider) => {
            const statusLabel = STATUS_LABEL[provider.status] ?? STATUS_LABEL.unknown;

            return (
              <span
                key={provider.name}
                className="group relative flex items-center gap-1.5 text-xs text-slate-400"
                title={`${provider.name}: ${statusLabel}`}
              >
                <span
                  className={`h-2.5 w-2.5 rounded-full ring-2 ring-black/20 ${STATUS_COLOR[provider.status] ?? STATUS_COLOR.unknown} ${
                    provider.status === 'online' ? 'animate-pulse-slow' : ''
                  }`}
                />
                <span className="hidden lg:inline">{provider.name}</span>
                <span className="text-[10px] lg:hidden">{provider.name?.split(' ')[0]}</span>
              </span>
            );
          })}
        </div>
        <button
          onClick={onToggleMissionControl}
          className={`touch-target ${missionControlActive ? 'btn-pill-active' : 'btn-pill text-slate-300'}`}
          aria-label="Toggle Mission Control"
          aria-pressed={missionControlActive}
        >
          <LayoutDashboard className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden lg:inline">Mission Control</span>
        </button>
        <button
          onClick={onToggleSettings}
          className="btn-pill touch-target text-slate-300"
          aria-label="Open settings"
        >
          <Settings className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">Settings</span>
        </button>
        <button
          onClick={onToggleTelemetry}
          className="btn-pill touch-target text-slate-300"
          aria-label="Open telemetry drawer"
        >
          <Activity className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">Telemetry</span>
        </button>
      </div>
    </header>
  );
}
