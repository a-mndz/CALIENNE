export function randId() { return Math.random().toString(36).slice(2, 10); }

export function picsum(seed, w = 1600, h = 1000) {
  const hash = String(seed).split("").reduce((acc, c) => (acc * 31 + c.charCodeAt(0)) | 0, 0);
  const hue = Math.abs(hash) % 360;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs>
      <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#090B12"/>
        <stop offset="50%" stop-color="#131622"/>
        <stop offset="100%" stop-color="#050508"/>
      </linearGradient>
      <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="hsl(${hue}, 80%, 55%)" stop-opacity="0.6"/>
        <stop offset="100%" stop-color="#00F0FF" stop-opacity="0.2"/>
      </linearGradient>
      <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
        <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.04)" stroke-width="1"/>
      </pattern>
    </defs>
    <rect width="${w}" height="${h}" fill="url(#bg)"/>
    <rect width="${w}" height="${h}" fill="url(#grid)"/>
    <circle cx="${w * 0.5}" cy="${h * 0.5}" r="${Math.min(w, h) * 0.35}" fill="none" stroke="url(#accent)" stroke-width="1.5" stroke-dasharray="8 6"/>
    <circle cx="${w * 0.5}" cy="${h * 0.5}" r="${Math.min(w, h) * 0.2}" fill="none" stroke="rgba(0,240,255,0.3)" stroke-width="1"/>
    <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#969DB8" font-family="monospace" font-size="14" letter-spacing="4">CALIENNE // SCHEMATIC [${String(seed).toUpperCase()}]</text>
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
