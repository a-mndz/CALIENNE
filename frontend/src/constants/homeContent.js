import { truncate } from "../utils/format.js";

export const HOME_BENTO_CARDS = [
  {
    id: "matrix",
    title: "Choose who gets a voice before the decision gets socialized.",
    body: "Turn viewpoints on and off, then feed the same question through a tighter panel instead of arguing from memory.",
    span: "span-7",
  },
  {
    id: "media",
    title: "See how a conclusion holds up once pressure, evidence, and synthesis stop agreeing by accident.",
    body: "Calienne keeps the debate visible long enough to expose what would normally be softened away in a status call.",
    span: "span-5",
    image: "signal-loom",
  },
  {
    id: "prompts",
    title: "Launch a hard prompt with the room already in motion.",
    body: "Start from a loaded prompt instead of a blank canvas when you want to compare reasoning styles, not typing speed.",
    span: "span-4",
  },
  {
    id: "modes",
    title: "Balance speed, depth, and synthesis without losing the shape of the argument.",
    body: "Fast keeps signal moving, Deep stretches the proof, and Balanced stays closer to an operating cadence your team can reuse.",
    span: "span-8",
  },
];

export const HOME_ACCORDIONS = [
  {
    id: "assumption",
    title: "Assumption pressure",
    body: "Breaker forces the hidden premise into daylight before anyone can confuse momentum with evidence.",
    image: "fracture-grid",
  },
  {
    id: "structure",
    title: "Structure under load",
    body: "Logician turns a vague debate into explicit tradeoffs, reversible choices, and cost curves the team can inspect.",
    image: "vector-flow",
  },
  {
    id: "divergence",
    title: "Divergence on purpose",
    body: "Creative opens alternate paths so the final answer is chosen, not inherited from the first confident voice in the room.",
    image: "kinetic-room",
  },
];

export const HOME_SIGNAL_CARDS = [
  {
    title: "Pressure",
    body: "Challenge the premise and reveal where the decision is resting on language that nobody has actually verified.",
    image: "pressure-wave",
  },
  {
    title: "Evidence",
    body: "Map the argument into variables, dependencies, and cost so the conclusion is inspectable instead of charismatic.",
    image: "evidence-grid",
  },
  {
    title: "Synthesis",
    body: "Judge resolves the spread into a usable recommendation that still preserves where confidence drops off.",
    image: "synthesis-core",
  },
];

export const HOME_TESTIMONIALS = [
  {
    quote: "We stopped mistaking fast consensus for real conviction. The synthesis was the first time our product review felt audit-ready.",
    author: "Mara Voss",
    role: "Product Director, Northline",
    image: "portrait-mara",
  },
  {
    quote: "The pinned narrative rail changed how we review infrastructure decisions. It forces the team to see each tradeoff as it forms.",
    author: "Ilan Mercer",
    role: "Staff Engineer, Relayworks",
    image: "portrait-ilan",
  },
  {
    quote: "Calienne made our research readouts less theatrical and more useful. Every disagreement became explicit enough to work with.",
    author: "Sana Cho",
    role: "Research Lead, Halide Studio",
    image: "portrait-sana",
  },
];

export const RESPONSES = {
  breaker: (q) => `What assumption is "${truncate(q)}" resting on that hasn't actually been tested?`,
  logician: () => `Structuring this: the decision reduces to two variables \u2014 reversibility, and cost of delay.`,
  creative: () => `Worth asking: what if the real constraint isn't the one on the table?`,
  judge: () => `Synthesis: the balanced path is the one that keeps the largest number of doors open. Confidence ${78 + Math.floor(Math.random() * 18)}%.`,
};
