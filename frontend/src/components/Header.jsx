import { memo, useState, useEffect, useRef } from "react";
import {
  Menu, Plus, Settings, Bell,
  ChevronLeft, Activity, LogOut,
  ShieldCheck, PanelLeft, PanelRight, Rows, Square, MoreHorizontal,
} from "lucide-react";
import Popover from "./Popover.jsx";
import SessionClock from "./SessionClock.jsx";
import { PULSE_DURATION } from "../constants/timing.js";

const Header = memo(function Header({
  models, toggleModel, addModel, onOpenSettings, onOpenStudio,
  layoutMode, setLayoutMode, isNarrow, notifications, markAllRead,
  onMissionControl, onTelemetry, onLogout, onOpenSidebarMobile, onExitLanding,
  isAdmin, userEmail,
}) {
  const [newModelName, setNewModelName] = useState("");
  const [pulsingChipId, setPulsingChipId] = useState(null);
  const chipPulseTimeoutRef = useRef(null);
  const unread = notifications.filter((n) => !n.read).length;

  useEffect(() => () => clearTimeout(chipPulseTimeoutRef.current), []);

  async function submitModel(close) {
    const name = newModelName.trim();
    if (!name) return;
    if (await addModel(name)) {
      setNewModelName("");
      close();
    }
  }

  function handleToggleModel(id) {
    toggleModel(id);
    setPulsingChipId(id);
    clearTimeout(chipPulseTimeoutRef.current);
    chipPulseTimeoutRef.current = setTimeout(() => {
      setPulsingChipId((currentId) => (currentId === id ? null : currentId));
    }, PULSE_DURATION);
  }

  const layoutBtns = [
    { mode: "left", label: "Show Left Panel", icon: PanelLeft },
    { mode: "right", label: "Show Right Panel", icon: PanelRight },
    { mode: "both", label: "Show Both Panels", icon: Rows },
    { mode: "hidden", label: "Hide Panels", icon: Square },
  ];

  const displayModels = (() => {
    const configuredOnly = models.filter((m) => m.custom || m.configured);
    return configuredOnly.length > 0 ? configuredOnly : models;
  })();

  return (
    <header className="header">
      <div className="header-left">
        <button className="icon-btn mobile-only" onClick={onOpenSidebarMobile} aria-label="Open conversations panel"><Menu size={18} /></button>
        <div className="brand" title="Calienne - Reasoning, arbitrated.">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none">
              <path d="M12 3L4 19H8.5L12 11L15.5 19H20L12 3Z" stroke="var(--text)" strokeWidth="1.6" strokeLinejoin="round" />
              <circle cx="12" cy="14" r="2.5" fill="#00F0FF" />
              <path d="M6.5 14H17.5" stroke="#00F0FF" strokeWidth="1.2" strokeDasharray="2 2" opacity="0.8" />
            </svg>
          </span>
          <span className="brand-name">Calienne</span>
          <span className="brand-ver">REV 2.0</span>
        </div>
        {onExitLanding && <button className="text-btn desktop-only return-btn" onClick={onExitLanding}><ChevronLeft size={14} /> Overview</button>}
      </div>

      <div className="header-models">
        {displayModels.map((model) => (
          <button
            key={model.full_id || model.id}
            className={`chip${model.active ? " chip-active" : ""}${pulsingChipId === (model.full_id || model.id) ? " chip-pulse" : ""}`}
            onClick={() => handleToggleModel(model.full_id || model.id)}
            title={model.active ? "Click to deactivate model" : "Click to activate model"}
          >
            <span className={`chip-dot${model.active ? " on" : ""}`} />
            {model.name}
          </button>
        ))}
        {isAdmin && <Popover align="left"
          renderTrigger={({ triggerRef, toggle }) => (
            <button ref={triggerRef} className="chip chip-ghost" onClick={toggle}><Plus size={13} /> Add Model</button>
          )}>
          {({ close }) => (
            <div className="add-model-pop">
              <input autoFocus className="text-input" placeholder="e.g. qwen-2.5-72b" value={newModelName}
                onChange={(e) => setNewModelName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitModel(close)} />
              <button className="btn-primary sm" onClick={() => submitModel(close)}>Add</button>
            </div>
          )}
        </Popover>}
        {isAdmin && <button className="chip chip-ghost chip-studio-btn" onClick={onOpenStudio} title="Open Model & Provider Studio">
          ⚡ Model &amp; Provider Studio
        </button>}
      </div>

      <div className="header-right">
        <button className="text-btn desktop-only" onClick={onMissionControl}><ShieldCheck size={14} /> Mission Control</button>
        <button className="text-btn desktop-only" onClick={onTelemetry}><Activity size={14} /> Telemetry</button>

        <Popover align="right"
          renderTrigger={({ triggerRef, toggle }) => (
            <button ref={triggerRef} className="icon-btn tooltip desktop-only" data-tip="Session" onClick={toggle}><Settings size={17} /></button>
          )}>
          {({ close }) => (
            <div className="session-block">
              <div className="session-row"><span>Uptime</span><SessionClock /></div>
              <div className="session-row"><span>Build</span><span className="mono">REV 2.0</span></div>
              <div className="dd-sep" />
              {isAdmin && <button className="dd-item" onClick={() => { close(); onOpenStudio?.(); }}><Activity size={13} /> Model &amp; Provider Studio</button>}
              <button className="dd-item" onClick={() => { close(); onOpenSettings(); }}><Settings size={13} /> Open Settings</button>
            </div>
          )}
        </Popover>

        <Popover align="right" menuClassName="notif-pop"
          renderTrigger={({ triggerRef, toggle }) => (
            <button ref={triggerRef} className="icon-btn tooltip desktop-only" data-tip="Notifications" onClick={toggle}>
              <Bell size={17} />
              {unread > 0 && <span className="badge" key={unread}>{unread}</span>}
            </button>
          )}>
          {() => (
            <>
              <div className="dd-label-row">
                <span className="dd-label">Notifications</span>
                <button className="link-btn" onClick={markAllRead}>Mark all read</button>
              </div>
              {notifications.map((notification) => (
                <div key={notification.id} className={`notif-item${notification.read ? "" : " unread"}`}>
                  <span className="notif-dot" />
                  <div>
                    <div className="notif-text">{notification.text}</div>
                    <div className="notif-time">{notification.time}</div>
                  </div>
                </div>
              ))}
            </>
          )}
        </Popover>

        <Popover align="right"
          renderTrigger={({ triggerRef, toggle }) => (
            <button ref={triggerRef} className="avatar-btn" onClick={toggle} aria-label="Account menu">A</button>
          )}>
          {({ close }) => (
            <>
              <div className="acct-info">
                <div className="acct-avatar">A</div>
                <div>
                  <div className="acct-name">{userEmail || "Signed in"}</div>
                  <div className="acct-plan">{isAdmin ? "Administrator" : "Member"}</div>
                </div>
              </div>
              <div className="dd-sep" />
              <button className="dd-item danger" onClick={() => { close(); onLogout(); }}><LogOut size={14} /> Log Out</button>
            </>
          )}
        </Popover>

        {/* Mobile only: Models + Session + Notifications folded into one menu.
            Three separate icon buttons for these, plus Account, plus hamburger,
            plus the layout-group, do not fit any phone viewport — measured,
            not assumed (see prior width audit). Account stays separate since
            it's the one item worth a permanent, always-reachable affordance. */}
        <Popover align="right" menuClassName="models-pop mobile-more-pop"
          renderTrigger={({ triggerRef, toggle }) => (
            <button ref={triggerRef} className="icon-btn tooltip mobile-only" data-tip="More" onClick={toggle}>
              <MoreHorizontal size={18} />
              {unread > 0 && <span className="badge" key={unread}>{unread}</span>}
            </button>
          )}>
          {({ close }) => (
            <>
              <div className="dd-label">Active Models</div>
              <div className="models-pop-list">
                {models.map((model) => (
                  <button key={model.id} className={`chip${model.active ? " chip-active" : ""}${pulsingChipId === model.full_id ? " chip-pulse" : ""}`} onClick={() => handleToggleModel(model.full_id)} disabled={!isAdmin}>
                    <span className={`chip-dot${model.active ? " on" : ""}`} />
                    {model.name}
                  </button>
                ))}
              </div>
              {isAdmin && <div className="add-model-pop">
                <input className="text-input" placeholder="e.g. qwen-2.5-72b" value={newModelName}
                  onChange={(e) => setNewModelName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submitModel(close)} />
                <button className="btn-primary sm" onClick={() => submitModel(close)}>Add</button>
              </div>}

              <div className="dd-sep" />
              <div className="session-row"><span>Uptime</span><SessionClock /></div>
              <div className="session-row"><span>Build</span><span className="mono">REV 2.0</span></div>
              <button className="dd-item" onClick={() => { close(); onOpenSettings(); }}><Settings size={13} /> Open Settings</button>

              <div className="dd-sep" />
              <div className="dd-label-row">
                <span className="dd-label">Notifications</span>
                <button className="link-btn" onClick={markAllRead}>Mark all read</button>
              </div>
              {notifications.map((notification) => (
                <div key={notification.id} className={`notif-item${notification.read ? "" : " unread"}`}>
                  <span className="notif-dot" />
                  <div>
                    <div className="notif-text">{notification.text}</div>
                    <div className="notif-time">{notification.time}</div>
                  </div>
                </div>
              ))}
            </>
          )}
        </Popover>

        <div className="layout-group desktop-only" role="group" aria-label="Panel layout">
          {layoutBtns
            .filter((b) => !(isNarrow && b.mode === "both"))
            .map((b) => (
              <button key={b.mode}
                className={`icon-btn tooltip${layoutMode === b.mode ? " active" : ""}`}
                data-tip={b.label}
                aria-label={b.label}
                onClick={() => setLayoutMode(b.mode)} aria-pressed={layoutMode === b.mode}>
                <b.icon size={15} />
              </button>
            ))}
        </div>

        {/* layoutMode can only be hidden/left/right while isNarrow (changeLayoutMode
            clamps "both" to "hidden" below 900px) so this check doesn't need
            to also test for "both" the way the desktop toggle group does. */}
        <button className="icon-btn tooltip mobile-only"
          data-tip={layoutMode === "right" ? "Hide Telemetry" : "Show Telemetry"}
          aria-label="Toggle telemetry panel"
          aria-pressed={layoutMode === "right"}
          onClick={() => setLayoutMode(layoutMode === "right" ? "hidden" : "right")}>
          <PanelRight size={17} />
        </button>
      </div>
    </header>
  );
});

export default Header;
