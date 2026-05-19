"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  fetchAdminAuditLogs,
  fetchAdminAppSettings,
  fetchAdminUsers,
  fetchBusinessGitSettings,
  fetchRuntimeGitSettings,
  inviteAdminUser,
  listBusinesses,
  updateBusinessGitSettings,
  updateAdminAppSettings,
  updateRuntimeGitSettings,
  type AdminAppSettings,
  type AdminAuditLog,
  type AdminUser,
  type BusinessRecord,
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

const emptyInviteForm = {
  email: "",
  display_name: "",
  role: "regular" as "admin" | "regular",
  business_ids: [] as number[],
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
  const [businesses, setBusinesses] = useState<BusinessRecord[]>([]);
  const [selectedBusinessId, setSelectedBusinessId] = useState<string>("global");
  const [settings, setSettings] = useState<RuntimeGitSettings | null>(null);
  const [appSettings, setAppSettings] = useState<AdminAppSettings>({ default_promotion_type: "sales", updated_at: null });
  const [form, setForm] = useState<FormState>(emptyForm);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [inviteForm, setInviteForm] = useState(emptyInviteForm);
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [loadedSettings, loadedAppSettings, loadedAudit] = await Promise.all([
        fetchRuntimeGitSettings(),
        fetchAdminAppSettings(),
        fetchAdminAuditLogs(),
      ]);
      setBusinesses(await listBusinesses());
      setUsers(await fetchAdminUsers());
      setSettings(loadedSettings);
      setAppSettings(loadedAppSettings);
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

  async function handleScopeChange(value: string) {
    setSelectedBusinessId(value);
    setStatus(null);
    setError(null);
    try {
      const loadedSettings =
        value === "global" ? await fetchRuntimeGitSettings() : await fetchBusinessGitSettings(Number(value));
      setSettings(loadedSettings);
      setForm(toForm(loadedSettings));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load repository settings");
    }
  }

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
      const updated =
        selectedBusinessId === "global"
          ? await updateRuntimeGitSettings(payload)
          : await updateBusinessGitSettings(Number(selectedBusinessId), payload);
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

  async function handleAppSettingsSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    setError(null);
    try {
      const updated = await updateAdminAppSettings({
        default_promotion_type: appSettings.default_promotion_type,
      });
      setAppSettings(updated);
      setAuditLogs(await fetchAdminAuditLogs());
      setStatus("Application settings saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to save application settings");
    } finally {
      setSaving(false);
    }
  }

  async function handleInviteSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    setError(null);
    try {
      await inviteAdminUser({
        email: inviteForm.email,
        display_name: clean(inviteForm.display_name),
        role: inviteForm.role,
        business_ids: inviteForm.role === "regular" ? inviteForm.business_ids : [],
      });
      setInviteForm(emptyInviteForm);
      setUsers(await fetchAdminUsers());
      setAuditLogs(await fetchAdminAuditLogs());
      setStatus("User invitation saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to invite user");
    } finally {
      setSaving(false);
    }
  }

  function toggleInviteBusiness(businessId: number) {
    const businessIds = inviteForm.business_ids.includes(businessId)
      ? inviteForm.business_ids.filter((id) => id !== businessId)
      : [...inviteForm.business_ids, businessId];
    setInviteForm({ ...inviteForm, business_ids: businessIds });
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
            <h2>Users</h2>
            <small>Invite app users and assign business access. Cognito owns passwords and login.</small>
          </div>
        </div>

        <form onSubmit={handleInviteSubmit} className="admin-settings-form">
          <div className="grid-form">
            <label className="stacked-label">
              <span>Email</span>
              <input
                type="email"
                value={inviteForm.email}
                onChange={(event) => setInviteForm({ ...inviteForm, email: event.target.value })}
                placeholder="user@example.com"
                required
              />
            </label>
            <label className="stacked-label">
              <span>Display name</span>
              <input
                value={inviteForm.display_name}
                onChange={(event) => setInviteForm({ ...inviteForm, display_name: event.target.value })}
                placeholder="Optional"
              />
            </label>
            <label className="stacked-label">
              <span>Role</span>
              <select
                value={inviteForm.role}
                onChange={(event) =>
                  setInviteForm({
                    ...inviteForm,
                    role: event.target.value === "admin" ? "admin" : "regular",
                    business_ids: event.target.value === "admin" ? [] : inviteForm.business_ids,
                  })
                }
              >
                <option value="regular">Regular user</option>
                <option value="admin">Admin user</option>
              </select>
            </label>
          </div>

          {inviteForm.role === "regular" ? (
            <fieldset className="stacked-label">
              <span>Business access</span>
              <div className="checkbox-stack">
                {businesses.map((business) => (
                  <label key={business.id} className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={inviteForm.business_ids.includes(business.id)}
                      onChange={() => toggleInviteBusiness(business.id)}
                    />
                    <span>{business.display_name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}

          <button type="submit" disabled={saving}>
            {saving ? "Inviting..." : "Invite user"}
          </button>
        </form>

        {users.length === 0 ? <p className="empty-hint">No application users created yet.</p> : null}
        <ul className="audit-list">
          {users.map((user) => (
            <li key={user.id}>
              <strong>{user.email}</strong>
              <small>
                {user.role} · {user.status}
                {user.business_ids.length > 0 ? ` · businesses ${user.business_ids.join(", ")}` : ""}
              </small>
            </li>
          ))}
        </ul>
      </section>

      <section className="card section-gap">
        <div className="section-header-row">
          <div>
            <h2>Promotion Defaults</h2>
            <small>Choose the default promotion type used when a new promotion is created.</small>
          </div>
        </div>

        <form onSubmit={handleAppSettingsSubmit} className="admin-settings-form">
          <label className="stacked-label">
            <span>Default promotion type</span>
            <select
              value={appSettings.default_promotion_type}
              onChange={(event) =>
                setAppSettings({
                  ...appSettings,
                  default_promotion_type: event.target.value === "storybook" ? "storybook" : "sales",
                })
              }
            >
              <option value="sales">Sales</option>
              <option value="storybook">Storybook</option>
            </select>
          </label>

          <button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save promotion defaults"}
          </button>
        </form>
      </section>

      <section className="card section-gap">
        <div className="section-header-row">
          <div>
            <h2>Business Data Repository</h2>
            <small>
              Configure global defaults or business-specific Git service credentials. Secret values are write-only.
            </small>
          </div>
          {settings ? (
            <small>
              {settings.source === "business"
                ? "Business override"
                : settings.source === "global"
                  ? "Using global defaults"
                  : "Using config defaults"}
              {" · "}
              {settings.credential_configured ? "Credential configured" : "No credential stored"}
            </small>
          ) : null}
        </div>

        <label className="stacked-label">
          <span>Settings scope</span>
          <select value={selectedBusinessId} onChange={(event) => void handleScopeChange(event.target.value)}>
            <option value="global">Global defaults</option>
            {businesses.map((business) => (
              <option key={business.id} value={business.id}>
                {business.display_name}
              </option>
            ))}
          </select>
        </label>

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
              <span>Repository URL</span>
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
            <small>
              Tokens are saved to the selected secret provider and are never returned after save. Leave blank to keep
              the current token.
            </small>
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
