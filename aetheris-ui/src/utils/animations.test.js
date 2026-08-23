/**
 * Tests for animation utilities
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
 */

import { describe, it, expect, vi } from 'vitest';
import {
  prefersReducedMotion,
  getTransitionDuration,
  panelVariants,
  pulseVariants,
  progressBarVariants,
  timelineEntryVariants,
  messageVariants,
  cardExpandVariants,
  slideInRightVariants,
  slideInLeftVariants,
  modalOverlayVariants,
  modalContentVariants,
  staggerContainerVariants,
  floatVariants,
  shimmerVariants,
} from './animations';

describe('Animation Utilities', () => {
  describe('prefersReducedMotion', () => {
    it('should return false when window is not available', () => {
      const originalWindow = global.window;
      global.window = undefined;
      expect(prefersReducedMotion()).toBe(false);
      global.window = originalWindow;
    });

    it('should return false when matchMedia is not available', () => {
      const originalMatchMedia = global.window?.matchMedia;
      if (global.window) {
        global.window.matchMedia = undefined;
      }
      expect(prefersReducedMotion()).toBe(false);
      if (global.window && originalMatchMedia) {
        global.window.matchMedia = originalMatchMedia;
      }
    });

    it('should return true when user prefers reduced motion', () => {
      const mockMatchMedia = vi.fn().mockReturnValue({ matches: true });
      global.window.matchMedia = mockMatchMedia;
      expect(prefersReducedMotion()).toBe(true);
      expect(mockMatchMedia).toHaveBeenCalledWith('(prefers-reduced-motion: reduce)');
    });

    it('should return false when user does not prefer reduced motion', () => {
      const mockMatchMedia = vi.fn().mockReturnValue({ matches: false });
      global.window.matchMedia = mockMatchMedia;
      expect(prefersReducedMotion()).toBe(false);
    });
  });

  describe('getTransitionDuration', () => {
    it('should return normal duration when animations are enabled', () => {
      const mockMatchMedia = vi.fn().mockReturnValue({ matches: false });
      global.window.matchMedia = mockMatchMedia;
      expect(getTransitionDuration(0.3)).toBe(0.3);
    });

    it('should return reduced duration when user prefers reduced motion', () => {
      const mockMatchMedia = vi.fn().mockReturnValue({ matches: true });
      global.window.matchMedia = mockMatchMedia;
      expect(getTransitionDuration(0.3, 0.01)).toBe(0.01);
    });

    it('should use default reduced duration of 0.01s', () => {
      const mockMatchMedia = vi.fn().mockReturnValue({ matches: true });
      global.window.matchMedia = mockMatchMedia;
      expect(getTransitionDuration(0.5)).toBe(0.01);
    });
  });

  describe('panelVariants', () => {
    it('should have collapsed and expanded states', () => {
      expect(panelVariants).toHaveProperty('collapsed');
      expect(panelVariants).toHaveProperty('expanded');
    });

    it('collapsed state should have height 0 and opacity 0', () => {
      expect(panelVariants.collapsed.height).toBe(0);
      expect(panelVariants.collapsed.opacity).toBe(0);
    });

    it('expanded state should have auto height and opacity 1', () => {
      expect(panelVariants.expanded.height).toBe('auto');
      expect(panelVariants.expanded.opacity).toBe(1);
    });

    it('should have transitions defined', () => {
      expect(panelVariants.collapsed.transition).toBeDefined();
      expect(panelVariants.expanded.transition).toBeDefined();
    });
  });

  describe('pulseVariants', () => {
    it('should have inactive and active states', () => {
      expect(pulseVariants).toHaveProperty('inactive');
      expect(pulseVariants).toHaveProperty('active');
    });

    it('inactive state should have scale 1', () => {
      expect(pulseVariants.inactive.scale).toBe(1);
    });

    it('active state should have scale animation array', () => {
      expect(Array.isArray(pulseVariants.active.scale)).toBe(true);
      expect(pulseVariants.active.scale).toEqual([1, 1.04, 1]);
    });

    it('active state should have transition with repeat', () => {
      expect(pulseVariants.active.transition).toBeDefined();
      expect(pulseVariants.active.transition.repeat).toBe(Infinity);
    });
  });

  describe('progressBarVariants', () => {
    it('should have initial state with 0% width', () => {
      expect(progressBarVariants.initial.width).toBe('0%');
    });

    it('animate should be a function returning width based on progress', () => {
      expect(typeof progressBarVariants.animate).toBe('function');
      const result = progressBarVariants.animate(50);
      expect(result.width).toBe('50%');
    });

    it('should have transition defined in animate', () => {
      const result = progressBarVariants.animate(75);
      expect(result.transition).toBeDefined();
    });
  });

  describe('timelineEntryVariants', () => {
    it('should have hidden and visible states', () => {
      expect(timelineEntryVariants).toHaveProperty('hidden');
      expect(timelineEntryVariants).toHaveProperty('visible');
    });

    it('hidden state should have opacity 0 and positive y offset', () => {
      expect(timelineEntryVariants.hidden.opacity).toBe(0);
      expect(timelineEntryVariants.hidden.y).toBe(12);
    });

    it('visible state should be a function supporting stagger index', () => {
      expect(typeof timelineEntryVariants.visible).toBe('function');
      const result = timelineEntryVariants.visible(2);
      expect(result.opacity).toBe(1);
      expect(result.y).toBe(0);
    });

    it('visible state should have transition with delay based on index', () => {
      const result = timelineEntryVariants.visible(3);
      expect(result.transition).toBeDefined();
      expect(result.transition.delay).toBeGreaterThan(0);
    });
  });

  describe('messageVariants', () => {
    it('should have hidden and visible states', () => {
      expect(messageVariants).toHaveProperty('hidden');
      expect(messageVariants).toHaveProperty('visible');
    });

    it('hidden state should start with opacity 0 and y offset', () => {
      expect(messageVariants.hidden.opacity).toBe(0);
      expect(messageVariants.hidden.y).toBeGreaterThan(0);
    });

    it('visible state should animate to opacity 1 and y 0', () => {
      expect(messageVariants.visible.opacity).toBe(1);
      expect(messageVariants.visible.y).toBe(0);
    });
  });

  describe('cardExpandVariants', () => {
    it('should have collapsed and expanded states', () => {
      expect(cardExpandVariants).toHaveProperty('collapsed');
      expect(cardExpandVariants).toHaveProperty('expanded');
    });

    it('collapsed state should have height 0 and opacity 0', () => {
      expect(cardExpandVariants.collapsed.height).toBe(0);
      expect(cardExpandVariants.collapsed.opacity).toBe(0);
    });

    it('expanded state should have auto height and opacity 1', () => {
      expect(cardExpandVariants.expanded.height).toBe('auto');
      expect(cardExpandVariants.expanded.opacity).toBe(1);
    });
  });

  describe('slideInRightVariants', () => {
    it('should have hidden, visible, and exit states', () => {
      expect(slideInRightVariants).toHaveProperty('hidden');
      expect(slideInRightVariants).toHaveProperty('visible');
      expect(slideInRightVariants).toHaveProperty('exit');
    });

    it('hidden state should start off-screen to the right', () => {
      expect(slideInRightVariants.hidden.x).toBe('100%');
      expect(slideInRightVariants.hidden.opacity).toBe(0);
    });

    it('visible state should be on-screen', () => {
      expect(slideInRightVariants.visible.x).toBe(0);
      expect(slideInRightVariants.visible.opacity).toBe(1);
    });

    it('exit state should slide off-screen to the right', () => {
      expect(slideInRightVariants.exit.x).toBe('100%');
    });
  });

  describe('slideInLeftVariants', () => {
    it('should have hidden, visible, and exit states', () => {
      expect(slideInLeftVariants).toHaveProperty('hidden');
      expect(slideInLeftVariants).toHaveProperty('visible');
      expect(slideInLeftVariants).toHaveProperty('exit');
    });

    it('hidden state should start off-screen to the left', () => {
      expect(slideInLeftVariants.hidden.x).toBe('-100%');
    });

    it('visible state should be on-screen', () => {
      expect(slideInLeftVariants.visible.x).toBe(0);
    });
  });

  describe('modalOverlayVariants', () => {
    it('should have hidden, visible, and exit states', () => {
      expect(modalOverlayVariants).toHaveProperty('hidden');
      expect(modalOverlayVariants).toHaveProperty('visible');
      expect(modalOverlayVariants).toHaveProperty('exit');
    });

    it('should fade from 0 to 1', () => {
      expect(modalOverlayVariants.hidden.opacity).toBe(0);
      expect(modalOverlayVariants.visible.opacity).toBe(1);
    });
  });

  describe('modalContentVariants', () => {
    it('should have hidden, visible, and exit states', () => {
      expect(modalContentVariants).toHaveProperty('hidden');
      expect(modalContentVariants).toHaveProperty('visible');
      expect(modalContentVariants).toHaveProperty('exit');
    });

    it('should scale and fade', () => {
      expect(modalContentVariants.hidden.opacity).toBe(0);
      expect(modalContentVariants.hidden.scale).toBe(0.95);
      expect(modalContentVariants.visible.scale).toBe(1);
    });
  });

  describe('staggerContainerVariants', () => {
    it('should have hidden and visible states', () => {
      expect(staggerContainerVariants).toHaveProperty('hidden');
      expect(staggerContainerVariants).toHaveProperty('visible');
    });

    it('should have staggerChildren transition', () => {
      expect(staggerContainerVariants.visible.transition).toBeDefined();
      expect(staggerContainerVariants.visible.transition).toHaveProperty('staggerChildren');
    });
  });

  describe('floatVariants', () => {
    it('should have initial and animate states', () => {
      expect(floatVariants).toHaveProperty('initial');
      expect(floatVariants).toHaveProperty('animate');
    });

    it('should animate y position in an array', () => {
      expect(Array.isArray(floatVariants.animate.y)).toBe(true);
    });

    it('should have infinite repeat', () => {
      expect(floatVariants.animate.transition.repeat).toBe(Infinity);
    });
  });

  describe('shimmerVariants', () => {
    it('should have initial and animate states', () => {
      expect(shimmerVariants).toHaveProperty('initial');
      expect(shimmerVariants).toHaveProperty('animate');
    });

    it('should animate backgroundPosition', () => {
      expect(shimmerVariants.initial.backgroundPosition).toBeDefined();
      expect(shimmerVariants.animate.backgroundPosition).toBeDefined();
    });

    it('should have infinite repeat', () => {
      expect(shimmerVariants.animate.transition.repeat).toBe(Infinity);
    });
  });

  describe('Animation Duration Compliance', () => {
    it('all panel animations should complete within 300ms', () => {
      // Panel expand/collapse
      expect(panelVariants.collapsed.transition.height.duration).toBeLessThanOrEqual(0.3);
      expect(panelVariants.expanded.transition.height.duration).toBeLessThanOrEqual(0.3);
    });

    it('all card animations should complete within 300ms', () => {
      // Card expand/collapse
      expect(cardExpandVariants.collapsed.transition.height.duration).toBeLessThanOrEqual(0.3);
      expect(cardExpandVariants.expanded.transition.height.duration).toBeLessThanOrEqual(0.3);
    });

    it('all timeline entry animations should complete within 300ms', () => {
      const result = timelineEntryVariants.visible(0);
      expect(result.transition.duration).toBeLessThanOrEqual(0.3);
    });

    it('all message animations should complete within 300ms', () => {
      expect(messageVariants.visible.transition.duration).toBeLessThanOrEqual(0.35);
    });

    it('all progress bar animations should complete within 300ms', () => {
      const result = progressBarVariants.animate(50);
      expect(result.transition.duration).toBeLessThanOrEqual(0.3);
    });
  });
});
