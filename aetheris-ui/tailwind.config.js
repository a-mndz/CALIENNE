/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    // Explicitly configure responsive breakpoints per design system
    screens: {
      sm: '640px',
      md: '768px',  // Tablet: 768px-1023px
      lg: '1024px', // Desktop: 1024px-1279px
      xl: '1280px', // Large Desktop: 1280px+
      '2xl': '1536px',
    },
    extend: {
      colors: {
        surface: {
          900: '#05060a',
          800: '#0b0d14',
          700: '#11141d',
          600: '#171b27',
          500: '#1e2333',
        },
        accent: {
          cyan: '#22d3ee',
          violet: '#8b5cf6',
          amber: '#f59e0b',
          rose: '#fb7185',
          emerald: '#34d399',
        },
        agent: {
          logician: '#22d3ee',
          creative: '#8b5cf6',
          judge: '#f59e0b',
          breaker: '#34d399',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        shimmer: 'shimmer 2.2s linear infinite',
        float: 'float 6s ease-in-out infinite',
        'step-reveal': 'step-reveal 0.3s ease-out forwards',
        'thinking-pulse': 'thinking-pulse 1.5s ease-in-out infinite',
        'fade-in-up': 'fade-in-up 0.35s ease-out forwards',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        'step-reveal': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'thinking-pulse': {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '1' },
        },
        'fade-in-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      boxShadow: {
        glow: '0 0 24px rgba(139,92,246,0.25)',
        'glow-cyan': '0 0 24px rgba(34,211,238,0.25)',
        'glow-amber': '0 0 24px rgba(245,158,11,0.25)',
      },
    },
  },
  plugins: [],
};
