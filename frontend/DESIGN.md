---
version: 2.0
name: Calienne — Adaptive Multi-Model Reasoning Orchestrator
description: Adaptive Multi-Model Reasoning Orchestrator and synthesis decision room.
tagline: "Reasoning, arbitrated."
visual_mode: "Dark Developer / Builder"
metaphor: "Triadic Synthesis Node"
colors:
  page-black: "#0B0D11"
  dashboard-black: "#0B0D11"
  panel-ink: "#12151B"
  surface-1: "#141820"
  surface-2: "#1E222A"
  surface-3: "#272C36"
  shell-line: "#2A303C"
  shell-line-strong: "#3A4252"
  text-strong: "#F4F6F9"
  text-ui: "#EAEFF6"
  text-soft: "#9FA6B2"
  text-faint: "#6A7382"
  signal-cyan: "#00F0FF"
  signal-cyan-bright: "#66F8FF"
  signal-red: "#E63E3E"
  telemetry-blue: "#78A7FF"
  consensus-green: "#3DDC6A"
  caution-amber: "#E0A030"
typography:
  display:
    fontFamily: "Geist, Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "clamp(3.4rem, 7vw, 5.8rem)"
    fontWeight: 700
    lineHeight: 0.94
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Geist, Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "clamp(1.8rem, 3vw, 3rem)"
    fontWeight: 700
    lineHeight: 1.02
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Geist, Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Plus Jakarta Sans, Geist, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "JetBrains Mono, Geist Mono, monospace"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.08em"
  mono:
    fontFamily: "JetBrains Mono, Geist Mono, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "0.04em"
rounded:
  none: "0px"
  pill: "999px"
  surface: "32px"
  surface-inner: "26px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  section: "48px"
components:
  button-primary:
    backgroundColor: "{colors.signal-teal}"
    textColor: "{colors.page-black}"
    rounded: "{rounded.pill}"
    padding: "14px 22px"
  button-primary-hover:
    backgroundColor: "{colors.signal-teal-bright}"
  button-ghost:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-strong}"
    rounded: "{rounded.pill}"
    padding: "14px 22px"
  chip-active:
    backgroundColor: "{colors.text-ui}"
    textColor: "{colors.dashboard-black}"
    rounded: "{rounded.none}"
    padding: "6px 10px"
  chip-idle:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-soft}"
    rounded: "{rounded.none}"
    padding: "6px 10px"
---

# Design System: Calienne

## 1. Overview

**Creative North Star: "The Pressure Chamber"**

Calienne should feel like a room built for consequential thinking, not a friendly productivity sandbox. The visual system is dark, technical, and controlled: near-black fields, disciplined chrome, sparse use of high-signal color, and typography that feels inspected rather than decorated. The landing page sells trust through atmosphere and restraint; the dashboard turns that same identity into a working instrument where dissent, confidence, and synthesis stay legible under load.

This system is intentionally split across two accents with one shared temperament. Teal is the invitation surface: the calm, credible promise that there is rigor underneath. Red is the decision surface: pressure, challenge, and active interrogation. Blue, green, and amber only appear as secondary telemetry signals inside the workspace. What ties both surfaces together is the same hard-edged editorial posture: precise copy, dark tactical layering, mono metadata, and visible structure rather than decorative flourish.

This system explicitly rejects Generic AI SaaS, Notion/Airtable softness, and Jira/Confluence bureaucracy. It must never drift into cream-background optimism, purple-gradient futurism, pastel collaboration energy, or dense enterprise gray process theater.

**Key Characteristics:**
- Cinematic dark mode with disciplined contrast
- One identity expressed as two surfaces: invitation and pressure
- Editorial typography over generic product-marketing scaffolds
- Tactical UI chrome with visible system state
- High signal density without visual clutter

## 2. Colors

The palette is built from near-black infrastructure and tightly rationed signal color. Color is never ambient decoration here; each accent has a job.

### Primary
- **Decision Teal** (`#9fe2c3`): The landing accent. Use for the most important calls to action, trust-bearing highlights, and calm signal moments where the brand is asking for attention without raising its voice.
- **Interrogation Red** (`#e63e3e`): The dashboard accent. Use for active states, pressure, challenge, selection, and critical system emphasis where the workspace needs to feel live and exacting.

### Secondary
- **Telemetry Blue** (`#78a7ff`): Analytical support color for model, data, or system-state cues.
- **Consensus Green** (`#3ddc6a`): Positive verification, healthy status, and successful outcomes.

### Tertiary
- **Caution Amber** (`#e3bf4b`): Uncertainty, pending judgment, and warning without escalating into alarm.

### Neutral
- **Absolute Black** (`#050505`): Primary page field for the brand surface.
- **Dashboard Black** (`#0a0a0a`): Primary product field for the workspace.
- **Panel Ink** (`#0a100d`): Dense inner landing panels and hero surfaces.
- **Surface Stack** (`#121212`, `#171717`, `#1c1c1c`): Layered dashboard planes for shell, drawers, and active state separation.
- **Shell Line** (`#2a2a2a`, `#3d3d3d`): Structural borders and dividers. These create hierarchy where lighter products would use shadow.
- **Cold Text** (`#f6f6f1`, `#eaeaea`, `#8f8f8f`, `#7a7a7a`): A restrained text ramp from primary copy down to metadata. It stays bright enough to read clearly on dark fields and never slips into fashionable low-contrast gray.

### Named Rules
**The Rare Accent Rule.** Saturated color is rationed. On any given screen, the dominant experience remains near-black and neutral; accent appears only where state, priority, or action must be unmistakable.

**The Two-Surface Rule.** Teal owns the invitation layer. Red owns the active decision layer. Do not swap them casually or blend them into a multicolor brand soup.

## 3. Typography

**Display Font:** Geist with Plus Jakarta Sans fallback
**Body Font:** Plus Jakarta Sans with Geist fallback
**Label/Mono Font:** JetBrains Mono for telemetry, chips, labels, and machine-facing metadata

**Character:** The pairing should read as exact and contemporary rather than luxurious or playful. The sans stack carries clarity and authority; the mono stack brings technical credibility and makes state feel inspected instead of narrated.

### Hierarchy
- **Display** (700, `clamp(3.4rem, 7vw, 5.8rem)`, 0.94): Reserved for hero headlines and major landing statements. It should feel compressed and forceful, never sprawling.
- **Headline** (700, `clamp(1.8rem, 3vw, 3rem)`, 1.02): Section headers, workspace landmarks, and major content pivots.
- **Title** (600, `1rem`, 1.3): Card titles, thread titles, panel headings, and dense information blocks.
- **Body** (400, `1rem`, 1.7): Long-form supporting copy and explanation. Cap readable prose around 65-75ch.
- **Label** (600, `0.75rem`, `0.08em`, uppercase or systems-style caps): Small UI framing, navigation metadata, pills, and minor taxonomy.
- **Mono** (500, `0.6875rem`, `0.04em`): Telemetry values, timestamps, scores, agent metadata, and keyboard hints.

### Named Rules
**The No-Hero-Metric Voice Rule.** Type should explain pressure, evidence, and reasoning. Do not fall back to generic SaaS scaffolds built from giant numbers and hollow category labels.

**The Sharp Interior Rule.** Body copy can be calm, but labels and metadata should feel clipped, technical, and exact.

## 4. Elevation

Calienne uses a hybrid depth model. The landing surface uses soft atmospheric lift, with large blurred shadows and translucent shells to create cinematic depth around key framed blocks. The dashboard is much flatter: hierarchy comes primarily from tonal layering, border contrast, and occasional state-driven shadow rather than ambient floating cards. The product surface should feel machined and functional, not glossy.

### Shadow Vocabulary
- **Landing shell lift** (`0 26px 70px rgba(9, 35, 27, 0.34)`): Use on major framed landing surfaces where the interface needs to feel suspended inside the dark field.
- **Landing CTA lift** (`0 18px 50px rgba(17, 48, 37, 0.28)`): Use on priority call-to-action buttons and other high-intent invitation moments.
- **Dashboard state lift** (`0 2px 8px rgba(0,0,0,0.2)`): A minimal state shadow for hovered or active workspace controls only.

### Named Rules
**The Flat-Under-Pressure Rule.** In the dashboard, surfaces sit flat by default. Depth appears as a response to interaction or priority, not as a permanent decorative haze.

## 5. Components

Every component should feel utilitarian, exact, and slightly severe. Calienne does not use soft consumer-app components.

### Buttons
- **Shape:** Landing calls to action are full-pill (`999px`). Dashboard buttons are square-cornered (`0px`).
- **Primary:** On the landing surface, use teal-backed CTAs with dark text and an inset island or directional glyph. In the dashboard, primary actions invert into light-on-dark or red-on-dark depending on urgency.
- **Hover / Focus:** Hover moves are subtle lifts or border clarifications, not bouncy gestures. Focus states must remain explicit and high contrast.
- **Secondary / Ghost:** Ghost actions stay dark and bordered, with enough tonal contrast to remain visible on black backgrounds.

### Chips
- **Style:** Rectilinear chips with dense mono or compact sans labels, thin borders, and restrained padding.
- **State:** Active chips invert strongly into light text/background contrast. Idle chips remain dark and technical, not pastel.

### Cards / Containers
- **Corner Style:** Landing feature frames use large rounded shells (`32px` outer, `26px` inner). Dashboard containers use hard corners.
- **Background:** Landing containers use translucent shells over cinematic gradients. Dashboard containers use solid tonal layers from `#121212` through `#1c1c1c`.
- **Shadow Strategy:** Landing uses atmospheric shadow; dashboard uses borders first, shadow second.
- **Border:** Thin structural lines are essential. Borders do the work that brighter systems often ask from drop shadows.
- **Internal Padding:** Most dense product containers sit in the `16px` to `24px` range. Landing hero and section frames can expand beyond that for breathing room.

### Inputs / Fields
- **Style:** Dark fields with visible 1px borders, square corners in the workspace, and text that remains bright enough for long sessions.
- **Focus:** Focus should shift border contrast or outline color immediately; never rely on subtle box-shadow alone.
- **Error / Disabled:** Errors take red or red-tinted treatment. Disabled states mute contrast but must remain readable.

### Navigation
- **Style:** Landing navigation is translucent, pill-based, and centered within a floating shell. Dashboard navigation is embedded into the app chrome as dense, low-radius or zero-radius utility controls.
- **States:** Hover clarifies border and text; active states should read as selected instrumentation, not playful toggles.
- **Mobile treatment:** Mobile keeps the same severity. Overlays may simplify layout, but not the tone.

### Signature Component
- **Decision thread:** The conversation view is the product's core artifact. User messages, agent responses, badges, and confidence cues should feel like an inspectable record, not a chat toy. Preserve authorship, state, and dissent visibility at a glance.

## 6. Do's and Don'ts

### Do:
- **Do** keep dark fields dominant and use accent only where decision state, trust, or action needs emphasis.
- **Do** preserve the two-surface split: teal for the brand invitation layer, red for the active dashboard layer.
- **Do** use mono labels, timestamps, scores, and telemetry to make the product feel evidentiary rather than promotional.
- **Do** keep borders visible and intentional, especially in the dashboard where structure matters more than softness.
- **Do** maintain high-contrast text against every dark field and provide reduced-motion fallbacks for reveals, overlays, and panel transitions.

### Don't:
- **Don't** introduce Generic AI SaaS patterns: cream backgrounds, purple gradients, vague empowerment copy, or decorative dashboards that feel like toys.
- **Don't** soften the system into Notion/Airtable territory with friendly pastel warmth, collaborative softness, or "everyone can contribute" visual energy.
- **Don't** let the workspace drift into Jira/Confluence bureaucracy with enterprise gray density and process-for-process-sake chrome.
- **Don't** use colored side stripes thicker than 1px as the primary accent mechanism on cards or list items.
- **Don't** use gradient text, glassmorphism-by-default, or identical icon-card grids as filler structure.
- **Don't** over-round product surfaces. Pills are for landing actions; the workspace should stay hard-edged.

## 7. `gpt-taste` Enforcement Architecture (Frontend Governance)

To maintain Awwwards-level visual and interactive standards across `new ui/frontend`, all UI engineering tasks must enforce the directives from `skills/gpt-taste/SKILL.md`:

### 7.1 Python-Driven True Randomization (Anti-Repetition)
- When generating or redesigning layouts within `new ui/frontend`, developers and agents must run a simulated deterministic Python seed before writing UI code to select layout variants, typography stack, component architectures, and GSAP motion paradigms.
- Defaulting repeatedly to identical hero structures or generic left/right splits is strictly prohibited.

### 7.2 Editorial Typography Stack & 2-Line Hero Iron Rule
- **Allowed Typography:** `Geist`, `Outfit`, `Cabinet Grotesk`, or `Satoshi` (via Google Fonts or self-hosted assets). **`Inter` is strictly banned.**
- **Hero 2-Line Rule:** Primary hero headings (`H1`) must use wide containers (`max-w-5xl`, `max-w-6xl`) and clamp font sizing (`clamp(3rem, 5vw, 5.5rem)`) to ensure headings never exceed **2 to 3 lines horizontally**.
- **Contrast & Legibility:** Buttons and interactive elements must guarantee high contrast ratio (light text on dark backgrounds, dark text on light backgrounds).

### 7.3 Gapless Bento Grids & AIDA Pacing
- **Gapless Grid Enforcement:** Every Bento grid layout must use Tailwind's `grid-flow-dense` or standard CSS `grid-auto-flow: dense`. `col-span` and `row-span` values must interlock mathematically with zero empty void cells.
- **AIDA Section Pacing:** All pages must follow the AIDA progression (Navigation → Attention Hero → Interest Bento → Desire GSAP Scroll → Action CTA/Footer) with generous vertical spacing between major sections (`py-32 md:py-48` equivalent).

### 7.4 Advanced GSAP Motion & Hover Physics
- Static components are disallowed. Pages must leverage `@gsap/react` and `ScrollTrigger` for:
  - **Hover Physics:** Interactive cards use `group-hover:scale-105 transition-transform duration-700 ease-out`.
  - **Scroll Pinning:** Section headers pin (`ScrollTrigger pin: true`) while companion elements scroll alongside.
  - **Scrubbing Text Reveals:** Opacity scrubs smoothly (`0.1` → `1.0`) as the user scrolls down.
  - **Scale & Fade:** Images animate from `scale: 0.8` to `1.0` on entry and fade gracefully on exit.

### 7.5 Pre-Flight `<design_plan>` Requirement
Before modifying or creating React components in `new ui/frontend`, every task must emit a `<design_plan>` verification block confirming:
1. Python deterministic randomization selection.
2. Complete AIDA page flow and section padding.
3. Hero H1 container width (`max-w-5xl`+) and 2–3 line limit compliance.
4. Bento grid density proof (`grid-auto-flow: dense`).
5. Absence of cheap meta-labels (`"SECTION 01"`, `"QUESTION 05"`, etc.) and compliance with button contrast rules.

