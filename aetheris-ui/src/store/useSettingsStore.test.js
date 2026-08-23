import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useSettingsStore } from './useSettingsStore.js';

describe('useSettingsStore', () => {
  beforeEach(() => {
    // Clear the store state before each test
    useSettingsStore.setState({
      messageDensity: 'comfortable',
      fontSize: 'medium',
      animationsEnabled: true,
      autoExpandReasoning: false,
      missionControlOpen: false,
      missionControlPinned: false,
    });
    
    // Clear localStorage mocks
    localStorage.getItem.mockClear();
    localStorage.setItem.mockClear();
  });

  describe('initialization', () => {
    it('should initialize with default settings', () => {
      const state = useSettingsStore.getState();
      
      expect(state.messageDensity).toBe('comfortable');
      expect(state.fontSize).toBe('medium');
      expect(state.animationsEnabled).toBe(true);
      expect(state.autoExpandReasoning).toBe(false);
      expect(state.missionControlOpen).toBe(false);
      expect(state.missionControlPinned).toBe(false);
    });
  });

  describe('updateSetting', () => {
    it('should update message density setting', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('messageDensity', 'compact');
      
      expect(useSettingsStore.getState().messageDensity).toBe('compact');
    });

    it('should update font size setting', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('fontSize', 'large');
      
      expect(useSettingsStore.getState().fontSize).toBe('large');
    });

    it('should update animations enabled setting', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('animationsEnabled', false);
      
      expect(useSettingsStore.getState().animationsEnabled).toBe(false);
    });

    it('should update auto expand reasoning setting', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('autoExpandReasoning', true);
      
      expect(useSettingsStore.getState().autoExpandReasoning).toBe(true);
    });

    it('should update mission control open setting', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('missionControlOpen', true);
      
      expect(useSettingsStore.getState().missionControlOpen).toBe(true);
    });

    it('should update mission control pinned setting', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('missionControlPinned', true);
      
      expect(useSettingsStore.getState().missionControlPinned).toBe(true);
    });

    it('should persist settings to localStorage after update', () => {
      const { updateSetting } = useSettingsStore.getState();
      
      updateSetting('fontSize', 'small');
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });
  });

  describe('resetToDefaults', () => {
    it('should reset all settings to defaults', () => {
      const { updateSetting, resetToDefaults } = useSettingsStore.getState();
      
      // Change some settings
      updateSetting('messageDensity', 'compact');
      updateSetting('fontSize', 'large');
      updateSetting('animationsEnabled', false);
      
      // Reset to defaults
      resetToDefaults();
      
      const state = useSettingsStore.getState();
      expect(state.messageDensity).toBe('comfortable');
      expect(state.fontSize).toBe('medium');
      expect(state.animationsEnabled).toBe(true);
      expect(state.autoExpandReasoning).toBe(false);
      expect(state.missionControlOpen).toBe(false);
      expect(state.missionControlPinned).toBe(false);
    });

    it('should persist defaults to localStorage after reset', () => {
      const { resetToDefaults } = useSettingsStore.getState();
      
      resetToDefaults();
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });
  });

  describe('localStorage persistence', () => {
    it('should use user email in storage key', () => {
      localStorage.getItem.mockImplementation((key) => {
        if (key === 'user_email') return 'user@example.com';
        return null;
      });
      
      const { updateSetting } = useSettingsStore.getState();
      updateSetting('fontSize', 'large');
      
      // Check that setItem was called with a key containing the email
      const calls = localStorage.setItem.mock.calls;
      const storageKey = calls[calls.length - 1]?.[0];
      expect(storageKey).toContain('user@example.com');
    });

    it('should use "anonymous" if no user email is set', () => {
      localStorage.getItem.mockReturnValue(null);
      
      const { updateSetting } = useSettingsStore.getState();
      updateSetting('fontSize', 'large');
      
      // Check that setItem was called with a key containing "anonymous"
      const calls = localStorage.setItem.mock.calls;
      const storageKey = calls[calls.length - 1]?.[0];
      expect(storageKey).toContain('anonymous');
    });
  });
});
