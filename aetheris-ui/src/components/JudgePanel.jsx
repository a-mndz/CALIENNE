import { motion, AnimatePresence } from 'framer-motion';
import { Scale, AlertTriangle, CheckCircle2, ArrowRightLeft } from 'lucide-react';

/**
 * Parses the backend's justification string into structured fields.
 * Format: "Confidence: High | Bias Risk: Low | Disagreements: note1, note2"
 */
function parseJustification(justification) {
  if (!justification || typeof justification !== 'string') return null;

  const result = { confidence: null, biasRisk: null, disagreements: [] };

  const confMatch = justification.match(/Confidence:\s*([^|]+)/i);
  if (confMatch) result.confidence = confMatch[1].trim();

  const biasMatch = justification.match(/Bias Risk:\s*([^|]+)/i);
  if (biasMatch) result.biasRisk = biasMatch[1].trim();

  const disagreeMatch = justification.match(/Disagreements:\s*(.+)/i);
  if (disagreeMatch) {
    const raw = disagreeMatch[1].trim();
    if (raw.toLowerCase() !== 'none') {
      result.disagreements = raw.split(',').map((s) => s.trim()).filter(Boolean);
    }
  }

  return result;
}

function ScoreBar({ label, value, color, icon: Icon }) {
  const pct = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <div className="flex-1">
      <div className="flex justify-between text-xs text-slate-400 mb-1.5">
        <span className="flex items-center gap-1">
          {Icon && <Icon className="h-3 w-3" />}
          {label}
        </span>
        <span className="font-mono">{typeof value === 'number' ? (value * 10).toFixed(1) : '—'}/10</span>
      </div>
      <div className="h-2 rounded-full bg-white/5 overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${color}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}

export default function JudgePanel({ decision, agentOutputs }) {
  if (!decision) return null;

  const parsed = parseJustification(decision.justification);

  // Use individual agent confidence as proxy scores when score_a === score_b (backend bug workaround)
  const logicianConfidence = agentOutputs?.logician?.confidence;
  const creativeConfidence = agentOutputs?.creative?.confidence;
  const scoresIdentical = decision.score_a === decision.score_b;

  const scoreA = scoresIdentical && typeof logicianConfidence === 'number'
    ? logicianConfidence
    : decision.score_a;
  const scoreB = scoresIdentical && typeof creativeConfidence === 'number'
    ? creativeConfidence
    : decision.score_b;

  return (
    <div className="rounded-xl glass-panel agent-card-judge overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 p-4 pb-3">
        <Scale className="h-4 w-4 text-amber-400" />
        <h4 className="text-sm font-semibold text-slate-200">Judge Analysis</h4>
        {parsed?.confidence && (
          <span className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${
            parsed.confidence.toLowerCase() === 'high'
              ? 'text-emerald-300 bg-emerald-500/10 ring-1 ring-emerald-400/20'
              : parsed.confidence.toLowerCase() === 'medium'
              ? 'text-amber-300 bg-amber-500/10 ring-1 ring-amber-400/20'
              : 'text-rose-300 bg-rose-500/10 ring-1 ring-rose-400/20'
          }`}>
            {parsed.confidence} confidence
          </span>
        )}
      </div>

      <div className="px-4 pb-4 space-y-3">
        {/* Verdict */}
        <div className="flex items-center gap-2 bg-white/[0.03] rounded-lg p-3 border border-white/[0.06]">
          <CheckCircle2 className="h-4 w-4 text-amber-400 flex-shrink-0" />
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">Verdict</p>
            <p className="text-sm text-slate-100 font-medium capitalize">
              {decision.verdict || 'Not available'}
            </p>
          </div>
        </div>

        {/* Agent Score Comparison */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <ArrowRightLeft className="h-3 w-3 text-slate-400" />
            <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
              Agent Comparison
            </p>
          </div>
          <div className="flex items-center gap-4">
            <ScoreBar label="Logician" value={scoreA} color="bg-gradient-to-r from-cyan-500 to-cyan-400" />
            <ScoreBar label="Creative" value={scoreB} color="bg-gradient-to-r from-violet-500 to-violet-400" />
          </div>
        </div>

        {/* Bias Risk */}
        {parsed?.biasRisk && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-500">Bias Risk:</span>
            <span className={`font-medium px-2 py-0.5 rounded-full ${
              parsed.biasRisk.toLowerCase() === 'low'
                ? 'text-emerald-300 bg-emerald-500/10'
                : parsed.biasRisk.toLowerCase() === 'medium'
                ? 'text-amber-300 bg-amber-500/10'
                : 'text-rose-300 bg-rose-500/10'
            }`}>
              {parsed.biasRisk}
            </span>
          </div>
        )}

        {/* Disagreements */}
        {parsed?.disagreements?.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <AlertTriangle className="h-3 w-3 text-amber-400" />
              <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
                Disagreements Identified
              </p>
            </div>
            <div className="space-y-1.5">
              {parsed.disagreements.map((note, i) => (
                <div
                  key={i}
                  className="text-xs text-amber-200/80 bg-amber-500/[0.06] border border-amber-400/10 rounded-lg px-3 py-2"
                >
                  {note}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
