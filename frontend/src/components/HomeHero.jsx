import { useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { AGENTS } from "../constants/agents.js";
import { QUICK_PROMPTS } from "../constants/prompts.js";
import { HOME_BENTO_CARDS, HOME_ACCORDIONS, HOME_SIGNAL_CARDS } from "../constants/homeContent.js";
import { picsum } from "../utils/id.js";
import FeedbackCarousel from "./FeedbackCarousel.jsx";

gsap.registerPlugin(useGSAP, ScrollTrigger);

function HomeHero({ onQuickPrompt, onFocusInput, onOpenSettings, onOpenTelemetry }) {
  const rootRef = useRef(null);
  const pinnedWrapRef = useRef(null);
  const pinnedCopyRef = useRef(null);
  const revealRef = useRef(null);
  const [activeAccordion, setActiveAccordion] = useState(0);

  useGSAP(() => {
    const scroller = rootRef.current;
    if (!scroller || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    gsap.fromTo(
      ".hero-animate",
      { y: 34, opacity: 0 },
      { y: 0, opacity: 1, stagger: 0.08, duration: 0.9, ease: "power3.out" }
    );

    gsap.fromTo(
      ".hero-float-card",
      { y: 24, opacity: 0, scale: 0.92 },
      { y: 0, opacity: 1, scale: 1, duration: 1.1, ease: "power3.out", delay: 0.15 }
    );

    gsap.utils.toArray(".bento-card").forEach((card, index) => {
      gsap.fromTo(
        card,
        { y: 48, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.8,
          ease: "power3.out",
          scrollTrigger: {
            trigger: card,
            scroller,
            start: "top 84%",
          },
          delay: index * 0.04,
        }
      );
    });

    gsap.utils.toArray(".signal-card").forEach((card, index) => {
      const media = card.querySelector("img");
      gsap.fromTo(
        card,
        { y: 64, opacity: 0.2 },
        {
          y: 0,
          opacity: 1,
          duration: 0.9,
          ease: "power3.out",
          scrollTrigger: {
            trigger: card,
            scroller,
            start: "top 80%",
          },
          delay: index * 0.08,
        }
      );

      if (media) {
        gsap.fromTo(
          media,
          { scale: 0.82, opacity: 0.34 },
          {
            scale: 1,
            opacity: 1,
            ease: "none",
            scrollTrigger: {
              trigger: card,
              scroller,
              start: "top 82%",
              end: "bottom 20%",
              scrub: true,
            },
          }
        );
      }
    });

    if (pinnedWrapRef.current && pinnedCopyRef.current && window.innerWidth >= 900) {
      ScrollTrigger.create({
        trigger: pinnedWrapRef.current,
        scroller,
        start: "top top+=120",
        end: "bottom bottom-=80",
        pin: pinnedCopyRef.current,
        pinSpacing: true,
      });
    }

    const words = gsap.utils.toArray(".reveal-word");
    if (words.length) {
      gsap.fromTo(
        words,
        { opacity: 0.12 },
        {
          opacity: 1,
          stagger: 0.18,
          ease: "none",
          scrollTrigger: {
            trigger: revealRef.current,
            scroller,
            start: "top 76%",
            end: "bottom 40%",
            scrub: true,
          },
        }
      );
    }
  }, { scope: rootRef });

  return (
    <div className="home-experience" ref={rootRef}>
      <section className="hero-stage chapter">
        <div className="hero-copy">
          <p className="hero-kicker hero-animate">Calienne turns high-stakes questions into visible reasoning.</p>
          <h1 className="hero-title hero-animate">
            Pressure-test a decision <span className="inline-pill-image" style={{ backgroundImage: `url(${picsum("ink-current", 320, 160)})` }} aria-hidden="true" /> before consensus <span className="inline-pill-image" style={{ backgroundImage: `url(${picsum("glass-current", 320, 160)})` }} aria-hidden="true" /> hardens.
          </h1>
          <p className="hero-subtitle hero-animate">Four reasoning styles attack the same prompt from different angles, so the argument stays inspectable before it gets flattened into a clean summary.</p>
          <div className="hero-actions hero-animate">
            <button className="btn-primary hero-main-btn" onClick={() => onQuickPrompt(QUICK_PROMPTS[0].text)}>Run a loaded debate <ArrowRight size={15} /></button>
            <button className="hero-ghost-btn" onClick={onFocusInput}>Open a blank thread</button>
          </div>
        </div>

        <div className="hero-float-card hover-card">
          <div className="hero-float-frame overflow-clip">
            <img src={picsum("editorial-decision", 1400, 1100)} alt="" className="hero-float-image hover-media" />
          </div>
          <div className="hero-float-metric">
            <span>Live synthesis stays visible while the prompt is still under stress.</span>
          </div>
        </div>
      </section>

      <section className="chapter section-bento">
        <div className="section-heading">
          <p className="section-kicker">A quieter interface with more pressure inside it.</p>
          <h2>Build the argument in public without making the page feel like a dashboard graveyard.</h2>
        </div>

        <div className="home-bento-grid">
          {HOME_BENTO_CARDS.map((card) => (
            <article key={card.id} className={`bento-card ${card.span} hover-card`}>
              {card.id === "matrix" && (
                <>
                  <div>
                    <p className="bento-kicker">Agent panel</p>
                    <h3>{card.title}</h3>
                    <p>{card.body}</p>
                  </div>
                  <div className="agent-matrix">
                    {AGENTS.map((agent) => (
                      <div
                        key={agent.id}
                        className="agent-tile on"
                        style={{ "--agent-color": agent.color }}
                      >
                        <div className="agent-tile-head">
                          <agent.icon size={16} />
                          <span>{agent.name}</span>
                        </div>
                        <div className="agent-tile-body">{agent.desc}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {card.id === "media" && (
                <>
                  <div className="bento-media overflow-clip">
                    <img src={picsum(card.image, 1400, 1100)} alt="" className="hover-media" />
                  </div>
                  <div>
                    <p className="bento-kicker">Signal view</p>
                    <h3>{card.title}</h3>
                    <p>{card.body}</p>
                  </div>
                </>
              )}

              {card.id === "prompts" && (
                <>
                  <div>
                    <p className="bento-kicker">Quick starts</p>
                    <h3>{card.title}</h3>
                    <p>{card.body}</p>
                  </div>
                  <div className="prompt-stack">
                    {QUICK_PROMPTS.slice(0, 2).map((prompt) => (
                      <button key={prompt.text} className="prompt-stack-card" onClick={() => onQuickPrompt(prompt.text)}>
                        <prompt.icon size={16} />
                        <span>{prompt.text}</span>
                        <ArrowUpRight size={14} />
                      </button>
                    ))}
                  </div>
                </>
              )}

              {card.id === "modes" && (
                <>
                  <div>
                    <p className="bento-kicker">Execution modes</p>
                    <h3>{card.title}</h3>
                    <p>{card.body}</p>
                  </div>
                  <div className="mode-rail">
                    <div className="mode-rail-card">
                      <span>Balanced</span>
                      <p>The fastest way to keep a live room aligned without flattening nuance.</p>
                    </div>
                    <div className="mode-rail-card">
                      <span>Deep</span>
                      <p>Longer proofs, slower confidence, and clearer edges around irreversible choices.</p>
                    </div>
                    <div className="mode-rail-card">
                      <span>Web Search</span>
                      <p>Pull outside context into the same thread when internal memory is not enough.</p>
                    </div>
                  </div>
                </>
              )}
            </article>
          ))}
        </div>

        <div className="accordion-band">
          {HOME_ACCORDIONS.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`accordion-slice${activeAccordion === index ? " active" : ""}`}
              onMouseEnter={() => setActiveAccordion(index)}
              onFocus={() => setActiveAccordion(index)}
            >
              <img src={picsum(item.image, 1200, 1400)} alt="" className="accordion-image" />
              <div className="accordion-overlay" />
              <div className="accordion-copy">
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="chapter section-desire" ref={pinnedWrapRef}>
        <div className="pin-grid">
          <div className="pin-copy" ref={pinnedCopyRef}>
            <p className="section-kicker">Follow the reasoning as it separates into distinct kinds of pressure.</p>
            <h2>Pin the thesis. Let the evidence move past it.</h2>
            <p className="pin-body reveal-copy" ref={revealRef}>
              {"Breaker isolates the untested premise while Logician forces structure, Creative opens alternate paths, and Judge recomposes the result into a recommendation the team can actually defend.".split(" ").map((word, index) => (
                <span key={`${word}-${index}`} className="reveal-word">{word} </span>
              ))}
            </p>
          </div>

          <div className="signal-stack">
            {HOME_SIGNAL_CARDS.map((card) => (
              <article key={card.title} className="signal-card hover-card">
                <div className="signal-card-media overflow-clip">
                  <img src={picsum(card.image, 1400, 1100)} alt="" className="hover-media" />
                </div>
                <div className="signal-card-copy">
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <FeedbackCarousel
        onOpenSettings={onOpenSettings}
        onOpenTelemetry={onOpenTelemetry}
        onFocusInput={onFocusInput}
      />
    </div>
  );
}

export default HomeHero;
