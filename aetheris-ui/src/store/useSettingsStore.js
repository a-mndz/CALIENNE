import { create } from 'zustand';

/**
 * Get the storage key for user settings based on logged-in email
 * Requirements: 25.6 (per-user settings persistence)
 */
function getStorageKey() {
  const email = localStorage.getItem('user_email') || 'anonymous';
  return `calienne.settings.${email}.v1`;
}

/**
 * Load persisted settings from localStorage
 */
function loadPersisted() {
  try {
    const raw = localStorage.getItem(getStorageKey());
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Persist settings to localStorage
 */
function persist(settings) {
  try {
    localStorage.setItem(getStorageKey(), JSON.stringify(settings));
  } catch {
    // localStorage unavailable (private browsing / quota exceeded) —
    // fail silently; in-memory state still functions for this session.
  }
}

/**
 * Default settings values
 */
const DEFAULT_SETTINGS = {
  messageDensity: 'comfortable', // 'compact' | 'comfortable'
  fontSize: 'medium', // 'small' | 'medium' | 'large'
  animationsEnabled: true,
  autoExpandReasoning: false,
  missionControlOpen: false,
  missionControlPinned: false,
};

// Load persisted settings or use defaults
const persisted = loadPersisted();
const initialSettings = persisted ? { ...DEFAULT_SETTINGS, ...persisted } : DEFAULT_SETTINGS;

/**
 * Settings store for user preferences
 * Requirements: 25.1-25.7 (user preferences)
 */
export const useSettingsStore = create((set) => ({
  ...initialSettings,

  /**
   * Update a single setting
   * Requirements: 25.2-25.5 (preference updates)
   */
  updateSetting: (key, value) => {
    set((state) => {
      const updated = { ...state, [key]: value };
      // Extract only the settings values for persistence (exclude methods)
      const settingsOnly = {
        messageDensity: updated.messageDensity,
        fontSize: updated.fontSize,
        animationsEnabled: updated.animationsEnabled,
        autoExpandReasoning: updated.autoExpandReasoning,
        missionControlOpen: updated.missionControlOpen,
        missionControlPinned: updated.missionControlPinned,
      };
      persist(settingsOnly);
      return { [key]: value };
    });
  },

  /**
   * Reset all settings to defaults
   * Requirements: 25.7 (reset to defaults)
   */
  resetToDefaults: () => {
    set(DEFAULT_SETTINGS);
    persist(DEFAULT_SETTINGS);
  },
}));
