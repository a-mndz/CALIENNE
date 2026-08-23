import { useState, useEffect, useCallback, useRef } from "react";
import { useEscapeKey } from "../hooks/useEscapeKey.js";
import { useFocusTrap } from "../hooks/useFocusTrap.js";

export default function ModelApiStudioModal({ isOpen, onClose, models = [], onToggleModel, onRefresh }) {
  const [activeTab, setActiveTab] = useState("models");
  const [vaultProviders, setVaultProviders] = useState([]);
  const [loadingVault, setLoadingVault] = useState(false);

  // Tab 2: Custom Model form state
  const [modelId, setModelId] = useState("");
  const [role, setRole] = useState("generation");
  const [submittingModel, setSubmittingModel] = useState(false);
  const [modelMsg, setModelMsg] = useState(null);

  // Tab 3: Secure Vault form state per account
  const [keyInputs, setKeyInputs] = useState({});
  const [showKey, setShowKey] = useState({});
  const [savingKey, setSavingKey] = useState({});
  const [vaultMsg, setVaultMsg] = useState({});
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const previousFocusRef = useRef(null);

  useFocusTrap(isOpen, dialogRef);
  useEscapeKey(useCallback(() => {
    if (isOpen) onClose();
  }, [isOpen, onClose]));

  useEffect(() => {
    if (!isOpen) return;
    previousFocusRef.current = document.activeElement;
    closeRef.current?.focus();
    return () => previousFocusRef.current?.focus?.();
  }, [isOpen]);

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
      fetchVaultStatus();
    }
  }, [isOpen, fetchVaultStatus]);

  if (!isOpen) return null;

  const handleAddCustomModel = async (e) => {
    e.preventDefault();
    if (!modelId.trim()) return;
    setSubmittingModel(true);
    setModelMsg(null);
    try {
      const headers = {
        "Content-Type": "application/json",
      };
      const payload = {
        model_id: modelId.trim(),
        role,
      };
      const res = await fetch("/api/models/custom", {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setModelMsg({ type: "success", text: "Successfully registered model in orchestrator!" });
        setModelId("");
        if (onRefresh) onRefresh();
      } else {
        const err = await res.json().catch(() => ({ detail: "Failed to add model" }));
        setModelMsg({ type: "error", text: err.detail || "Failed to register model" });
      }
    } catch (err) {
      setModelMsg({ type: "error", text: err.message });
    } finally {
      setSubmittingModel(false);
    }
  };

  const handleSaveVaultKey = async (account) => {
    const secret = (keyInputs[account] || "").trim();
    if (!secret) return;

    setSavingKey((p) => ({ ...p, [account]: true }));
    setVaultMsg((p) => ({ ...p, [account]: null }));
    try {
      const headers = {
        "Content-Type": "application/json",
      };
      const res = await fetch("/api/config/vault", {
        method: "POST",
        headers,
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

  return (
    <div className="studio-modal-backdrop" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className="studio-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="studio-modal-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="studio-modal-header">
          <div>
            <div className="studio-modal-tag">⚡ AETHERIS ORCHESTRATOR</div>
            <h2 id="studio-modal-title" className="studio-modal-title">Model & API Gateway Studio</h2>
            <p className="studio-modal-subtitle">
              Configure AI pipeline models, custom gateway endpoints, and zero-leakage API key vault.
            </p>
          </div>
          <button ref={closeRef} className="studio-close-btn" onClick={onClose} aria-label="Close Studio">
            ✕
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="studio-tabs">
          <button
            className={`studio-tab-btn ${activeTab === "models" ? "active" : ""}`}
            onClick={() => setActiveTab("models")}
          >
            <span>🦾</span> Active Pipeline Models
          </button>
          <button
            className={`studio-tab-btn ${activeTab === "add" ? "active" : ""}`}
            onClick={() => setActiveTab("add")}
          >
            <span>➕</span> Add Custom Model & Gateway
          </button>
          <button
            className={`studio-tab-btn ${activeTab === "vault" ? "active" : ""}`}
            onClick={() => setActiveTab("vault")}
          >
            <span>🔒</span> Secure API Key Vault
          </button>
        </div>

        {/* Tab Contents */}
        <div className="studio-modal-body">
          {/* Tab 1: Active Pipeline Models */}
          {activeTab === "models" && (
            <div className="studio-models-pane">
              <div className="studio-section-banner">
                <div>
                  <h4>Pipeline Fallback Chain</h4>
                  <p>Models are tried in priority sequence across generation, circuit breaker, and audit judge roles.</p>
                </div>
                <button className="studio-refresh-btn" onClick={onRefresh}>
                  🔄 Refresh Status
                </button>
              </div>

              <div className="studio-models-list">
                {models.length === 0 ? (
                  <div className="studio-empty-state">No models loaded.</div>
                ) : (
                  models.map((m) => (
                    <div key={m.id} className={`studio-model-card ${m.active ? "active" : "inactive"}`}>
                      <div className="studio-model-info">
                        <div className="studio-model-top">
                          <span className="studio-model-name">{m.name}</span>
                          <span className="studio-provider-badge">{m.provider || "gateway"}</span>
                        </div>
                        <div className="studio-model-fullid">{m.full_id || m.id}</div>
                        <div className="studio-model-roles">
                          {(m.roles || ["generation"]).map((r) => (
                            <span key={r} className={`studio-role-chip role-${r}`}>
                              {r.toUpperCase()}
                            </span>
                          ))}
                          <span className="studio-latency-badge">⚡ {m.latency || "—"}</span>
                        </div>
                      </div>
                      <div className="studio-model-actions">
                        <button
                          className={`studio-toggle-switch ${m.active ? "on" : "off"}`}
                          onClick={() => onToggleModel && onToggleModel(m.full_id)}
                          title={m.active ? "Deactivate model" : "Activate model"}
                        >
                          <span className="switch-thumb" />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* Tab 2: Add Custom Model & Gateway */}
          {activeTab === "add" && (
            <div className="studio-add-pane">
              <div className="studio-section-banner">
                <div>
                  <h4>Register Custom Model Endpoint</h4>
                  <p>Connect OpenRouter, OpenAI, local Ollama/vLLM, or custom gateway instances.</p>
                </div>
              </div>

              <form className="studio-form" onSubmit={handleAddCustomModel}>
                <div className="studio-form-grid">
                  <div className="studio-form-group">
                    <label>Model Identifier (Required)</label>
                    <input
                      type="text"
                      placeholder="e.g. openrouter/anthropic/claude-3.5-sonnet"
                      value={modelId}
                      onChange={(e) => setModelId(e.target.value)}
                      required
                    />
                    <small>Full route path used by the orchestrator gateway.</small>
                  </div>

                  <div className="studio-form-group">
                    <label>Pipeline Role</label>
                    <select value={role} onChange={(e) => setRole(e.target.value)}>
                      <option value="generation">Generation (Primary synthesis & answering)</option>
                      <option value="breaker">Circuit Breaker (Fast fallback & recovery)</option>
                      <option value="judge">Audit Judge (Consensus & response auditing)</option>
                    </select>
                    <small>Assigns this model to the selected role fallback chain.</small>
                  </div>

                </div>

                {modelMsg && (
                  <div className={`studio-alert alert-${modelMsg.type}`}>
                    {modelMsg.text}
                  </div>
                )}

                <div className="studio-form-actions">
                  <button type="submit" className="studio-primary-btn" disabled={submittingModel}>
                    {submittingModel ? "Registering..." : "➕ Add to Pipeline Chain"}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Tab 3: Secure API Key Vault */}
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
    </div>
  );
}
