# Framer Motion Animation System

## Overview

This document describes the animation system implemented for the Calienne UI using Framer Motion. All animations are designed to complete within 300ms and respect the user's `prefers-reduced-motion` system preference.

## Requirements Satisfied

- **8.1**: Expand/collapse animations for ReasoningPanel (300ms duration)
- **8.2**: Pulse effect for active pipeline stages
- **8.3**: Smooth progress bar transitions
- **8.4**: Fade-in effect for new timeline entries
- **8.5**: All animations complete within 300ms
- **8.6**: Animations avoid excessive motion
- **8.7**: Respect prefers-reduced-motion system preference

## Files Created

### 1. `src/utils/animations.js`
Central animation utilities file containing:

- **`prefersReducedMotion()`**: Checks if user prefers reduced motion
- **`getTransitionDuration()`**: Helper to get duration based on user preference
- **`panelVariants`**: Expand/collapse animations (300ms)
- **`pulseVariants`**: Pulse effect for active stages
- **`progressBarVariants`**: Smooth progress transitions
- **`timelineEntryVariants`**: Fade-in with stagger for timeline entries
- **`messageVariants`**: Fade-in for chat messages
- **`cardExpandVariants`**: Card expand/collapse (250ms)
- **`slideInRightVariants`**: Slide-in from right (for drawers)
- **`slideInLeftVariants`**: Slide-in from left (for sidebar)
- **`modalOverlayVariants`**: Modal fade overlay
- **`modalContentVariants`**: Modal content scale-fade
- **`staggerContainerVariants`**: Stagger children animations
- **`floatVariants`**: Float animation for logos
- **`shimmerVariants`**: Shimmer/loading animation

### 2. `src/utils/animations.test.js`
Comprehensive test suite (52 tests) covering:
- All animation variants
- `prefersReducedMotion` detection
- Duration compliance (≤300ms)
- Variant structure and properties

### 3. `src/hooks/useAnimations.js`
Custom hook that combines user settings with system preference for determining if animations should run.

## Components Updated

### 1. **ReasoningPanel**
- Uses `panelVariants` for expand/collapse animation
- Respects `animationsEnabled` setting from store
- Smooth 300ms height and opacity transition

### 2. **PipelineStatus**
- Uses `pulseVariants` for active stage pulse effect
- Progress bar uses smooth transitions
- Respects animation settings

### 3. **AgentThinkingCard**
- Uses `cardExpandVariants` for expand/collapse
- Timeline steps use `timelineEntryVariants` with stagger
- Respects animation settings

### 4. **ChatWindow**
- Wraps messages in `messageVariants` for fade-in effect
- Respects animation settings

### 5. **EmptyState**
- Updated to respect animation settings
- Conditional animation based on `animationsEnabled`

## Animation Behavior

### When Animations Are Enabled
- Full 300ms transitions
- Smooth easing (easeInOut, easeOut)
- Pulse effects loop infinitely
- Stagger delays for sequential reveals

### When Animations Are Disabled
- Animations disabled via `variants={animationsEnabled ? ... : undefined}`
- User can disable via settings store: `animationsEnabled: false`
- System preference checked: `prefers-reduced-motion: reduce`
- CSS media query also handles Tailwind animations

## CSS Support

The `index.css` file includes a media query that respects `prefers-reduced-motion`:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}
```

This ensures Tailwind CSS animations also respect the system preference.

## Usage Example

```jsx
import { motion } from 'framer-motion';
import { panelVariants } from '../utils/animations';
import { useSettingsStore } from '../store/useSettingsStore';

function MyComponent() {
  const [isOpen, setIsOpen] = useState(false);
  const animationsEnabled = useSettingsStore((state) => state.animationsEnabled);

  return (
    <motion.div
      initial="collapsed"
      animate={isOpen ? "expanded" : "collapsed"}
      variants={animationsEnabled ? panelVariants : undefined}
    >
      {/* Content */}
    </motion.div>
  );
}
```

## Performance

All animations are optimized for performance:
- GPU-accelerated properties (transform, opacity)
- Durations kept at or below 300ms
- No layout thrashing
- Efficient re-renders using motion variants

## Testing

Run animation tests:
```bash
npm test -- animations.test.js
```

All 52 tests verify:
- Variant structure
- Animation durations
- System preference detection
- User setting integration

## Future Enhancements

Potential additions for other components:
- Mission Control Panel slide-in animations
- Telemetry Drawer transitions
- Notification stack animations
- Settings panel modal animations

All future animations should follow these patterns and respect the same user preferences.
