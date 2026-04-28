"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  artifactDownloadUrl,
  createBusiness,
  createCampaignForBusiness,
  createChatSession,
  fetchArtifacts,
  fetchBackendHealth,
  listBusinesses,
  listCampaignsForBusiness,
  lookupCampaigns,
  postChatMessage,
  renderArtifact,
  syncYamlData,
  updateBusiness,
  type ArtifactItem,
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
  const [collisionMatches, setCollisionMatches] = useState<CampaignRecord[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatHistoryItem[]>([]);
  const [chatMessage, setChatMessage] = useState("");
  const [chatStatus, setChatStatus] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [rendering, setRendering] = useState(false);
  const [renderStatus, setRenderStatus] = useState<string | null>(null);
  const [clonePreviewPrompt, setClonePreviewPrompt] = useState<{
    campaignId: number;
    campaignName: string;
  } | null>(null);
  const [latestCloneArtifact, setLatestCloneArtifact] = useState<{
    artifactId: number;
    campaignId: number;
  } | null>(null);
  const [businessForm, setBusinessForm] = useState({
    legal_name: "",
    display_name: "",
    timezone: "America/New_York",
  });
  const [businessEditForm, setBusinessEditForm] = useState({
    legal_name: "",
    display_name: "",
    timezone: "America/New_York",
    is_active: true,
  });
  const [campaignForm, setCampaignForm] = useState({
    campaign_name: "",
    campaign_key: "",
    title: "",
    objective: "",
  });

  async function handleClonePreviewChoice(shouldView: boolean): Promise<void> {
    const pending = clonePreviewPrompt;
    if (pending == null) {
      return;
    }
    setClonePreviewPrompt(null);

    if (!shouldView) {
      setChatStatus(
        `Campaign '${pending.campaignName}' is active. Continue editing it with the chatbot below.`
      );
      return;
    }

    try {
      setRendering(true);
      setRenderStatus(null);
      const artifact = await renderArtifact(pending.campaignId, "flyer");
      const items = await fetchArtifacts(pending.campaignId);
      setArtifacts(items);
      setLatestCloneArtifact({ artifactId: artifact.id, campaignId: pending.campaignId });
      setRenderStatus("Flyer generated successfully.");
      window.open(artifactDownloadUrl(artifact.id), "_blank", "noopener,noreferrer");
      setChatStatus(
        `Campaign '${pending.campaignName}' opened. Continue editing it with the chatbot below.`
      );
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Artifact generation failed";
      setRenderStatus(`Artifact generation failed: ${message}`);
      setChatStatus(
        `Campaign '${pending.campaignName}' is active, but opening the PDF failed. You can still continue editing.`
      );
    } finally {
      setRendering(false);
    }
  }

  function handleOpenLatestClonePdf(): void {
    if (latestCloneArtifact == null) {
      return;
    }
    window.open(
      artifactDownloadUrl(latestCloneArtifact.artifactId),
      "_blank",
      "noopener,noreferrer"
    );
  }

  function parseSelectedId(value: string): number | null {
    if (value.trim() === "") {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

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
    const selected = businesses.find((item) => item.id === selectedBusinessId);
    if (selected == null) {
      setBusinessEditForm({
        legal_name: "",
        display_name: "",
        timezone: "America/New_York",
        is_active: true,
      });
      return;
    }
    setBusinessEditForm({
      legal_name: selected.legal_name,
      display_name: selected.display_name,
      timezone: selected.timezone,
      is_active: selected.is_active,
    });
  }, [businesses, selectedBusinessId]);

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

  useEffect(() => {
    let active = true;
    if (selectedCampaignId == null) {
      setArtifacts([]);
      return;
    }

    async function loadArtifacts() {
      try {
        const items = await fetchArtifacts(selectedCampaignId);
        if (!active) return;
        setArtifacts(items);
      } catch {
        if (!active) return;
        setArtifacts([]);
      }
    }

    void loadArtifacts();
    return () => {
      active = false;
    };
  }, [selectedCampaignId]);

  async function refreshCampaignsForBusiness(businessId: number): Promise<void> {
    const items = await listCampaignsForBusiness(businessId);
    setCampaigns(items);
    setSelectedCampaignId(items[0]?.id ?? null);
  }

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

  async function handleBusinessUpdate(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (selectedBusinessId == null) {
      setError("Select a business before updating");
      return;
    }

    setError(null);
    try {
      const updated = await updateBusiness(selectedBusinessId, businessEditForm);
      const nextBusinesses = businesses.map((item) => (item.id === updated.id ? updated : item));
      setBusinesses(nextBusinesses);
      setBusinessEditForm({
        legal_name: updated.legal_name,
        display_name: updated.display_name,
        timezone: updated.timezone,
        is_active: updated.is_active,
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to update business";
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
      if (campaignForm.campaign_key.trim() === "") {
        const lookup = await lookupCampaigns(selectedBusinessId, campaignForm.campaign_name.trim());
        if (lookup.matches.length > 0) {
          setCollisionMatches(lookup.matches);
          setError("Campaign name already exists. Select an existing campaign or provide a secondary key.");
          return;
        }
      }

      const created = await createCampaignForBusiness(selectedBusinessId, {
        campaign_name: campaignForm.campaign_name,
        campaign_key: campaignForm.campaign_key || undefined,
        title: campaignForm.title,
        objective: campaignForm.objective || undefined,
      });
      const updatedCampaigns = [...campaigns, created].sort((a, b) => a.campaign_name.localeCompare(b.campaign_name));
      setCampaigns(updatedCampaigns);
      setSelectedCampaignId(created.id);
      setCollisionMatches([]);
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
    // Clone commands don't require a campaign to be selected, but edits do.
    const isCloneAttempt = /clon(?:e|ing)/i.test(chatMessage);
    if (chatSessionId == null || (!isCloneAttempt && selectedCampaignId == null)) {
      setChatStatus("Select a campaign to open chat editing, or use a clone command to create one.");
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

      // If this was a clone command, refresh the campaign list and switch to the new campaign.
      const result = payload.result as Record<string, unknown>;
      if (result.target === "clone") {
        const newCampaignId = typeof result.new_campaign_id === "number" ? result.new_campaign_id : null;
        const newBusinessId = typeof result.new_business_id === "number" ? result.new_business_id : null;
        // Refresh business list in case business changed, then refresh campaigns.
        const refreshedBusinesses = await listBusinesses();
        setBusinesses(refreshedBusinesses);
        const targetBusinessId = newBusinessId ?? selectedBusinessId;
        if (targetBusinessId != null) {
          setSelectedBusinessId(targetBusinessId);
          const refreshedCampaigns = await listCampaignsForBusiness(targetBusinessId);
          setCampaigns(refreshedCampaigns);
          setSelectedCampaignId(newCampaignId ?? (refreshedCampaigns[0]?.id ?? null));
        }

        const activatedCampaignId = newCampaignId ?? null;
        if (activatedCampaignId != null) {
          const campaignName = String(result.new_campaign_name ?? "new-campaign");
          setLatestCloneArtifact(null);
          setClonePreviewPrompt({ campaignId: activatedCampaignId, campaignName });
          setChatStatus(
            `Campaign '${campaignName}' created and active. Do you want to view the new promotion PDF now?`
          );
        } else {
          setChatStatus(
            `Campaign '${String(result.new_campaign_name)}' created. It is now the active campaign — continue editing below.`
          );
        }
      }
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
      if (selectedBusinessId != null) {
        await refreshCampaignsForBusiness(selectedBusinessId);
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Sync failed";
      setSyncStatus(`Sync failed: ${message}`);
    }
  }

  async function handleGenerateArtifact(artifactType: "flyer" | "poster"): Promise<void> {
    if (selectedCampaignId == null) {
      setRenderStatus("Select a campaign before generating artifacts.");
      return;
    }

    setRendering(true);
    setRenderStatus(null);
    try {
      await renderArtifact(selectedCampaignId, artifactType);
      const items = await fetchArtifacts(selectedCampaignId);
      setArtifacts(items);
      setRenderStatus(`${artifactType} generated successfully.`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Artifact generation failed";
      setRenderStatus(`Artifact generation failed: ${message}`);
    } finally {
      setRendering(false);
    }
  }

  function openExistingCampaign(campaignId: number): void {
    setSelectedCampaignId(campaignId);
    setCollisionMatches([]);
    setError(null);
  }

  const canOpenLatestClonePdf =
    latestCloneArtifact != null && latestCloneArtifact.campaignId === selectedCampaignId;

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
            onChange={(event) => setSelectedBusinessId(parseSelectedId(event.target.value))}
          >
            {businesses.map((business) => (
              <option key={business.id} value={business.id}>
                {business.display_name}
              </option>
            ))}
          </select>
        </label>

        <form className="grid-form" onSubmit={handleBusinessUpdate}>
          <label className="stacked-label" htmlFor="edit-legal-name">
            <span>Edit legal name</span>
            <input
              id="edit-legal-name"
              value={businessEditForm.legal_name}
              onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, legal_name: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="edit-display-name">
            <span>Edit display name</span>
            <input
              id="edit-display-name"
              value={businessEditForm.display_name}
              onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, display_name: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="edit-timezone">
            <span>Edit timezone</span>
            <input
              id="edit-timezone"
              value={businessEditForm.timezone}
              onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, timezone: event.target.value }))}
              required
            />
          </label>
          <label className="stacked-label" htmlFor="edit-active">
            <span>Active</span>
            <input
              id="edit-active"
              type="checkbox"
              checked={businessEditForm.is_active}
              onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, is_active: event.target.checked }))}
            />
          </label>
          <button type="submit">Update Business</button>
        </form>
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

        {collisionMatches.length > 0 ? (
          <div className="collision-box">
            <p>Existing campaigns with this name:</p>
            <ul className="chat-history">
              {collisionMatches.map((match) => (
                <li key={match.id}>
                  <strong>{match.title}</strong>
                  {match.campaign_key ? ` (${match.campaign_key})` : ""}
                  <button type="button" onClick={() => openExistingCampaign(match.id)}>
                    Open Existing
                  </button>
                </li>
              ))}
            </ul>
            <p>Add a secondary key above if you want to create a new campaign with the same name.</p>
          </div>
        ) : null}

        <label className="stacked-label" htmlFor="campaign-select">
          <span>Active campaign</span>
          <select
            id="campaign-select"
            value={selectedCampaignId ?? ""}
            onChange={(event) => setSelectedCampaignId(parseSelectedId(event.target.value))}
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
        <p>
          Edit commands: <code>set title to Weekend Blowout</code>, <code>set status to active</code>, <code>set brand primary_color to #112233</code>.
          <br />
          Clone commands: <code>clone summer-sale and rename it to fall-clearance</code> — creates a new campaign and makes it active.
        </p>
        <form className="stacked-label" onSubmit={handleChatSend}>
          <span>Edit command</span>
          <input
            value={chatMessage}
            onChange={(event) => setChatMessage(event.target.value)}
            placeholder="set title to Memorial Day Mega Sale"
          />
          <button type="submit">Send Edit</button>
        </form>
        {chatStatus ? (
          <div className="chat-status-row">
            <p className="save-status">{chatStatus}</p>
            {canOpenLatestClonePdf ? (
              <button type="button" className="ghost-button" onClick={handleOpenLatestClonePdf}>
                Open Latest PDF
              </button>
            ) : null}
          </div>
        ) : null}
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

      <section className="card section-gap">
        <h2>Artifact Preview and Download</h2>
        <div className="artifact-controls">
          <button type="button" onClick={() => void handleGenerateArtifact("flyer")} disabled={rendering}>
            {rendering ? "Generating..." : "Generate Flyer"}
          </button>
          <button type="button" onClick={() => void handleGenerateArtifact("poster")} disabled={rendering}>
            {rendering ? "Generating..." : "Generate Poster"}
          </button>
        </div>
        {renderStatus ? <p>{renderStatus}</p> : null}
        {artifacts.length > 0 ? (
          <ul className="artifact-list">
            {artifacts.map((artifact) => (
              <li key={artifact.id}>
                <span>{artifact.artifact_type}</span>
                <span className="artifact-date">{artifact.created_at ?? ""}</span>
                <a href={artifactDownloadUrl(artifact.id)} className="text-link" target="_blank" rel="noopener noreferrer">
                  Download PDF
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p>No artifacts generated for the selected campaign yet.</p>
        )}
      </section>

      {error ? <p className="error-text">{error}</p> : null}

      {clonePreviewPrompt ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="clone-preview-title">
          <div className="modal-card">
            <h3 id="clone-preview-title">View New Promotion Now?</h3>
            <p>
              Campaign <strong>{clonePreviewPrompt.campaignName}</strong> is ready. Generate and open the flyer PDF now?
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleClonePreviewChoice(false)}
                disabled={rendering}
              >
                Not Now
              </button>
              <button type="button" onClick={() => void handleClonePreviewChoice(true)} disabled={rendering}>
                {rendering ? "Generating..." : "Yes, Open PDF"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
