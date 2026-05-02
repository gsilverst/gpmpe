"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  fetchAdminAuditLogs,
  fetchRuntimeGitSettings,
  updateRuntimeGitSettings,
  type AdminAuditLog,
  type RuntimeGitSettings,
  type RuntimeGitSettingsPayload,
} from "../../lib/api";

type FormState = {
  repo_path: string;
  remote_url: string;
  remote_name: string;
  branch: string;
  user_name: string;
  user_email: string;
  push_enabled: boolean;
  credential_provider: "local" | "aws";
  credential_reference: string;
  credential_secret: string;
};

const emptyForm: FormState = {
  repo_path: "",
  remote_url: "",
  remote_name: "origin",
  branch: "HEAD",
  user_name: "",
  user_email: "",
  push_enabled: false,
  credential_provider: "local",
  credential_reference: "",
  credential_secret: "",
};

function toForm(settings: RuntimeGitSettings): FormState {
  return {
    repo_path: settings.repo_path ?? "",
    remote_url: settings.remote_url ?? "",
    remote_name: settings.remote_name,
    branch: settings.branch,
    user_name: settings.user_name ?? "",
    user_email: settings.user_email ?? "",
    push_enabled: settings.push_enabled,
    credential_provider: settings.credential_provider === "aws" ? "aws" : "local",
    credential_reference: settings.credential_reference ?? "",
    credential_secret: "",
  };
}

function clean(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export default function AdminPage() {
  const [settings, setSettings] = useState<RuntimeGitSettings | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [loadedSettings, loadedAudit] = await Promise.all([
        fetchRuntimeGitSettings(),
        fetchAdminAuditLogs(),
      ]);
      setSettings(loadedSettings);
      setForm(toForm(loadedSettings));
      setAuditLogs(loadedAudit);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load admin settings");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    setError(null);
    try {
      const payload: RuntimeGitSettingsPayload = {
        repo_path: clean(form.repo_path),
        remote_url: clean(form.remote_url),
        remote_name: form.remote_name.trim() || "origin",
        branch: form.branch.trim() || "HEAD",
        user_name: clean(form.user_name),
        user_email: clean(form.user_email),
        push_enabled: form.push_enabled,
        credential_provider: form.credential_provider,
        credential_reference: clean(form.credential_reference),
      };
      if (form.credential_secret !== "") {
        payload.credential_secret = form.credential_secret;
      }
      const updated = await updateRuntimeGitSettings(payload);
      setSettings(updated);
      setForm(toForm(updated));
      setAuditLogs(await fetchAdminAuditLogs());
      setStatus("Settings saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to save admin settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <div className="page-header">
        <div>
          <h1>Admin Settings</h1>
          <p>Runtime configuration for the business data repository and Git sync identity.</p>
        </div>
        <Link className="text-link" href="/">
          Back to home
        </Link>
      </div>

      {loading ? <p>Loading settings...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {status ? <p className="save-status">{status}</p> : null}

      <section className="card section-gap">
        <div className="section-header-row">
          <div>
            <h2>Business Data Repository</h2>
            <small>
              Secret values are write-only. Saved secrets are never returned to the browser.
            </small>
          </div>
          {settings ? (
            <small>{settings.credential_configured ? "Credential configured" : "No credential stored"}</small>
          ) : null}
        </div>

        <form onSubmit={handleSubmit} className="admin-settings-form">
          <div className="grid-form">
            <label className="stacked-label">
              <span>Repository path</span>
              <input
                value={form.repo_path}
                onChange={(event) => setForm({ ...form, repo_path: event.target.value })}
                placeholder="/app/data"
              />
            </label>
            <label className="stacked-label">
              <span>Remote URL</span>
              <input
                value={form.remote_url}
                onChange={(event) => setForm({ ...form, remote_url: event.target.value })}
                placeholder="git@github.com:org/business-data.git"
              />
            </label>
            <label className="stacked-label">
              <span>Remote name</span>
              <input
                value={form.remote_name}
                onChange={(event) => setForm({ ...form, remote_name: event.target.value })}
              />
            </label>
            <label className="stacked-label">
              <span>Branch/ref</span>
              <input
                value={form.branch}
                onChange={(event) => setForm({ ...form, branch: event.target.value })}
              />
            </label>
            <label className="stacked-label">
              <span>Git author name</span>
              <input
                value={form.user_name}
                onChange={(event) => setForm({ ...form, user_name: event.target.value })}
              />
            </label>
            <label className="stacked-label">
              <span>Git author email</span>
              <input
                value={form.user_email}
                onChange={(event) => setForm({ ...form, user_email: event.target.value })}
              />
            </label>
            <label className="stacked-label">
              <span>Credential provider</span>
              <select
                value={form.credential_provider}
                onChange={(event) =>
                  setForm({ ...form, credential_provider: event.target.value === "aws" ? "aws" : "local" })
                }
              >
                <option value="local">Local</option>
                <option value="aws">AWS Secrets Manager</option>
              </select>
            </label>
            <label className="stacked-label">
              <span>Credential reference</span>
              <input
                value={form.credential_reference}
                onChange={(event) => setForm({ ...form, credential_reference: event.target.value })}
                placeholder="gpmpe/local/git/global"
              />
            </label>
          </div>

          <label className="stacked-label">
            <span>New credential secret</span>
            <textarea
              value={form.credential_secret}
              onChange={(event) => setForm({ ...form, credential_secret: event.target.value })}
              placeholder="Paste a token or private key only when creating or rotating the credential."
            />
          </label>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.push_enabled}
              onChange={(event) => setForm({ ...form, push_enabled: event.target.checked })}
            />
            <span>Allow the application to push commits to the configured remote</span>
          </label>

          <button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save settings"}
          </button>
        </form>
      </section>

      <section className="card section-gap">
        <h2>Audit Log</h2>
        {auditLogs.length === 0 ? <p className="empty-hint">No admin changes recorded yet.</p> : null}
        <ul className="audit-list">
          {auditLogs.map((entry) => (
            <li key={entry.id}>
              <strong>{entry.action}</strong>
              <small>
                {entry.actor} · {entry.created_at ?? "unknown time"}
              </small>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
