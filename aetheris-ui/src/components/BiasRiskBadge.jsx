const RISK_STYLES = {
  low: 'text-emerald-300 ring-emerald-400/30',
  medium: 'text-amber-300 ring-amber-400/30',
  high: 'text-rose-300 ring-rose-400/30',
};

export default function BiasRiskBadge({ risk }) {
  if (!risk) return null;
  const style = RISK_STYLES[risk.toLowerCase()] ?? 'text-slate-300 ring-slate-500/30';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 bg-white/5 ${style}`} role="status" aria-label={`Bias risk: ${risk}`}>
      Bias risk: {risk}
    </span>
  );
}
