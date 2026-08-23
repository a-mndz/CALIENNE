import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useEscapeKey } from "../hooks/useEscapeKey.js";
import { useFocusTrap } from "../hooks/useFocusTrap.js";

const PROVIDER_PRESETS = [
  { name: "Ollama (Local)", url: "http://localhost:11434/v1", icon: "🦙", hint: "Local Ollama on port 11434" },
  { name: "vLLM (Local)", url: "http://localhost:8000/v1", icon: "🐋", hint: "Local vLLM / SGLang on port 8000" },
  { name: "DeepSeek API", url: "https://api.deepseek.com/v1", icon: "⚡", hint: "Official DeepSeek V3 / R1 endpoint" },
  { name: "OpenRouter", url: "https://openrouter.ai/api/v1", icon: "🌐", hint: "Unified open & proprietary model gateway" },
  { name: "Together AI", url: "https://api.together.xyz/v1", icon: "🤝", hint: "Together inference cloud" },
  { name: "OpenAI", url: "https://api.openai.com/v1", icon: "🧠", hint: "Direct OpenAI API" },
  { name: "Groq Cloud", url: "https://api.groq.com/openai/v1", icon: "🚀", hint: "Ultra-fast LPU inference" },
];

export default function ModelApiStudioModal({
  isOpen,
  onClose,
  models = [],
  onToggleModel,
  onRefresh,
  inline = false,
}) {
  const [activeTab, setActiveTab] = useState("models"); // 'models' | 'add_provider' | 'providers' | 'vault'
  const [roleFilter, setRoleFilter] = useState("all"); // 'all' | 'judge' | 'generation' | 'breaker'

  // Providers list state
  const [customProviders, setCustomProviders] = useState([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [rolePreferences, setRolePreferences] = useState({});

  // Tab 2: Add Provider & Discover Models state
  const [providerName, setProviderName] = useState("");
  const [providerUrl, setProviderUrl] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [showProviderKey, setShowProviderKey] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [discoveredModels, setDiscoveredModels] = useState([]);
  const [selectedModelIds, setSelectedModelIds] = useState(new Set());
  const [modelRoleOverrides, setModelRoleOverrides] = useState({});
  const [defaultImportRoles, setDefaultImportRoles] = useState({ generation: true, judge: false, breaker: false });
  const [modelSearchTerm, setModelSearchTerm] = useState("");
  const [savingProvider, setSavingProvider] = useState(false);
  const [providerMsg, setProviderMsg] = useState(null);

  // Tab 4: Vault state
  const [vaultProviders, setVaultProviders] = useState([]);
  const [loadingVault, setLoadingVault] = useState(false);
  const [keyInputs, setKeyInputs] = useState({});
  const [showKey, setShowKey] = useState({});
  const [savingKey, setSavingKey] = useState({});
  const [vaultMsg, setVaultMsg] = useState({});

  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const previousFocusRef = useRef(null);

  useFocusTrap(!inline && isOpen, dialogRef);
  useEscapeKey(useCallback(() => {
    if (isOpen && onClose) onClose();
  }, [isOpen, onClose]));

  useEffect(() => {
    if (!isOpen || inline) return;
    previousFocusRef.current = document.activeElement;
    closeRef.current?.focus();
    return () => previousFocusRef.current?.focus?.();
  }, [isOpen, inline]);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const res = await fetch("/api/providers", { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        setCustomProviders(data.providers || []);
        setRolePreferences(data.preferences || {});
      }
    } catch (err) {
      console.error("Could not fetch custom providers", err);
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const fetchVaultStatus = useCallback(async () => {
    setLoadingVault(true);
    try {
      const res = await fetch("/api/config/vault", { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        setVaultProviders(data.providers || []);
      }
    } catch (err) {
      console.error("Could not fetch vault status", err);
    } finally {
      setLoadingVault(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchProviders();
      fetchVaultStatus();
    }
  }, [isOpen, fetchProviders, fetchVaultStatus]);

  if (!isOpen) return null;

  // ── Step 1: Discover models from Provider URL + API Key ─────────────────────
  const handleDiscoverModels = async (e) => {
    if (e) e.preventDefault();
    if (!providerUrl.trim()) return;

    setFetchingModels(true);
    setProviderMsg(null);
    setDiscoveredModels([]);
    setSelectedModelIds(new Set());
    setModelRoleOverrides({});

    try {
      const res = await fetch("/api/providers/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          base_url: providerUrl.trim(),
          api_key: providerKey.trim() || undefined,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const found = data.models || [];
        setDiscoveredModels(found);
        if (found.length === 0) {
          setProviderMsg({ type: "error", text: "Connected successfully, but no models were returned by the endpoint." });
        } else {
          // Pre-select first 3 or all if few
          const initialSelection = new Set(found.slice(0, 5).map((m) => m.id));
          setSelectedModelIds(initialSelection);
          setProviderMsg({
            type: "success",
            text: `Connected successfully! Found ${found.length} available model(s). Select which ones to import below.`,
          });
        }
      } else {
        const err = await res.json().catch(() => ({ detail: "Connection failed" }));
        setProviderMsg({ type: "error", text: err.detail || "Failed to discover models from provider." });
      }
    } catch (err) {
      setProviderMsg({ type: "error", text: `Connection error: ${err.message}` });
    } finally {
      setFetchingModels(false);
    }
  };

  // ── Step 2: Toggle Model Selection ──────────────────────────────────────────
  const toggleModelSelect = (id) => {
    setSelectedModelIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedModelIds(new Set(discoveredModels.map((m) => m.id)));
  };

  const handleDeselectAll = () => {
    setSelectedModelIds(new Set());
  };

  const handleModelRoleToggle = (modelId, role) => {
    setModelRoleOverrides((prev) => {
      const currentRoles = prev[modelId] || (
        Object.entries(defaultImportRoles).filter(([, v]) => v).map(([k]) => k)
      );
      const nextRoles = currentRoles.includes(role)
        ? currentRoles.filter((r) => r !== role)
        : [...currentRoles, role];
      return {
        ...prev,
        [modelId]: nextRoles.length > 0 ? nextRoles : ["generation"],
      };
    });
  };

  // ── Step 3: Save Provider and Import Selected Models to Keyring ─────────────
  const handleSaveAndImport = async () => {
    if (!providerName.trim() || !providerUrl.trim()) {
      setProviderMsg({ type: "error", text: "Provider name and API base URL are required." });
      return;
    }
    if (selectedModelIds.size === 0) {
      setProviderMsg({ type: "error", text: "Please check at least one model to import." });
      return;
    }

    setSavingProvider(true);
    setProviderMsg(null);

    try {
      const baseRoles = Object.entries(defaultImportRoles).filter(([, v]) => v).map(([k]) => k);
      const effectiveDefaultRoles = baseRoles.length > 0 ? baseRoles : ["generation"];

      const modelsToImport = Array.from(selectedModelIds).map((mid) => {
        const found = discoveredModels.find((m) => m.id === mid) || { id: mid, name: mid };
        const roles = modelRoleOverrides[mid] || effectiveDefaultRoles;
        return {
          id: found.id,
          name: found.name || found.id,
          roles,
          enabled: true,
          context_length: found.context_length,
          description: found.description,
        };
      });

      const payload = {
        name: providerName.trim(),
        base_url: providerUrl.trim(),
        api_key: providerKey.trim() || undefined,
        models: modelsToImport,
      };

      const res = await fetch("/api/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        setProviderMsg({
          type: "success",
          text: `🎉 Successfully imported ${modelsToImport.length} model(s)! API Key securely locked in OS Keyring.`,
        });
        setProviderKey("");
        fetchProviders();
        if (onRefresh) onRefresh();
        // Switch to models tab after short delay
        setTimeout(() => setActiveTab("models"), 1200);
      } else {
        const err = await res.json().catch(() => ({ detail: "Failed to save provider" }));
        setProviderMsg({ type: "error", text: err.detail || "Failed to register provider." });
      }
    } catch (err) {
      setProviderMsg({ type: "error", text: err.message });
    } finally {
      setSavingProvider(false);
    }
  };

  // ── Role Management (Toggle Judge / Generation / Breaker for active model) ─
  const handleToggleRoleForModel = async (fullModelId, roleToToggle) => {
    const targetModel = models.find((m) => m.full_id === fullModelId);
    if (!targetModel) return;

    const currentRoles = targetModel.roles || ["generation"];
    const nextRoles = currentRoles.includes(roleToToggle)
      ? currentRoles.filter((r) => r !== roleToToggle)
      : [...currentRoles, roleToToggle];

    if (nextRoles.length === 0) {
      alert("A model must have at least one assigned role.");
      return;
    }

    try {
      const res = await fetch("/api/models/roles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ model_id: fullModelId, roles: nextRoles }),
      });
      if (res.ok) {
        if (onRefresh) onRefresh();
        fetchProviders();
      }
    } catch (err) {
      console.error("Failed to update model roles", err);
    }
  };

  // ── Set Primary Judge or Generation Model ──────────────────────────────────
  const handleSetPrimaryModel = async (role, fullModelId) => {
    try {
      const res = await fetch("/api/models/primary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ role, model_id: fullModelId }),
      });
      if (res.ok) {
        if (onRefresh) onRefresh();
        fetchProviders();
      }
    } catch (err) {
      console.error("Failed to set primary model", err);
    }
  };

  // ── Delete Custom Provider ────────────────────────────────────────────────
  const handleDeleteProvider = async (providerId) => {
    if (!confirm(`Are you sure you want to remove provider "${providerId}" and its keyring credentials?`)) {
      return;
    }
    try {
      const res = await fetch(`/api/providers/${providerId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (res.ok) {
        fetchProviders();
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      console.error("Failed to delete provider", err);
    }
  };

  // ── Delete Single Custom Model ────────────────────────────────────────────
  const handleDeleteCustomModel = async (fullModelId) => {
    if (!confirm(`Remove model "${fullModelId}" from the orchestrator?`)) return;
    try {
      const res = await fetch("/api/models/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ id: fullModelId }),
      });
      if (res.ok) {
        if (onRefresh) onRefresh();
        fetchProviders();
      }
    } catch (err) {
      console.error("Failed to delete model", err);
    }
  };

  // ── Tab 4: Save built-in key to vault ──────────────────────────────────────
  const handleSaveVaultKey = async (account) => {
    const secret = (keyInputs[account] || "").trim();
    if (!secret) return;

    setSavingKey((p) => ({ ...p, [account]: true }));
    setVaultMsg((p) => ({ ...p, [account]: null }));
    try {
      const res = await fetch("/api/config/vault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ account, secret }),
      });
      if (res.ok) {
        const data = await res.json();
        setVaultProviders(data.providers || []);
        setKeyInputs((p) => ({ ...p, [account]: "" }));
        const storageLabel = data.storage === "keyring" ? "OS keyring" : "process memory";
        setVaultMsg((p) => ({ ...p, [account]: { type: "success", text: `Saved to ${storageLabel}.` } }));
      } else {
        setVaultMsg((p) => ({ ...p, [account]: { type: "error", text: "Failed to save secret" } }));
      }
    } catch (err) {
      setVaultMsg((p) => ({ ...p, [account]: { type: "error", text: err.message } }));
    } finally {
      setSavingKey((p) => ({ ...p, [account]: false }));
    }
  };

  // Filter models for Tab 1
  const filteredModels = useMemo(() => {
    if (roleFilter === "all") return models;
    if (roleFilter === "configured") return models.filter((m) => m.configured || m.custom);
    return models.filter((m) => (m.roles || []).includes(roleFilter));
  }, [models, roleFilter]);

  // Filter discovered models in Tab 2
  const filteredDiscoveredModels = useMemo(() => {
    if (!modelSearchTerm.trim()) return discoveredModels;
    const term = modelSearchTerm.toLowerCase();
    return discoveredModels.filter(
      (m) => m.id.toLowerCase().includes(term) || (m.name && m.name.toLowerCase().includes(term))
    );
  }, [discoveredModels, modelSearchTerm]);

  // Find currently active primary models
  const primaryGenModel = useMemo(() => {
    return models.find((m) => m.is_primary_generation)?.full_id || "";
  }, [models]);

  const primaryJudgeModel = useMemo(() => {
    return models.find((m) => m.is_primary_judge)?.full_id || "";
  }, [models]);

  const primaryBreakerModel = useMemo(() => {
    return models.find((m) => m.is_primary_breaker)?.full_id || "";
  }, [models]);

  const [strategyMode, setStrategyMode] = useState("HYBRID");

  const handleSetStrategyMode = async (mode) => {
    try {
      const res = await fetch("/api/strategy/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ mode }),
      });
      if (res.ok) {
        setStrategyMode(mode);
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      console.error("Failed to update strategy mode", err);
    }
  };

  const handleMoveModelInChain = async (fullModelId, role, direction) => {
    const roleModels = models.filter((m) => (m.roles || []).includes(role)).map((m) => m.full_id);
    const idx = roleModels.indexOf(fullModelId);
    if (idx < 0) return;
    const targetIdx = direction === "up" ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= roleModels.length) return;

    const newChain = [...roleModels];
    const temp = newChain[idx];
    newChain[idx] = newChain[targetIdx];
    newChain[targetIdx] = temp;

    try {
      const res = await fetch("/api/models/chain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ role, chain: newChain }),
      });
      if (res.ok) {
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      console.error("Failed to reorder chain", err);
    }
  };

  const cardContent = (
    <div
      ref={inline ? null : dialogRef}
      className={inline ? "studio-inline-card" : "studio-modal-card"}
      role={inline ? "region" : "dialog"}
      aria-modal={inline ? undefined : "true"}
      aria-labelledby="studio-modal-title"
      onMouseDown={inline ? undefined : (e) => e.stopPropagation()}
    >
      {/* Modal Header */}
      <div className="studio-modal-header">
        <div>
          <div className="studio-modal-tag">⚡ SYSTEM SETTINGS &amp; PROVIDERS</div>
          <h2 id="studio-modal-title" className="studio-modal-title">Model &amp; Provider Studio</h2>
          <p className="studio-modal-subtitle">
            Add AI providers, auto-discover &amp; import models with OS Keyring protection, and configure the Consensus Audit Judge.
          </p>
        </div>
        {onClose && (
          <button
            ref={inline ? null : closeRef}
            className={inline ? "studio-back-btn" : "studio-close-btn"}
            onClick={onClose}
            aria-label={inline ? "Back to Workspace" : "Close Studio"}
          >
            {inline ? "← Back to Workspace" : "✕"}
          </button>
        )}
      </div>

      {/* Navigation Tabs */}
        <div className="studio-tabs">
          <button
            className={`studio-tab-btn ${activeTab === "models" ? "active" : ""}`}
            onClick={() => setActiveTab("models")}
          >
            <span>🦾</span> Active Pipeline & Roles ({models.length})
          </button>
          <button
            className={`studio-tab-btn ${activeTab === "add_provider" ? "active" : ""}`}
            onClick={() => setActiveTab("add_provider")}
          >
            <span>➕</span> Add Provider & Import
          </button>
          <button
            className={`studio-tab-btn ${activeTab === "providers" ? "active" : ""}`}
            onClick={() => setActiveTab("providers")}
          >
            <span>🎛️</span> Configured Providers ({customProviders.length})
          </button>
          <button
            className={`studio-tab-btn ${activeTab === "vault" ? "active" : ""}`}
            onClick={() => setActiveTab("vault")}
          >
            <span>🔒</span> Keyring Vault
          </button>
        </div>

        {/* Tab Contents */}
        <div className="studio-modal-body">
          {/* ═══════════════════════════════════════════════════════════════════
              TAB 1: Active Pipeline Models & Role Assignment
             ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === "models" && (
            <div className="studio-models-pane">
              {/* Orchestrator Leadership & Primary Roles Dashboard */}
              <div className="studio-orchestrator-grid">
                {/* Generation Engine */}
                <div className="orchestrator-role-card gen-role-card">
                  <div className="role-card-top">
                    <span className="role-card-icon">🦾</span>
                    <div>
                      <div className="role-card-title">Lead Generation Engine</div>
                      <div className="role-card-desc">Primary agent for logician, creative, and analyst reasoning</div>
                    </div>
                  </div>
                  <select
                    className="orchestrator-select-dropdown gen-select"
                    value={primaryGenModel}
                    onChange={(e) => handleSetPrimaryModel("generation", e.target.value)}
                  >
                    <option value="" disabled>Select Lead Generator...</option>
                    {models
                      .filter((m) => (m.roles || []).includes("generation"))
                      .map((m) => (
                        <option key={m.full_id} value={m.full_id}>
                          🦾 {m.name} ({m.provider})
                        </option>
                      ))}
                    {models.filter((m) => (m.roles || []).includes("generation")).length === 0 && (
                      <option disabled>No models assigned to Generation</option>
                    )}
                  </select>
                </div>

                {/* Consensus Audit Judge */}
                <div className="orchestrator-role-card judge-role-card">
                  <div className="role-card-top">
                    <span className="role-card-icon">⚖️</span>
                    <div>
                      <div className="role-card-title">Consensus Audit Judge</div>
                      <div className="role-card-desc">Arbitrates between hypotheses and guarantees invariant output</div>
                    </div>
                  </div>
                  <select
                    className="orchestrator-select-dropdown judge-select"
                    value={primaryJudgeModel}
                    onChange={(e) => handleSetPrimaryModel("judge", e.target.value)}
                  >
                    <option value="" disabled>Select Audit Judge...</option>
                    {models
                      .filter((m) => (m.roles || []).includes("judge"))
                      .map((m) => (
                        <option key={m.full_id} value={m.full_id}>
                          ⚖️ {m.name} ({m.provider})
                        </option>
                      ))}
                    {models.filter((m) => (m.roles || []).includes("judge")).length === 0 && (
                      <option disabled>No models assigned to Judge</option>
                    )}
                  </select>
                </div>

                {/* Circuit Breaker Shield */}
                <div className="orchestrator-role-card breaker-role-card">
                  <div className="role-card-top">
                    <span className="role-card-icon">🛡️</span>
                    <div>
                      <div className="role-card-title">Circuit Breaker &amp; Shield</div>
                      <div className="role-card-desc">Safety enforcement, injection defense, and emergency failover</div>
                    </div>
                  </div>
                  <select
                    className="orchestrator-select-dropdown breaker-select"
                    value={primaryBreakerModel}
                    onChange={(e) => handleSetPrimaryModel("breaker", e.target.value)}
                  >
                    <option value="" disabled>Select Circuit Breaker...</option>
                    {models
                      .filter((m) => (m.roles || []).includes("breaker"))
                      .map((m) => (
                        <option key={m.full_id} value={m.full_id}>
                          🛡️ {m.name} ({m.provider})
                        </option>
                      ))}
                    {models.filter((m) => (m.roles || []).includes("breaker")).length === 0 && (
                      <option disabled>No models assigned to Breaker</option>
                    )}
                  </select>
                </div>
              </div>

              {/* Strategy Mode Control Banner */}
              <div className="studio-strategy-banner">
                <div className="strategy-info">
                  <span className="strategy-icon">🎛️</span>
                  <div>
                    <span className="strategy-title">Operating Strategy Mode:</span>
                    <span className="strategy-sub">Governs automatic tier routing and fallback behavior</span>
                  </div>
                </div>
                <div className="strategy-mode-pills">
                  <button
                    type="button"
                    className={`strategy-pill ${strategyMode === "FREE" ? "active" : ""}`}
                    onClick={() => handleSetStrategyMode("FREE")}
                  >
                    ⚡ FREE (Local / Open-Source)
                  </button>
                  <button
                    type="button"
                    className={`strategy-pill ${strategyMode === "HYBRID" ? "active" : ""}`}
                    onClick={() => handleSetStrategyMode("HYBRID")}
                  >
                    ⚖️ HYBRID (Smart Fallback)
                  </button>
                  <button
                    type="button"
                    className={`strategy-pill ${strategyMode === "PAID" ? "active" : ""}`}
                    onClick={() => handleSetStrategyMode("PAID")}
                  >
                    🚀 PAID (Frontier Commercial)
                  </button>
                </div>
              </div>

              {/* Filter Pills and Refresh Button */}
              <div className="studio-filter-bar">
                <div className="studio-role-filter-pills">
                  <button
                    className={`filter-pill ${roleFilter === "all" ? "active" : ""}`}
                    onClick={() => setRoleFilter("all")}
                  >
                    All Models ({models.length})
                  </button>
                  <button
                    className={`filter-pill pill-configured ${roleFilter === "configured" ? "active" : ""}`}
                    onClick={() => setRoleFilter("configured")}
                  >
                    🔒 Configured Only ({models.filter((m) => m.configured || m.custom).length})
                  </button>
                  <button
                    className={`filter-pill pill-generation ${roleFilter === "generation" ? "active" : ""}`}
                    onClick={() => setRoleFilter("generation")}
                  >
                    🦾 Generation ({models.filter((m) => (m.roles || []).includes("generation")).length})
                  </button>
                  <button
                    className={`filter-pill pill-judge ${roleFilter === "judge" ? "active" : ""}`}
                    onClick={() => setRoleFilter("judge")}
                  >
                    ⚡ Audit Judges ({models.filter((m) => (m.roles || []).includes("judge")).length})
                  </button>
                  <button
                    className={`filter-pill pill-breaker ${roleFilter === "breaker" ? "active" : ""}`}
                    onClick={() => setRoleFilter("breaker")}
                  >
                    🛡️ Circuit Breakers ({models.filter((m) => (m.roles || []).includes("breaker")).length})
                  </button>
                </div>
                <button className="studio-refresh-btn" onClick={onRefresh}>
                  🔄 Refresh Status
                </button>
              </div>

              {/* Models List */}
              <div className="studio-models-list">
                {filteredModels.length === 0 ? (
                  <div className="studio-empty-state">
                    No models match the selected filter. Click <strong>"Add Provider & Import"</strong> to register your models.
                  </div>
                ) : (
                  filteredModels.map((m) => {
                    const isPrimaryJudge = m.is_primary_judge;
                    const isPrimaryGen = m.is_primary_generation;
                    const isPrimaryBreaker = m.is_primary_breaker;
                    const hasJudgeRole = (m.roles || []).includes("judge");
                    const hasGenRole = (m.roles || []).includes("generation");
                    const hasBreakerRole = (m.roles || []).includes("breaker");
                    const isConfigured = m.configured || m.custom;

                    return (
                      <div
                        key={m.full_id || m.id}
                        className={`studio-model-card ${m.active ? "active" : "inactive"} ${isPrimaryJudge ? "primary-judge-card" : isPrimaryGen ? "primary-gen-card" : isPrimaryBreaker ? "primary-breaker-card" : ""}`}
                      >
                        <div className="studio-model-info">
                          <div className="studio-model-top">
                            <span className="studio-model-name">{m.name}</span>
                            <span className="studio-provider-badge">{m.provider || "gateway"}</span>
                            {isPrimaryGen && (
                              <span className="studio-primary-gen-badge">👑 PRIMARY GENERATION</span>
                            )}
                            {isPrimaryJudge && (
                              <span className="studio-primary-judge-badge">⚖️ PRIMARY JUDGE</span>
                            )}
                            {isPrimaryBreaker && (
                              <span className="studio-primary-breaker-badge">🛡️ PRIMARY BREAKER</span>
                            )}
                            {m.custom ? (
                              <span className="studio-custom-badge">CUSTOM</span>
                            ) : isConfigured ? (
                              <span className="studio-configured-badge">🔒 READY</span>
                            ) : (
                              <span className="studio-unconfigured-badge" title="No API Key configured in vault or env for this provider">⚠️ NO KEY</span>
                            )}
                          </div>
                          <div className="studio-model-fullid">{m.full_id || m.id}</div>

                          {/* Role Toggle Chips */}
                          <div className="studio-interactive-roles">
                            <span className="role-label-text">Assigned Roles:</span>
                            <button
                              type="button"
                              className={`studio-role-toggle-chip ${hasGenRole ? "active-gen" : "inactive-chip"}`}
                              onClick={() => handleToggleRoleForModel(m.full_id, "generation")}
                              title="Click to toggle Generation role"
                            >
                              🦾 GENERATION {hasGenRole ? "✓" : "+"}
                            </button>
                            <button
                              type="button"
                              className={`studio-role-toggle-chip ${hasJudgeRole ? "active-judge" : "inactive-chip"}`}
                              onClick={() => handleToggleRoleForModel(m.full_id, "judge")}
                              title="Click to toggle Audit Judge role"
                            >
                              ⚡ JUDGE {hasJudgeRole ? "✓" : "+"}
                            </button>
                            <button
                              type="button"
                              className={`studio-role-toggle-chip ${hasBreakerRole ? "active-breaker" : "inactive-chip"}`}
                              onClick={() => handleToggleRoleForModel(m.full_id, "breaker")}
                              title="Click to toggle Circuit Breaker role"
                            >
                              🛡️ BREAKER {hasBreakerRole ? "✓" : "+"}
                            </button>

                            {/* Set Primary Actions for all roles */}
                            {hasGenRole && !isPrimaryGen && (
                              <button
                                type="button"
                                className="studio-make-primary-btn gen-primary-btn"
                                onClick={() => handleSetPrimaryModel("generation", m.full_id)}
                                title="Set as Primary Generation Engine"
                              >
                                ⭐ Set Primary Gen
                              </button>
                            )}
                            {hasJudgeRole && !isPrimaryJudge && (
                              <button
                                type="button"
                                className="studio-make-primary-btn judge-primary-btn"
                                onClick={() => handleSetPrimaryModel("judge", m.full_id)}
                                title="Set as Primary Audit Judge"
                              >
                                ⭐ Set Primary Judge
                              </button>
                            )}
                            {hasBreakerRole && !isPrimaryBreaker && (
                              <button
                                type="button"
                                className="studio-make-primary-btn breaker-primary-btn"
                                onClick={() => handleSetPrimaryModel("breaker", m.full_id)}
                                title="Set as Primary Circuit Breaker"
                              >
                                ⭐ Set Primary Breaker
                              </button>
                            )}

                            <span className="studio-latency-badge">⚡ {m.latency || "—"}</span>
                          </div>
                        </div>

                        <div className="studio-model-actions">
                          {/* Chain reorder buttons */}
                          <div className="chain-order-buttons">
                            <button
                              type="button"
                              className="order-btn"
                              onClick={() => handleMoveModelInChain(m.full_id, (m.roles || ["generation"])[0], "up")}
                              title="Move up in fallback chain"
                            >
                              ▲
                            </button>
                            <button
                              type="button"
                              className="order-btn"
                              onClick={() => handleMoveModelInChain(m.full_id, (m.roles || ["generation"])[0], "down")}
                              title="Move down in fallback chain"
                            >
                              ▼
                            </button>
                          </div>

                          <button
                            type="button"
                            className="studio-delete-btn"
                            onClick={() => handleDeleteCustomModel(m.full_id)}
                            title="Remove model from orchestrator"
                          >
                            🗑️
                          </button>
                          <button
                            className={`studio-toggle-switch ${m.active ? "on" : "off"}`}
                            onClick={() => onToggleModel && onToggleModel(m.full_id)}
                            title={m.active ? "Click to deactivate model" : "Click to activate model"}
                          >
                            <span className="switch-thumb" />
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              TAB 2: Add Provider & Import Models via URL + API Key
             ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === "add_provider" && (
            <div className="studio-add-pane">
              <div className="studio-section-banner">
                <div>
                  <h4>Connect Provider & Auto-Import Models</h4>
                  <p>
                    Enter your provider API base URL and key. Calienne will probe the endpoint, list all models, and securely save the credentials in the OS Keyring.
                  </p>
                </div>
              </div>

              {/* Provider Connection Form */}
              <form className="studio-form" onSubmit={handleDiscoverModels}>
                {/* Presets Bar */}
                <div className="studio-presets-row">
                  <span className="presets-label">Quick Presets:</span>
                  <div className="presets-btn-group">
                    {PROVIDER_PRESETS.map((p) => (
                      <button
                        key={p.name}
                        type="button"
                        className="preset-pill-btn"
                        onClick={() => {
                          setProviderName(p.name);
                          setProviderUrl(p.url);
                          setProviderMsg({ type: "info", text: `Selected ${p.name}: ${p.hint}` });
                        }}
                      >
                        <span>{p.icon}</span> {p.name}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="studio-form-grid">
                  <div className="studio-form-group">
                    <label>Provider Name</label>
                    <input
                      type="text"
                      placeholder="e.g. My Local Ollama, DeepSeek API, Together AI"
                      value={providerName}
                      onChange={(e) => setProviderName(e.target.value)}
                      required
                    />
                    <small>Friendly label shown throughout the interface.</small>
                  </div>

                  <div className="studio-form-group">
                    <label>API Base URL / Link (OpenAI-compatible)</label>
                    <input
                      type="text"
                      placeholder="e.g. http://localhost:11434/v1 or https://api.deepseek.com/v1"
                      value={providerUrl}
                      onChange={(e) => setProviderUrl(e.target.value)}
                      required
                    />
                    <small>The /v1 or base URL of the model inference service.</small>
                  </div>

                  <div className="studio-form-group full-width">
                    <label>API Key (Optional for local Ollama/vLLM)</label>
                    <div className="vault-input-wrapper">
                      <input
                        type={showProviderKey ? "text" : "password"}
                        placeholder="sk-... (Leave blank if running unauthenticated local LLM)"
                        value={providerKey}
                        onChange={(e) => setProviderKey(e.target.value)}
                      />
                      <button
                        type="button"
                        className="vault-eye-btn"
                        onClick={() => setShowProviderKey((v) => !v)}
                        title="Toggle visibility"
                      >
                        {showProviderKey ? "🙈" : "👁️"}
                      </button>
                    </div>
                    <small>🔒 Protected by OS Keyring (Windows Credential Manager / Keychain). Zero plaintext disk storage.</small>
                  </div>
                </div>

                <div className="studio-form-actions">
                  <button type="submit" className="studio-primary-btn" disabled={fetchingModels || !providerUrl.trim()}>
                    {fetchingModels ? "🔄 Probing Provider & Fetching Models..." : "🔍 Fetch & Discover Models"}
                  </button>
                </div>
              </form>

              {providerMsg && (
                <div className={`studio-alert alert-${providerMsg.type === "info" ? "info" : providerMsg.type}`}>
                  {providerMsg.text}
                </div>
              )}

              {/* ── Discovered Models Import Section ── */}
              {discoveredModels.length > 0 && (
                <div className="studio-discovered-section">
                  <div className="discovered-header">
                    <div>
                      <h3 className="discovered-title">Available Models ({discoveredModels.length})</h3>
                      <p className="discovered-subtitle">
                        Select the models to import and assign their default orchestrator roles.
                      </p>
                    </div>
                    <div className="discovered-actions">
                      <button type="button" className="action-small-btn" onClick={handleSelectAll}>
                        Select All
                      </button>
                      <button type="button" className="action-small-btn" onClick={handleDeselectAll}>
                        Clear Selection
                      </button>
                      <span className="selection-count-badge">
                        {selectedModelIds.size} of {discoveredModels.length} selected
                      </span>
                    </div>
                  </div>

                  {/* Batch Role Selector & Search */}
                  <div className="discovered-controls-row">
                    <div className="discovered-search-box">
                      <span>🔎</span>
                      <input
                        type="text"
                        placeholder="Search discovered models..."
                        value={modelSearchTerm}
                        onChange={(e) => setModelSearchTerm(e.target.value)}
                      />
                    </div>

                    <div className="default-roles-selector">
                      <span className="roles-label">Default Import Roles:</span>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={defaultImportRoles.generation}
                          onChange={(e) =>
                            setDefaultImportRoles((p) => ({ ...p, generation: e.target.checked }))
                          }
                        />
                        <span>🦾 Generation</span>
                      </label>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={defaultImportRoles.judge}
                          onChange={(e) =>
                            setDefaultImportRoles((p) => ({ ...p, judge: e.target.checked }))
                          }
                        />
                        <span>⚡ Judge</span>
                      </label>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={defaultImportRoles.breaker}
                          onChange={(e) =>
                            setDefaultImportRoles((p) => ({ ...p, breaker: e.target.checked }))
                          }
                        />
                        <span>🛡️ Breaker</span>
                      </label>
                    </div>
                  </div>

                  {/* Discovered Models Checklist */}
                  <div className="discovered-models-grid">
                    {filteredDiscoveredModels.map((m) => {
                      const isSelected = selectedModelIds.has(m.id);
                      const baseRoles = Object.entries(defaultImportRoles).filter(([, v]) => v).map(([k]) => k);
                      const activeRoles = modelRoleOverrides[m.id] || (baseRoles.length > 0 ? baseRoles : ["generation"]);

                      return (
                        <div
                          key={m.id}
                          className={`discovered-model-card ${isSelected ? "selected" : ""}`}
                          onClick={() => toggleModelSelect(m.id)}
                        >
                          <div className="model-select-checkbox">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => {}} // Handled by card click
                            />
                          </div>
                          <div className="discovered-model-details">
                            <div className="discovered-model-name-row">
                              <span className="discovered-model-name">{m.name || m.id}</span>
                              {m.context_length && (
                                <span className="ctx-badge">{Math.round(m.context_length / 1024)}k ctx</span>
                              )}
                            </div>
                            <div className="discovered-model-id">{m.id}</div>
                            {m.description && <div className="discovered-model-desc">{m.description}</div>}

                            {isSelected && (
                              <div
                                className="discovered-role-chips"
                                onClick={(e) => e.stopPropagation()} // Prevent card deselect
                              >
                                <span className="chips-sublabel">Roles:</span>
                                <button
                                  type="button"
                                  className={`mini-role-btn ${activeRoles.includes("generation") ? "active-gen" : ""}`}
                                  onClick={() => handleModelRoleToggle(m.id, "generation")}
                                >
                                  🦾 Generation
                                </button>
                                <button
                                  type="button"
                                  className={`mini-role-btn ${activeRoles.includes("judge") ? "active-judge" : ""}`}
                                  onClick={() => handleModelRoleToggle(m.id, "judge")}
                                >
                                  ⚡ Judge
                                </button>
                                <button
                                  type="button"
                                  className={`mini-role-btn ${activeRoles.includes("breaker") ? "active-breaker" : ""}`}
                                  onClick={() => handleModelRoleToggle(m.id, "breaker")}
                                >
                                  🛡️ Breaker
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Final Import Button */}
                  <div className="discovered-submit-bar">
                    <button
                      type="button"
                      className="studio-primary-btn import-confirm-btn"
                      disabled={savingProvider || selectedModelIds.size === 0}
                      onClick={handleSaveAndImport}
                    >
                      {savingProvider
                        ? "🔒 Storing Key in OS Keyring & Registering Models..."
                        : `🔒 Save Provider & Import ${selectedModelIds.size} Selected Model(s)`}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              TAB 3: Configured Custom Providers
             ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === "providers" && (
            <div className="studio-providers-pane">
              <div className="studio-section-banner">
                <div>
                  <h4>Registered Custom & Gateway Providers</h4>
                  <p>Manage endpoints, view Keyring security status, and re-discover models.</p>
                </div>
                <button
                  className="studio-refresh-btn"
                  onClick={() => setActiveTab("add_provider")}
                >
                  ➕ Add New Provider
                </button>
              </div>

              {loadingProviders ? (
                <div className="studio-loading">Loading custom providers...</div>
              ) : customProviders.length === 0 ? (
                <div className="studio-empty-state">
                  No custom providers registered yet. Click <strong>"Add Provider & Import"</strong> to connect your first Ollama, DeepSeek, Together, or OpenAI-compatible endpoint.
                </div>
              ) : (
                <div className="studio-custom-providers-grid">
                  {customProviders.map((prov) => (
                    <div key={prov.id} className="custom-provider-card">
                      <div className="provider-card-header">
                        <div>
                          <span className="provider-name-text">{prov.name}</span>
                          <span className="provider-slug-badge">{prov.id}</span>
                        </div>
                        <div className="provider-header-actions">
                          <span className="keyring-lock-badge">
                            {prov.has_api_key ? "🔒 Keyring Protected" : "🔓 No Auth (Local)"}
                          </span>
                          <button
                            type="button"
                            className="studio-delete-btn"
                            onClick={() => handleDeleteProvider(prov.id)}
                            title="Delete provider and purge keyring credentials"
                          >
                            🗑️
                          </button>
                        </div>
                      </div>

                      <div className="provider-url-row">
                        <span className="url-label">Endpoint:</span>
                        <code className="url-code">{prov.base_url}</code>
                      </div>

                      <div className="provider-models-summary">
                        <span className="summary-title">Imported Models ({prov.models?.length || 0}):</span>
                        <div className="provider-models-tags">
                          {(prov.models || []).map((m) => (
                            <span key={m.full_id} className="imported-model-tag">
                              {m.name || m.id}
                              <span className="tag-roles">
                                {(m.roles || []).map((r) => r[0].toUpperCase()).join("/")}
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="provider-card-footer">
                        <button
                          type="button"
                          className="action-small-btn"
                          onClick={() => {
                            setProviderName(prov.name);
                            setProviderUrl(prov.base_url);
                            setActiveTab("add_provider");
                            handleDiscoverModels();
                          }}
                        >
                          🔄 Re-discover / Import More Models
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              TAB 4: Secure API Key Vault (Built-in provider accounts)
             ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === "vault" && (
            <div className="studio-vault-pane">
              <div className="studio-security-banner">
                <div className="security-icon">🛡️</div>
                <div className="security-text">
                  <h4>Zero Plaintext Leakage Architecture</h4>
                  <p>
                    Credentials submitted here are stored strictly inside the OS-native credential store (Windows Credential Manager / Keychain / Secret Service) and running memory enclave. No keys are written to <code>.env</code> or plaintext files.
                  </p>
                </div>
              </div>

              {loadingVault ? (
                <div className="studio-loading">Loading Secure Key Vault...</div>
              ) : (
                <div className="studio-vault-grid">
                  {vaultProviders.map((p) => {
                    const account = p.account;
                    const isConfigured = p.configured;
                    const inputVal = keyInputs[account] || "";
                    const isVisible = showKey[account];
                    const isSaving = savingKey[account];
                    const msg = vaultMsg[account];

                    return (
                      <div key={account} className="studio-vault-card">
                        <div className="vault-card-header">
                          <div>
                            <span className="vault-provider-name">{p.name}</span>
                            <span className="vault-account-id">{account}</span>
                          </div>
                          <span className={`vault-status-badge ${isConfigured ? "configured" : "missing"}`}>
                            {isConfigured ? `🔒 ${p.masked}` : "⚠️ Not Configured"}
                          </span>
                        </div>

                        <p className="vault-provider-desc">{p.description}</p>

                        <div className="vault-input-row">
                          <div className="vault-input-wrapper">
                            <input
                              type={isVisible ? "text" : "password"}
                              placeholder={isConfigured ? "Enter new API key to replace..." : "Paste API key (e.g. sk-or-v1-...)"}
                              value={inputVal}
                              onChange={(e) =>
                                setKeyInputs((prev) => ({ ...prev, [account]: e.target.value }))
                              }
                            />
                            <button
                              type="button"
                              className="vault-eye-btn"
                              onClick={() =>
                                setShowKey((prev) => ({ ...prev, [account]: !prev[account] }))
                              }
                              title="Toggle Key Visibility"
                            >
                              {isVisible ? "🙈" : "👁️"}
                            </button>
                          </div>
                          <button
                            type="button"
                            className="vault-save-btn"
                            disabled={isSaving || !inputVal.trim()}
                            onClick={() => handleSaveVaultKey(account)}
                          >
                            {isSaving ? "Saving..." : "Save Secret"}
                          </button>
                        </div>

                        {msg && (
                          <div className={`vault-msg msg-${msg.type}`}>
                            {msg.text}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );

  if (inline) {
    return <div className="studio-inline-wrapper">{cardContent}</div>;
  }

  return (
    <div className="studio-modal-backdrop" onMouseDown={onClose}>
      {cardContent}
    </div>
  );
}
