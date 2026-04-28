"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  createBusiness,
  createCampaignForBusiness,
  createChatSession,
  fetchBackendHealth,
  listBusinesses,
  listCampaignsForBusiness,
  postChatMessage,
  syncYamlData,
  type BusinessRecord,
  type CampaignRecord,
  type ChatHistoryItem,
  type HealthResponse,
} from "../lib/api";

export default function HomePage() {
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [businesses, setBusinesses] = useState<BusinessRecord[]>([]);
  const [selectedBusinessId, setSelectedBusinessId] = useState<number | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignRecord[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatHistoryItem[]>([]);
  const [chatMessage, setChatMessage] = useState("");
  const [chatStatus, setChatStatus] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [businessForm, setBusinessForm] = useState({
    legal_name: "",
    display_name: "",
    timezone: "America/New_York",
  });
  const [campaignForm, setCampaignForm] = useState({
    campaign_name: "",
    campaign_key: "",
    title: "",
    objective: "",
  });

  useEffect(() => {
    let active = true;
    async function loadInitialData() {
      try {
        const items = await listBusinesses();
        if (!active) return;
        setBusinesses(items);
        setSelectedBusinessId(items[0]?.id ?? null);
      } catch (caught) {
        if (!active) return;
        const message = caught instanceof Error ? caught.message : "Failed to load businesses";
        setError(message);
      }
    }

    void loadInitialData();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    if (selectedBusinessId == null) {
      setCampaigns([]);
      setSelectedCampaignId(null);
      return;
    }

    async function loadCampaigns() {
      try {
        const items = await listCampaignsForBusiness(selectedBusinessId);
        if (!active) return;
        setCampaigns(items);
        setSelectedCampaignId(items[0]?.id ?? null);
      } catch (caught) {
        if (!active) return;
        const message = caught instanceof Error ? caught.message : "Failed to load campaigns";
        setError(message);
      }
    }

    void loadCampaigns();
    return () => {
      active = false;
    };
  }, [selectedBusinessId]);

  useEffect(() => {
    let active = true;
    if (selectedCampaignId == null) {
      setChatSessionId(null);
      setChatHistory([]);
      return;
    }

    async function startSession() {
      try {
        const payload = await createChatSession();
        if (!active) return;
        setChatSessionId(payload.session_id);
        setChatHistory([]);
        setChatStatus(null);
      } catch (caught) {
        if (!active) return;
        const message = caught instanceof Error ? caught.message : "Failed to create chat session";
        setChatStatus(message);
      }
    }

    void startSession();
    return () => {
      active = false;
    };
  }, [selectedCampaignId]);

  async function checkBackend(): Promise<void> {
    setLoading(true);
    setError(null);

    try {
      const payload = await fetchBackendHealth();
      setHealth(payload);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Unknown error";
      setError(message);
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleBusinessCreate(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    try {
      const created = await createBusiness(businessForm);
      const updatedBusinesses = [...businesses, created].sort((a, b) => a.display_name.localeCompare(b.display_name));
      setBusinesses(updatedBusinesses);
      setSelectedBusinessId(created.id);
      setBusinessForm({
        legal_name: "",
        display_name: "",
        timezone: "America/New_York",
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to create business";
      setError(message);
    }
  }

  async function handleCampaignCreate(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (selectedBusinessId == null) {
      setError("Select a business before creating a campaign");
      return;
    }

    setError(null);
    try {
      const created = await createCampaignForBusiness(selectedBusinessId, {
        campaign_name: campaignForm.campaign_name,
        campaign_key: campaignForm.campaign_key || undefined,
        title: campaignForm.title,
        objective: campaignForm.objective || undefined,
      });
      const updatedCampaigns = [...campaigns, created].sort((a, b) => a.campaign_name.localeCompare(b.campaign_name));
      setCampaigns(updatedCampaigns);
      setSelectedCampaignId(created.id);
      setCampaignForm({
        campaign_name: "",
        campaign_key: "",
        title: "",
        objective: "",
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to create campaign";
      setError(message);
    }
  }

  async function handleChatSend(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (chatSessionId == null || selectedCampaignId == null) {
      setChatStatus("Select a campaign to open chat editing.");
      return;
    }
    if (chatMessage.trim() === "") {
      return;
    }

    setChatStatus(null);
    try {
      const payload = await postChatMessage(chatSessionId, selectedCampaignId, chatMessage.trim());
      setChatHistory(payload.history);
      setChatMessage("");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to send chat edit";
      setChatStatus(message);
    }
  }

  async function handleSyncNow(): Promise<void> {
    try {
      const payload = await syncYamlData();
      setSyncStatus(
        `Synced ${payload.businesses_synced} businesses and ${payload.campaigns_synced} campaigns from ${payload.data_dir}.`
      );
      const refreshedBusinesses = await listBusinesses();
      setBusinesses(refreshedBusinesses);
      if (selectedBusinessId == null && refreshedBusinesses.length > 0) {
        setSelectedBusinessId(refreshedBusinesses[0].id);
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Sync failed";
      setSyncStatus(`Sync failed: ${message}`);
    }
  }

  return (
    <main>
      <div className="page-header">
        <div>
          <h1>GPMPE</h1>
          <p>General Purpose Marketing Promotions Engine</p>
        </div>
        <Link className="text-link" href="/data-manager">
          Open GPMPE Data Manager
        </Link>
      </div>

      <section className="card">
        <h2>Backend Health Check</h2>
        <p>
          This baseline frontend shell includes a simple API client. Use the button below to test the
          backend <code>/health</code> endpoint.
        </p>

        <button type="button" onClick={checkBackend} disabled={loading}>
          {loading ? "Checking..." : "Check Backend"}
        </button>

        {health ? (
          <p>
            Connected. Status: <strong>{health.status}</strong>, DB: <strong>{health.database}</strong>
          </p>
        ) : null}

        {error ? <p>Failed to connect: {error}</p> : null}

        <small>
          API base URL: <code>{process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}</code>
        </small>
      </section>

      <section className="card section-gap">
        <h2>Business Profile Management</h2>
        <form className="grid-form" onSubmit={handleBusinessCreate}>
          <label className="stacked-label" htmlFor="legal-name">
            <span>Legal name</span>
            <input
              id="legal-name"
              value={businessForm.legal_name}
              onChange={(event) => setBusinessForm((prev) => ({ ...prev, legal_name: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="display-name">
            <span>Display name</span>
            <input
              id="display-name"
              value={businessForm.display_name}
              onChange={(event) => setBusinessForm((prev) => ({ ...prev, display_name: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="timezone">
            <span>Timezone</span>
            <input
              id="timezone"
              value={businessForm.timezone}
              onChange={(event) => setBusinessForm((prev) => ({ ...prev, timezone: event.target.value }))}
              required
            />
          </label>
          <button type="submit">Create Business</button>
        </form>

        <label className="stacked-label" htmlFor="business-select">
          <span>Active business</span>
          <select
            id="business-select"
            value={selectedBusinessId ?? ""}
            onChange={(event) => setSelectedBusinessId(Number(event.target.value))}
          >
            {businesses.map((business) => (
              <option key={business.id} value={business.id}>
                {business.display_name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="card section-gap">
        <h2>Campaign Builder</h2>
        <form className="grid-form" onSubmit={handleCampaignCreate}>
          <label className="stacked-label" htmlFor="campaign-name">
            <span>Campaign name</span>
            <input
              id="campaign-name"
              value={campaignForm.campaign_name}
              onChange={(event) => setCampaignForm((prev) => ({ ...prev, campaign_name: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="campaign-key">
            <span>Secondary key (optional)</span>
            <input
              id="campaign-key"
              placeholder="2026"
              value={campaignForm.campaign_key}
              onChange={(event) => setCampaignForm((prev) => ({ ...prev, campaign_key: event.target.value }))}
            />
          </label>
          <label className="stacked-label" htmlFor="campaign-title">
            <span>Title</span>
            <input
              id="campaign-title"
              value={campaignForm.title}
              onChange={(event) => setCampaignForm((prev) => ({ ...prev, title: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="campaign-objective">
            <span>Objective (optional)</span>
            <input
              id="campaign-objective"
              value={campaignForm.objective}
              onChange={(event) => setCampaignForm((prev) => ({ ...prev, objective: event.target.value }))}
            />
          </label>
          <button type="submit">Create Campaign</button>
        </form>

        <label className="stacked-label" htmlFor="campaign-select">
          <span>Active campaign</span>
          <select
            id="campaign-select"
            value={selectedCampaignId ?? ""}
            onChange={(event) => setSelectedCampaignId(Number(event.target.value))}
          >
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.campaign_name}
                {campaign.campaign_key ? ` (${campaign.campaign_key})` : ""}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="card section-gap">
        <h2>Chat Campaign Editing</h2>
        <p>Use commands like set title to Weekend Blowout, set status to active, or set brand primary_color to #112233.</p>
        <form className="stacked-label" onSubmit={handleChatSend}>
          <span>Edit command</span>
          <input
            value={chatMessage}
            onChange={(event) => setChatMessage(event.target.value)}
            placeholder="set title to Memorial Day Mega Sale"
          />
          <button type="submit">Send Edit</button>
        </form>
        {chatStatus ? <p className="error-text">{chatStatus}</p> : null}
        {chatHistory.length > 0 ? (
          <ul className="chat-history">
            {chatHistory.map((item, index) => (
              <li key={`${item.role}-${index}`}>
                <strong>{item.role}:</strong> {item.content}
              </li>
            ))}
          </ul>
        ) : (
          <p>No chat edits yet.</p>
        )}
      </section>

      <section className="card section-gap">
        <h2>YAML Sync Controls</h2>
        <button type="button" onClick={() => void handleSyncNow()}>
          Sync From Data Directory
        </button>
        {syncStatus ? <p>{syncStatus}</p> : null}
      </section>

      {error ? <p className="error-text">{error}</p> : null}
    </main>
  );
}
