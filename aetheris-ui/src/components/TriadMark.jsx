// Signature visual motif for Calienne: two opposing agents (cyan = logician,
// violet = creative) converging on a judge node (amber). Reused at small
// scale in the header and pipeline visualization so the product's actual
// mechanic — two reasoning styles reconciled by a judge — is legible as a
// mark, not just described in text.
export default function TriadMark({ size = 20, active = false, className = '' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} fill="none">
      <line x1="7" y1="9" x2="16" y2="22" stroke="#22d3ee" strokeWidth="1.4" strokeOpacity="0.6" />
      <line x1="25" y1="9" x2="16" y2="22" stroke="#8b5cf6" strokeWidth="1.4" strokeOpacity="0.6" />
      <circle cx="7" cy="9" r="3.4" fill="#22d3ee" fillOpacity="0.9" />
      <circle cx="25" cy="9" r="3.4" fill="#8b5cf6" fillOpacity="0.9" />
      <circle
        cx="16"
        cy="22"
        r="4"
        fill="#f59e0b"
        fillOpacity={active ? '1' : '0.85'}
        className={active ? 'animate-pulse-slow' : ''}
      />
    </svg>
  );
}
