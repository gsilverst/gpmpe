"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  bootstrapPrimaryAdmin,
  fetchAuthStatus,
  type AuthStatus,
  type CurrentUser,
} from "../../lib/api";

export default function SetupPage() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [createdUser, setCreatedUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      setStatus(await fetchAuthStatus());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load setup status");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const user = await bootstrapPrimaryAdmin(
        {
          primary_admin_email: email,
          display_name: displayName.trim() || undefined,
        },
        setupToken
      );
      setCreatedUser(user);
      setMessage("Primary administrator created.");
      setSetupToken("");
      await loadStatus();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to create primary administrator");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <div className="page-header">
        <div>
          <h1>First-Run Setup</h1>
          <p>Hand off this deployment to the first Primary Admin user.</p>
        </div>
        <Link className="text-link" href="/">
          Back to home
        </Link>
      </div>

      {loading ? <p>Loading setup status...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {message ? <p className="save-status">{message}</p> : null}

      <section className="card section-gap">
        <div className="section-header-row">
          <div>
            <h2>Authentication</h2>
            <small>
              {status?.enabled
                ? `Enabled with ${status.mode}`
                : "Disabled for this deployment"}
            </small>
          </div>
          <small>{status ? `${status.user_count} app user${status.user_count === 1 ? "" : "s"}` : ""}</small>
        </div>

        {status && !status.enabled ? (
          <p className="empty-hint">Authentication is not enabled for this deployment.</p>
        ) : null}

        {status && status.enabled && !status.bootstrap_required ? (
          <p className="empty-hint">First-run setup is complete.</p>
        ) : null}

        {status?.bootstrap_required ? (
          <form onSubmit={handleSubmit} className="admin-settings-form">
            <div className="grid-form">
              <label className="stacked-label">
                <span>Primary Admin email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  placeholder="admin@example.com"
                />
              </label>
              <label className="stacked-label">
                <span>Display name</span>
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="Optional"
                />
              </label>
            </div>
            <label className="stacked-label">
              <span>Setup token</span>
              <input
                type="password"
                value={setupToken}
                onChange={(event) => setSetupToken(event.target.value)}
                required
                placeholder="Temporary deployment setup token"
              />
              <small>The setup token is temporary and is not stored in the application database.</small>
            </label>
            <button type="submit" disabled={saving}>
              {saving ? "Creating..." : "Create Primary Admin"}
            </button>
          </form>
        ) : null}

        {createdUser ? (
          <p className="save-status">
            Created {createdUser.email} as {createdUser.role}.
          </p>
        ) : null}
      </section>
    </main>
  );
}
