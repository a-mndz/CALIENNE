import { Suspense, lazy, useEffect, useRef, useState } from 'react'

// Design Read: B2B landing surface for technical decision makers (product, research, infrastructure),
// with a clean structural aesthetic leaning toward high-precision custom cards, restrained motion, and zero marketing slop.
// Dials: DESIGN_VARIANCE=6 (controlled asymmetry), MOTION_INTENSITY=4 (subtle reveal transitions), VISUAL_DENSITY=5 (balanced information density).

const CalienneDashboard = lazy(() => import('./CalienneDashboard'))

const CHAT_HASH = '#workspace'

function getInitialSurface() {
  if (typeof window === 'undefined') return 'landing'
  if (window.location.hash === CHAT_HASH) return 'dashboard'
  return 'landing'
}

const navItems = [
  { href: '#architecture', label: 'Decision structure' },
  { href: '#signals', label: 'Dissent signals' },
  { href: '#flow', label: 'Export flow' },
  { href: '#proof', label: 'Decision trace' },
  { href: '#contact', label: 'Contact' },
]

const decisionTrace = [
  { label: 'Premise under test', value: 'Speed is reversible. Data shape is not.' },
  { label: 'Live objection', value: 'Breaker flagged launch pressure masking migration cost.' },
  { label: 'Final synthesis', value: 'Ship reversible surfaces. Freeze identity, billing, and model memory.' },
]

const architectureCards = [
  {
    name: 'Pressure framing',
    title: 'The room isolates assumptions before anyone mistakes velocity for proof.',
    body: 'Each prompt is reframed into pressure tests, source tension, and synthesis weight so the conclusion can be inspected later.',
    icon: 'grid',
    tone: 'large',
  },
  {
    name: 'Signal rail',
    title: 'A live side-channel keeps dissent visible instead of flattening it.',
    body: 'Operators can watch where alignment forms early, where confidence drops, and which objection actually changed the room.',
    icon: 'pulse',
    tone: 'tall',
  },
  {
    name: 'Decision memory',
    title: 'The final recommendation preserves edge cases, not just the winning sentence.',
    body: 'Calienne stores the argument spine, fallback paths, and unresolved risk so a team can restart from context instead of folklore.',
    icon: 'vault',
    tone: 'wide',
  },
]

const signalCards = [
  {
    name: 'Breaker',
    title: 'Challenges language that sounds settled but was never actually verified.',
    body: 'Useful when momentum is outrunning certainty and everyone is starting to inherit the same premise.',
    icon: 'split',
  },
  {
    name: 'Logician',
    title: 'Maps the debate into reversibility, cost, and second-order effects.',
    body: 'Turns intuition into something a product, research, and infra team can all inspect without translation loss.',
    icon: 'thread',
  },
  {
    name: 'Judge',
    title: 'Compresses the spread into one recommendation without deleting uncertainty.',
    body: 'Confidence is attached to the actual reasoning path, not a decorative percentage pasted on at the end.',
    icon: 'spark',
  },
]

const flowSteps = [
  {
    step: '01',
    title: 'Load a hard decision with context intact.',
    body: 'Bring in the prompt, prior constraints, and what cannot fail. The system opens with structure instead of theatrics.',
  },
  {
    step: '02',
    title: 'Shape the panel before the debate gains inertia.',
    body: 'Turn viewpoints on or off, bias toward speed or auditability, then let the room diverge on purpose.',
  },
  {
    step: '03',
    title: 'Export a recommendation that still shows its load-bearing doubts.',
    body: 'The answer ships with confidence, dissent, and the next branch you would take if the premise shifts tomorrow.',
  },
]

const testimonials = [
  {
    quote: 'The product review stopped sounding polished and started sounding honest. That changed what we shipped the same week.',
    author: 'Mara Voss',
    role: 'Product director, Northline',
  },
  {
    quote: 'We now keep the disagreement trace attached to every infrastructure decision. It saves us from relitigating the same tradeoff two sprints later.',
    author: 'Ilan Mercer',
    role: 'Staff engineer, Relayworks',
  },
]

function Icon({ name }) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: '1.35',
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  }

  const icons = {
    arrow: (
      <>
        <path d="M6 18 18 6" {...common} />
        <path d="M8 6h10v10" {...common} />
      </>
    ),
    grid: (
      <>
        <rect x="4.5" y="4.5" width="6.5" height="6.5" rx="1.8" {...common} />
        <rect x="13" y="4.5" width="6.5" height="6.5" rx="1.8" {...common} />
        <rect x="4.5" y="13" width="6.5" height="6.5" rx="1.8" {...common} />
        <rect x="13" y="13" width="6.5" height="6.5" rx="1.8" {...common} />
      </>
    ),
    pulse: (
      <>
        <path d="M3 12h4l2.3-4.5 4.2 9 2.2-4H21" {...common} />
      </>
    ),
    vault: (
      <>
        <path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5Z" {...common} />
        <path d="M12 9.2v5.6" {...common} />
        <path d="M9.4 12h5.2" {...common} />
      </>
    ),
    split: (
      <>
        <path d="M6 5.5h12" {...common} />
        <path d="M8 10.5h8" {...common} />
        <path d="M5 15.5h5" {...common} />
        <path d="M14 15.5h5" {...common} />
      </>
    ),
    thread: (
      <>
        <path d="M5 7.5h6c3.5 0 3.5 9 7 9h1" {...common} />
        <path d="M19 16.5 16.7 14" {...common} />
        <path d="M19 16.5 16.6 19" {...common} />
      </>
    ),
    spark: (
      <>
        <path d="m12 3 1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6Z" {...common} />
      </>
    ),
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="line-icon">
      {icons[name]}
    </svg>
  )
}

function Frame({ className = '', innerClassName = '', children }) {
  return (
    <div className={`surface-shell ${className}`.trim()}>
      <div className={`surface-core ${innerClassName}`.trim()}>{children}</div>
    </div>
  )
}

function CTA({ href, children, variant = 'primary', onClick }) {
  const className = variant === 'ghost' ? 'cta-button cta-ghost' : 'cta-button cta-primary'

  return (
    <a className={className} href={href} onClick={onClick}>
      <span>{children}</span>
      <span className="cta-island" aria-hidden="true">
        <Icon name="arrow" />
      </span>
    </a>
  )
}

export default function App() {
  const [surface, setSurface] = useState(getInitialSurface)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuToggleRef = useRef(null)
  const menuPanelRef = useRef(null)

  useEffect(() => {
    function handleHashChange() {
      if (window.location.hash === CHAT_HASH) {
        setSurface('dashboard')
      } else {
        setSurface('landing')
      }
    }

    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  useEffect(() => {
    if (surface !== 'landing') return undefined

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('in-view')
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.18, rootMargin: '0px 0px -10% 0px' },
    )

    const nodes = document.querySelectorAll('[data-reveal]')
    nodes.forEach((node) => observer.observe(node))

    return () => observer.disconnect()
  }, [surface])

  useEffect(() => {
    const isLanding = surface === 'landing'
    document.body.classList.toggle('landing-surface', isLanding)
    document.body.classList.toggle('menu-open', isLanding && menuOpen)

    return () => {
      document.body.classList.remove('landing-surface')
      document.body.classList.remove('menu-open')
    }
  }, [menuOpen, surface])

  useEffect(() => {
    if (surface !== 'landing' || !menuOpen) return undefined

    const panel = menuPanelRef.current
    const focusableSelector = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    const focusable = panel ? Array.from(panel.querySelectorAll(focusableSelector)) : []

    focusable[0]?.focus()

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        menuToggleRef.current?.focus()
        return
      }

      if (event.key !== 'Tab' || focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [menuOpen, surface])

  function closeMenu() {
    setMenuOpen(false)
    menuToggleRef.current?.focus()
  }

  function openDashboard(e) {
    if (e && e.preventDefault) e.preventDefault()
    setMenuOpen(false)
    setSurface('dashboard')
    window.location.hash = 'workspace'
  }

  function openLanding() {
    setMenuOpen(false)
    setSurface('landing')
    if (typeof window !== 'undefined') {
      window.location.hash = 'overview'
      window.scrollTo({ top: 0 })
    }
  }

  if (surface === 'dashboard') {
    return (
      <Suspense fallback={<div className="dashboard-loading">Loading workspace...</div>}>
        <CalienneDashboard onExitLanding={openLanding} />
      </Suspense>
    )
  }

  return (
    <div className="landing-app">
      <a className="skip-link" href="#content">
        Skip to content
      </a>

      <div className="page-chrome" aria-hidden="true">
        <div className="ambient-orb orb-left" />
        <div className="ambient-orb orb-right" />
        <div className="ambient-grid" />
      </div>

      <header className="site-header">
        <div className="nav-shell">
          <div className="nav-core">
            <a className="brand-lockup" href="#content" aria-label="Calienne home">
              <span className="brand-mark">C</span>
              <span className="brand-copy">
                <strong>Calienne</strong>
                <span>decision room</span>
              </span>
            </a>

            <nav className="nav-links" aria-label="Primary navigation">
              {navItems.map((item) => (
                <a key={item.href} href={item.href}>
                  {item.label}
                </a>
              ))}
            </nav>

            <div className="nav-actions">
              <a className="nav-pill" href={CHAT_HASH} onClick={openDashboard}>Launch room</a>
              <button
                ref={menuToggleRef}
                type="button"
                className={`menu-toggle ${menuOpen ? 'is-open' : ''}`}
                aria-expanded={menuOpen}
                aria-controls="mobile-menu"
                aria-label={menuOpen ? 'Close menu' : 'Open menu'}
                onClick={() => setMenuOpen((open) => !open)}
              >
                <span />
                <span />
              </button>
            </div>
          </div>
        </div>
      </header>

      <div
        className={`menu-overlay ${menuOpen ? 'is-open' : ''}`}
        id="mobile-menu"
        role="dialog"
        aria-modal="true"
        aria-label="Mobile navigation menu"
        aria-labelledby="mobile-menu-title"
        aria-hidden={!menuOpen}
        hidden={!menuOpen}
      >
        <div className="menu-panel" ref={menuPanelRef}>
          <div className="menu-panel-head">
            <p className="eyebrow" id="mobile-menu-title">Navigation</p>
            <button type="button" className="menu-close" onClick={closeMenu} aria-label="Close navigation menu">
              Close
            </button>
          </div>
          <div className="menu-links">
            {navItems.map((item, index) => (
              <a
                key={item.href}
                href={item.href}
                style={{ '--delay': `${120 + index * 60}ms` }}
                onClick={closeMenu}
              >
                <span>{item.label}</span>
                <Icon name="arrow" />
              </a>
            ))}
          </div>
          <div className="menu-footer">
            <p>Signal room for teams that need the argument preserved, not polished away.</p>
            <CTA href={CHAT_HASH} onClick={openDashboard}>Enter the workspace</CTA>
          </div>
        </div>
      </div>

      <main id="content">
        <section className="hero section-frame">
          <div className="hero-copy" data-reveal>
            <span className="eyebrow">Structured dissent for live decisions</span>
            <h1>
              A decision room with enough depth to hold pressure,
              <span className="hero-soft-break"> evidence, and synthesis at once.</span>
            </h1>
            <p className="hero-body">
              Calienne gives product, research, and infrastructure teams a shared surface for hard questions.
              The interface stays quiet while the reasoning gets sharper, more explicit, and easier to reuse.
            </p>
            <div className="hero-actions">
              <CTA href={CHAT_HASH} onClick={openDashboard}>Enter the room</CTA>
              <CTA href="#contact" variant="ghost">
                Talk to the team
              </CTA>
            </div>
            <Frame className="trace-frame hero-trace-frame" innerClassName="trace-core">
              <article className="trace-artifact" data-reveal>
                <div className="trace-artifact-head">
                  <span className="micro-label">Decision trace</span>
                  <span>03 linked records</span>
                </div>
                <div className="trace-lines">
                  {decisionTrace.map((item) => (
                    <div className="trace-line" key={item.label}>
                      <span>{item.label}</span>
                      <p>{item.value}</p>
                    </div>
                  ))}
                </div>
              </article>
            </Frame>
          </div>

          <div className="hero-rail" data-reveal>
            <Frame className="hero-card hero-card-primary" innerClassName="hero-card-inner">
              <div className="hero-card-topline">
                <span>Live room</span>
                <span>balanced mode</span>
              </div>
              <div className="signal-lines" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div className="hero-card-grid">
                <div>
                  <div className="micro-label">prompt</div>
                  <p>Should we optimize for launch speed now, or protect the core model before adoption gets expensive?</p>
                </div>
                <div>
                  <div className="micro-label">synthesis</div>
                  <p>Ship faster on reversible surfaces. Hold the line on identity, billing, and long-lived data shape.</p>
                </div>
              </div>
            </Frame>

            <div className="hero-stack">
              <Frame className="hero-card hero-card-tilt" innerClassName="hero-card-inner compact-core">
                <div className="mini-card-head">
                  <span className="eyebrow small">Pressure map</span>
                  <span className="status-dot" />
                </div>
                <div className="pill-scroller" aria-label="Active signal lanes">
                  <span>assumption drift</span>
                  <span>cost of delay</span>
                  <span>irreversible paths</span>
                  <span>confidence split</span>
                </div>
              </Frame>

              <Frame className="hero-card hero-card-offset" innerClassName="hero-card-inner compact-core">
                <div className="mini-card-head">
                  <span className="eyebrow small">Panel blend</span>
                  <span className="micro-label">4 agents active</span>
                </div>
                <div className="agent-strip">
                  <div><strong>Breaker</strong><span>premise stress</span></div>
                  <div><strong>Logician</strong><span>cost structure</span></div>
                  <div><strong>Judge</strong><span>usable output</span></div>
                </div>
              </Frame>
            </div>
          </div>
        </section>

        <section className="section-frame" id="architecture">
          <div className="section-heading" data-reveal>
            <span className="eyebrow">How a decision gets structured</span>
            <h2>Turn a hard call into claims, pressure tests, objections, and a preserved synthesis.</h2>
            <p>
              Calienne gives every part of the argument a place to live, so the final answer can be audited instead of retold.
            </p>
          </div>

          <div className="bento-grid">
            {architectureCards.map((card, index) => (
              <Frame
                key={card.name}
                className={`bento-frame ${card.tone}`}
                innerClassName="bento-core"
              >
                <article data-reveal style={{ '--stagger': `${index * 90}ms` }}>
                  <div className="card-icon-row">
                    <span className="icon-orbit">
                      <Icon name={card.icon} />
                    </span>
                    <span className="micro-label">{card.name}</span>
                  </div>
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                </article>
              </Frame>
            ))}
          </div>
        </section>

        <section className="section-frame split-section" id="signals">
          <div className="split-copy" data-reveal>
            <span className="eyebrow">How disagreement stays visible</span>
            <h2>Each voice handles a different kind of pressure before consensus hardens.</h2>
            <p>
              Instead of presenting four equally decorative assistants, the room gives each role a job with clear argumentative weight.
            </p>
          </div>

          <div className="split-rail">
            {signalCards.map((card, index) => (
              <Frame key={card.name} className="signal-frame" innerClassName="signal-core">
                <article className="signal-card" data-reveal style={{ '--stagger': `${index * 100}ms` }}>
                  <div className="card-icon-row">
                    <span className="icon-orbit">
                      <Icon name={card.icon} />
                    </span>
                    <span className="micro-label">{card.name}</span>
                  </div>
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                </article>
              </Frame>
            ))}
          </div>
        </section>

        <section className="section-frame" id="flow">
          <div className="section-heading narrow" data-reveal>
            <span className="eyebrow">What gets exported</span>
            <h2>The room moves from ambiguity to a recommendation with its load-bearing doubts intact.</h2>
          </div>

          <div className="flow-grid">
            {flowSteps.map((item, index) => (
              <Frame key={item.step} className="flow-frame" innerClassName="flow-core">
                <article className="flow-card" data-reveal style={{ '--stagger': `${index * 100}ms` }}>
                  <span className="flow-step">{item.step}</span>
                  <h3>{item.title}</h3>
                  <p>{item.body}</p>
                </article>
              </Frame>
            ))}
          </div>
        </section>

        <section className="section-frame proof-section" id="proof">
          <div className="section-heading" data-reveal>
            <span className="eyebrow">Decision trace</span>
            <h2>What survives the meeting is not a summary. It is the argument spine.</h2>
          </div>

          <div className="proof-grid">
            <Frame className="proof-artifact-frame" innerClassName="proof-artifact-core">
              <article className="proof-artifact" data-reveal>
                <div className="trace-artifact-head">
                  <span className="micro-label">Export sample</span>
                  <span>architecture review // saved</span>
                </div>
                <div className="proof-table" aria-label="Example Calienne decision trace">
                  <div><span>Decision</span><p>Delay multi-region writes until identity schema is stable.</p></div>
                  <div><span>Supporting evidence</span><p>Current replication path increases rollback cost on billing and audit tables.</p></div>
                  <div><span>Dissent preserved</span><p>Creative argued for a reversible shadow-write pilot to avoid freezing learning.</p></div>
                  <div><span>Next branch</span><p>If enterprise pilot requires regional failover, scope a bounded data-plane fork.</p></div>
                </div>
              </article>
            </Frame>
            {testimonials.slice(0, 1).map((item) => (
              <Frame key={item.author} className="quote-frame proof-quote-frame" innerClassName="quote-core">
                <article className="quote-card" data-reveal>
                  <span className="quote-mark">Operator evidence</span>
                  <blockquote>{item.quote}</blockquote>
                  <div className="quote-meta">
                    <strong>{item.author}</strong>
                    <span>{item.role}</span>
                  </div>
                </article>
              </Frame>
            ))}
          </div>
        </section>

        <section className="section-frame" id="contact">
          <Frame className="cta-frame" innerClassName="cta-core">
            <div className="cta-band" data-reveal>
              <div>
                <span className="eyebrow">Contact</span>
                <h2>Open a pilot for the decisions your team cannot afford to summarize badly.</h2>
              </div>
              <div className="cta-cluster">
                <CTA href={CHAT_HASH} onClick={openDashboard}>Launch the demo</CTA>
                <a className="text-link" href="mailto:signal@calienne.ai">
                  signal@calienne.ai
                </a>
              </div>
            </div>
          </Frame>
        </section>
      </main>

      <footer className="site-footer">
        <span>Calienne decision room</span>
        <div>
          <a href="#content">Back to top</a>
          <a href="#contact">Contact</a>
          <a href={CHAT_HASH} onClick={openDashboard}>Open workspace</a>
        </div>
      </footer>
    </div>
  )
}
