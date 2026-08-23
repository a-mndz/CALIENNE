/**
 * Animation utilities for Framer Motion
 * Provides reusable animation variants and utilities that respect prefers-reduced-motion
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
 */

/**
 * Check if user prefers reduced motion
 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined') return false;
  if (!window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Get transition duration based on user preference
 * @param {number} normalDuration - Duration in seconds when animations are enabled
 * @param {number} reducedDuration - Duration in seconds when reduced motion is preferred (default: 0.01)
 */
export function getTransitionDuration(normalDuration = 0.3, reducedDuration = 0.01) {
  return prefersReducedMotion() ? reducedDuration : normalDuration;
}

/**
 * Panel expand/collapse animation variants
 * Requirements: 8.1 (expand/collapse animations for ReasoningPanel, 300ms duration)
 */
export const panelVariants = {
  collapsed: {
    height: 0,
    opacity: 0,
    transition: {
      height: { duration: 0.3 },
      opacity: { duration: 0.2 },
      ease: 'easeInOut',
    },
  },
  expanded: {
    height: 'auto',
    opacity: 1,
    transition: {
      height: { duration: 0.3 },
      opacity: { duration: 0.25, delay: 0.05 },
      ease: 'easeInOut',
    },
  },
};

/**
 * Pulse effect for active pipeline stages
 * Requirements: 8.2 (pulse effect for active pipeline stages)
 */
export const pulseVariants = {
  inactive: {
    scale: 1,
  },
  active: {
    scale: [1, 1.04, 1],
    transition: {
      duration: 1.1,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
};

/**
 * Smooth progress bar transitions
 * Requirements: 8.3 (smooth progress bar transitions)
 */
export const progressBarVariants = {
  initial: { width: '0%' },
  animate: (progress) => ({
    width: `${progress}%`,
    transition: {
      duration: 0.3,
      ease: 'easeOut',
    },
  }),
};

/**
 * Fade-in effect for new timeline entries
 * Requirements: 8.4 (fade-in effect for new timeline entries)
 */
export const timelineEntryVariants = {
  hidden: {
    opacity: 0,
    y: 12,
  },
  visible: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.3,
      delay: i * 0.05, // Stagger entries
      ease: 'easeOut',
    },
  }),
};

/**
 * Fade-in up animation for new messages
 */
export const messageVariants = {
  hidden: {
    opacity: 0,
    y: 16,
  },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.35,
      ease: 'easeOut',
    },
  },
};

/**
 * Card expand/collapse variants with smooth height animation
 */
export const cardExpandVariants = {
  collapsed: {
    height: 0,
    opacity: 0,
    transition: {
      height: { duration: 0.25 },
      opacity: { duration: 0.15 },
      ease: 'easeInOut',
    },
  },
  expanded: {
    height: 'auto',
    opacity: 1,
    transition: {
      height: { duration: 0.25 },
      opacity: { duration: 0.2, delay: 0.05 },
      ease: 'easeInOut',
    },
  },
};

/**
 * Slide in from right (for drawers/panels)
 */
export const slideInRightVariants = {
  hidden: {
    x: '100%',
    opacity: 0,
  },
  visible: {
    x: 0,
    opacity: 1,
    transition: {
      duration: 0.3,
      ease: 'easeOut',
    },
  },
  exit: {
    x: '100%',
    opacity: 0,
    transition: {
      duration: 0.25,
      ease: 'easeIn',
    },
  },
};

/**
 * Slide in from left (for sidebar)
 */
export const slideInLeftVariants = {
  hidden: {
    x: '-100%',
    opacity: 0,
  },
  visible: {
    x: 0,
    opacity: 1,
    transition: {
      duration: 0.3,
      ease: 'easeOut',
    },
  },
  exit: {
    x: '-100%',
    opacity: 0,
    transition: {
      duration: 0.25,
      ease: 'easeIn',
    },
  },
};

/**
 * Modal/overlay fade variants
 */
export const modalOverlayVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      duration: 0.2,
    },
  },
  exit: {
    opacity: 0,
    transition: {
      duration: 0.15,
    },
  },
};

/**
 * Modal content scale-fade variants
 */
export const modalContentVariants = {
  hidden: {
    opacity: 0,
    scale: 0.95,
  },
  visible: {
    opacity: 1,
    scale: 1,
    transition: {
      duration: 0.25,
      ease: 'easeOut',
    },
  },
  exit: {
    opacity: 0,
    scale: 0.95,
    transition: {
      duration: 0.2,
      ease: 'easeIn',
    },
  },
};

/**
 * Stagger children animation for lists
 */
export const staggerContainerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
    },
  },
};

/**
 * Float animation for logos/icons
 */
export const floatVariants = {
  initial: { y: 0 },
  animate: {
    y: [-6, 6, -6],
    transition: {
      duration: 6,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
};

/**
 * Shimmer/loading animation
 */
export const shimmerVariants = {
  initial: { backgroundPosition: '-200% 0' },
  animate: {
    backgroundPosition: '200% 0',
    transition: {
      duration: 2.2,
      repeat: Infinity,
      ease: 'linear',
    },
  },
};
