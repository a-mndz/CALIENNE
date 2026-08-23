function getConfidenceStyle(score) {
  if (score >= 0.8) return { label: 'High confidence', dot: 'bg-emerald-400', text: 'text-emerald-300', ring: 'ring-emerald-400/30' };
  if (score >= 0.5) return { label: 'Moderate confidence', dot: 'bg-amber-400', text: 'text-amber-300', ring: 'ring-amber-400/30' };
  return { label: 'Low confidence', dot: 'bg-rose-400', text: 'text-rose-300', ring: 'ring-rose-400/30' };
}

export default function ConfidenceBadge({ score }) {
  if (typeof score !== 'number' || Number.isNaN(score)) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ring-1 ring-slate-500/30 bg-white/5 text-slate-400" role="status" aria-label="Confidence unavailable">
        Confidence unavailable
      </span>
    );
  }
  const { label, dot, text, ring } = getConfidenceStyle(score);
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 bg-white/5 ${ring} ${text}`} role="status" aria-label={`${label}: ${(score * 100).toFixed(0)}%`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {label} · {(score * 100).toFixed(0)}%
    </span>
  );
}
