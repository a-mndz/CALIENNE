/**
 * Custom hook to determine if animations should be enabled
 * Respects both user settings and system prefers-reduced-motion preference
 * Requirements: 8.7 (respect prefers-reduced-motion system preference)
 */

import { useSettingsStore } from '../store/useSettingsStore';
import { prefersReducedMotion } from '../utils/animations';

/**
 * Returns whether animations should be enabled
 * Takes into account both user settings and system preference
 * @returns {boolean} - true if animations should run, false otherwise
 */
export function useAnimations() {
  const animationsEnabled = useSettingsStore((state) => state.animationsEnabled);
  
  // Animations are enabled only if:
  // 1. User has enabled them in settings AND
  // 2. User's system doesn't prefer reduced motion
  return animationsEnabled && !prefersReducedMotion();
}
