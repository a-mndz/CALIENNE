import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import FocusTrap from 'focus-trap-react';
import { X, RotateCcw, MessageSquareText, Type, Sparkles, Eye, LayoutDashboard } from 'lucide-react';
import { useSettingsStore } from '../store/useSettingsStore';

function Toggle({ label, description, checked, onChange, icon: Icon }) {
  return (
    <div className="flex items-start gap-3 rounded-xl glass-panel p-3">
      {Icon && (
        <div className="h-8 w-8 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Icon className="h-4 w-4 text-slate-400" aria-hidden="true" />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-200">{label}</p>
        {description && <p className="text-[11px] text-slate-500 mt-0.5">{description}</p>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-7 w-12 flex-shrink-0 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-offset-2 focus:ring-offset-surface-900 ${
          checked ? 'bg-accent-cyan' : 'bg-surface-600'
        }`}
      >
        <span
          className={`inline-block h-6 w-6 rounded-full bg-white shadow-sm transform transition-transform duration-200 mt-0.5 ${
            checked ? 'translate-x-[1.375rem]' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  );
}

function RadioGroup({ label, description, value, options, onChange, icon: Icon }) {
  return (
    <div className="rounded-xl glass-panel p-3">
      <div className="flex items-start gap-3 mb-2.5">
        {Icon && (
          <div className="h-8 w-8 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
            <Icon className="h-4 w-4 text-slate-400" aria-hidden="true" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-200">{label}</p>
          {description && <p className="text-[11px] text-slate-500 mt-0.5">{description}</p>}
        </div>
      </div>
      <div className="flex gap-1.5 ml-11" role="radiogroup" aria-label={label}>
        {options.map((opt) => (
          <button
            key={opt.value}
            role="radio"
            aria-checked={value === opt.value}
            onClick={() => onChange(opt.value)}
            className={`flex-1 touch-target px-3 py-2 text-xs font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan ${
              value === opt.value
                ? 'bg-accent-cyan/15 text-cyan-300 ring-1 ring-cyan-400/30'
                : 'bg-white/5 text-slate-400 hover:text-slate-300 hover:bg-white/[0.08]'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function SettingsPanel({ open, onClose }) {
  const messageDensity = useSettingsStore((s) => s.messageDensity);
  const fontSize = useSettingsStore((s) => s.fontSize);
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);
  const autoExpandReasoning = useSettingsStore((s) => s.autoExpandReasoning);
  const missionControlOpen = useSettingsStore((s) => s.missionControlOpen);
  const updateSetting = useSettingsStore((s) => s.updateSetting);
  const resetToDefaults = useSettingsStore((s) => s.resetToDefaults);

  const panelRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  useEffect(() => {
    if (open && panelRef.current) {
      const focusable = panelRef.current.querySelector('button, [tabindex]');
      if (focusable) focusable.focus();
    }
  }, [open]);

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
              className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
              aria-hidden="true"
            />
            <motion.div
              ref={panelRef}
              role="dialog"
              aria-label="Settings"
              aria-modal="true"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className="fixed inset-4 sm:inset-auto sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 sm:w-full sm:max-w-md z-50 rounded-2xl bg-surface-800/95 backdrop-blur-xl border border-white/10 shadow-xl flex flex-col overflow-hidden"
            >
              <div className="flex items-center justify-between p-4 border-b border-white/[0.06]">
                <h2 className="text-sm font-semibold text-slate-200">Settings</h2>
                <button
                  onClick={onClose}
                  aria-label="Close settings"
                  className="btn-icon touch-target"
                >
                  <X className="h-5 w-5" aria-hidden="true" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                <RadioGroup
                  label="Message Density"
                  description="Adjust spacing between messages"
                  value={messageDensity}
                  onChange={(val) => updateSetting('messageDensity', val)}
                  icon={MessageSquareText}
                  options={[
                    { value: 'compact', label: 'Compact' },
                    { value: 'comfortable', label: 'Comfortable' },
                  ]}
                />

                <RadioGroup
                  label="Font Size"
                  description="Base text size for the interface"
                  value={fontSize}
                  onChange={(val) => updateSetting('fontSize', val)}
                  icon={Type}
                  options={[
                    { value: 'small', label: 'Small' },
                    { value: 'medium', label: 'Medium' },
                    { value: 'large', label: 'Large' },
                  ]}
                />

                <Toggle
                  label="Animations"
                  description="Enable smooth transitions and effects"
                  checked={animationsEnabled}
                  onChange={(val) => updateSetting('animationsEnabled', val)}
                  icon={Sparkles}
                />

                <Toggle
                  label="Auto-Expand Reasoning"
                  description="Automatically expand reasoning panels on responses"
                  checked={autoExpandReasoning}
                  onChange={(val) => updateSetting('autoExpandReasoning', val)}
                  icon={Eye}
                />

                <Toggle
                  label="Mission Control"
                  description="Show Mission Control panel by default"
                  checked={missionControlOpen}
                  onChange={(val) => updateSetting('missionControlOpen', val)}
                  icon={LayoutDashboard}
                />
              </div>

              <div className="p-4 border-t border-white/[0.06]">
                <button
                  onClick={resetToDefaults}
                  className="btn-ghost w-full flex items-center justify-center gap-2 text-xs"
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  Reset to Defaults
                </button>
              </div>
            </motion.div>
          </div>
        </FocusTrap>
      )}
    </AnimatePresence>
  );
}
