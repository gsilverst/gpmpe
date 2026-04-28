"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  artifactDownloadUrl,
  artifactPreviewUrl,
  cloneCampaignForBusiness,
  createBusiness,
  createCampaignForBusiness,
  createChatSession,
  fetchArtifacts,
  fetchBackendHealth,
  fetchStartupStatus,
  listBusinesses,
  listCampaignsForBusiness,
  lookupCampaigns,
  postChatMessage,
  renderArtifact,
  resolveStartup,
  syncYamlData,
  updateCampaignForBusiness,
  updateBusiness,
  type ArtifactItem,
  type BusinessRecord,
  type CampaignRecord,
  type ChatHistoryItem,
  type HealthResponse,
  type StartupStatusReport,
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
  const [previewArtifactId, setPreviewArtifactId] = useState<number | null>(null);
  const [previewRendering, setPreviewRendering] = useState(false);
  const [previewStatus, setPreviewStatus] = useState<string | null>(null);
  const [clonePreviewPrompt, setClonePreviewPrompt] = useState<{
    campaignId: number;
    campaignName: string;
  } | null>(null);
  const [latestCloneArtifact, setLatestCloneArtifact] = useState<{
    artifactId: number;
    campaignId: number;
  } | null>(null);
  const [reconciliationReport, setReconciliationReport] =
    useState<StartupStatusReport | null>(null);
  const [businessMode, setBusinessMode] = useState<"list" | "edit" | "create">("list");
  const [businessEditForm, setBusinessEditForm] = useState({
    legal_name: "",
    display_name: "",
    timezone: "America/New_York",
    is_active: true,
    phone: "",
    address_line1: "",
    address_line2: "",
    city: "",
    state: "",
    postal_code: "",
    country: "US",
  });
  const [campaignForm, setCampaignForm] = useState({
    campaign_name: "",
    campaign_key: "",
    title: "",
    objective: "",
  });
  const [campaignMode, setCampaignMode] = useState<"list" | "create" | "edit">("list");

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

  async function regenerateCampaignPreview(campaignId: number, reason?: string): Promise<void> {
    setPreviewRendering(true);
    setPreviewStatus(reason ? `Updating preview (${reason})...` : "Updating preview...");
    try {
      const artifact = await renderArtifact(campaignId, "flyer");
      setPreviewArtifactId(artifact.id);
      const items = await fetchArtifacts(campaignId);
      setArtifacts(items);
      setPreviewStatus("Preview updated.");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Preview generation failed";
      setPreviewStatus(`Preview generation failed: ${message}`);
    } finally {
      setPreviewRendering(false);
    }
  }

  function parseSelectedId(value: string): number | null {
    if (value.trim() === "") {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  async function handleReconciliationChoice(
    direction: "yaml_to_db" | "db_to_yaml"
  ): Promise<void> {
    try {
      await resolveStartup(direction);
      setReconciliationReport(null);
      // Reload businesses after resolution
      const items = await listBusinesses();
      setBusinesses(items);
      setSelectedBusinessId(null);
      setBusinessMode(items.length > 0 ? "list" : "create");
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Failed to resolve data conflict";
      setError(message);
    }
  }

  function pickMostRecentDirection(
    report: StartupStatusReport
  ): "yaml_to_db" | "db_to_yaml" {
    const dbTime = report.db_latest_updated_at
      ? new Date(report.db_latest_updated_at).getTime()
      : 0;
    const yamlTime = report.yaml_latest_mtime
      ? new Date(report.yaml_latest_mtime).getTime()
      : 0;
    // If DB is strictly newer, write DB state to DATA_DIR. Otherwise prefer YAML.
    return dbTime > yamlTime ? "db_to_yaml" : "yaml_to_db";
  }

  useEffect(() => {
    let active = true;
    async function loadInitialData() {
      let reconciliationNeeded = false;
      try {
        // Check for DB/DATA_DIR reconciliation before loading anything else.
        const startup = await fetchStartupStatus();
        if (!active) return;
        if (startup.reconciliation_needed && startup.report != null) {
          setReconciliationReport(startup.report);
          reconciliationNeeded = true;
        }
      } catch (caught) {
        if (!active) return;
        const message = caught instanceof Error ? caught.message : "Failed to check startup status";
        setError(message);
      }

      if (reconciliationNeeded) {
        return; // wait for the user to resolve before continuing
      }

      try {
        const items = await listBusinesses();
        if (!active) return;
        setBusinesses(items);
        setBusinessMode(items.length > 0 ? "list" : "create");
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
      setCampaignMode("list");
      return;
    }
    const businessId = selectedBusinessId;

    async function loadCampaigns() {
      try {
        const items = await listCampaignsForBusiness(businessId);
        if (!active) return;
        setCampaigns(items);
        setSelectedCampaignId(null);
        setCampaignMode("list");
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
    if (selectedCampaignId == null) {
      if (campaignMode === "edit") {
        setCampaignMode("list");
      }
      return;
    }
    const selected = campaigns.find((item) => item.id === selectedCampaignId);
    if (selected == null) {
      return;
    }
    setCampaignForm({
      campaign_name: selected.campaign_name,
      campaign_key: selected.campaign_key ?? "",
      title: selected.title,
      objective: selected.objective ?? "",
    });
  }, [campaigns, selectedCampaignId, campaignMode]);

  useEffect(() => {
    const selected = businesses.find((item) => item.id === selectedBusinessId);
    if (selected == null) {
      setBusinessEditForm({
        legal_name: "",
        display_name: "",
        timezone: "America/New_York",
        is_active: true,
        phone: "",
        address_line1: "",
        address_line2: "",
        city: "",
        state: "",
        postal_code: "",
        country: "US",
      });
      return;
    }
    setBusinessEditForm({
      legal_name: selected.legal_name,
      display_name: selected.display_name,
      timezone: selected.timezone,
      is_active: selected.is_active,
      phone: selected.phone ?? "",
      address_line1: selected.address_line1 ?? "",
      address_line2: selected.address_line2 ?? "",
      city: selected.city ?? "",
      state: selected.state ?? "",
      postal_code: selected.postal_code ?? "",
      country: selected.country ?? "US",
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
      setPreviewArtifactId(null);
      setPreviewStatus(null);
      return;
    }
    const campaignId = selectedCampaignId;

    async function loadArtifacts() {
      try {
        const items = await fetchArtifacts(campaignId);
        if (!active) return;
        setArtifacts(items);
        setPreviewArtifactId(items[0]?.id ?? null);
      } catch {
        if (!active) return;
        setArtifacts([]);
        setPreviewArtifactId(null);
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
      const created = await createBusiness({
        legal_name: businessEditForm.legal_name,
        display_name: businessEditForm.display_name,
        timezone: businessEditForm.timezone,
        phone: businessEditForm.phone || null,
        address_line1: businessEditForm.address_line1 || null,
        address_line2: businessEditForm.address_line2 || null,
        city: businessEditForm.city || null,
        state: businessEditForm.state || null,
        postal_code: businessEditForm.postal_code || null,
        country: businessEditForm.country || null,
      });
      const updatedBusinesses = [...businesses, created].sort((a, b) => a.display_name.localeCompare(b.display_name));
      setBusinesses(updatedBusinesses);
      setSelectedBusinessId(created.id);
      setBusinessEditForm({
        legal_name: created.legal_name,
        display_name: created.display_name,
        timezone: created.timezone,
        is_active: created.is_active,
        phone: created.phone ?? "",
        address_line1: created.address_line1 ?? "",
        address_line2: created.address_line2 ?? "",
        city: created.city ?? "",
        state: created.state ?? "",
        postal_code: created.postal_code ?? "",
        country: created.country ?? "US",
      });
      setBusinessMode("edit");
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
        phone: updated.phone ?? "",
        address_line1: updated.address_line1 ?? "",
        address_line2: updated.address_line2 ?? "",
        city: updated.city ?? "",
        state: updated.state ?? "",
        postal_code: updated.postal_code ?? "",
        country: updated.country ?? "US",
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
      setCampaignMode("edit");
      setCollisionMatches([]);
      setCampaignForm({
        campaign_name: created.campaign_name,
        campaign_key: created.campaign_key ?? "",
        title: created.title,
        objective: created.objective ?? "",
      });
      await regenerateCampaignPreview(created.id, "campaign created");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to create campaign";
      setError(message);
    }
  }

  async function handleCampaignUpdate(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (selectedBusinessId == null || selectedCampaignId == null) {
      setError("Select a campaign before updating");
      return;
    }

    setError(null);
    try {
      const updated = await updateCampaignForBusiness(selectedBusinessId, selectedCampaignId, {
        title: campaignForm.title,
        objective: campaignForm.objective || undefined,
      });
      const nextCampaigns = campaigns.map((item) => (item.id === updated.id ? updated : item));
      setCampaigns(nextCampaigns);
      setCampaignForm({
        campaign_name: updated.campaign_name,
        campaign_key: updated.campaign_key ?? "",
        title: updated.title,
        objective: updated.objective ?? "",
      });
      await regenerateCampaignPreview(updated.id, "campaign updated");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to update campaign";
      setError(message);
    }
  }

  async function handleCloneFromBuilder(): Promise<void> {
    if (selectedBusinessId == null || selectedCampaignId == null) {
      setError("Select an existing campaign to clone");
      return;
    }

    const selected = campaigns.find((item) => item.id === selectedCampaignId) ?? null;
    if (selected == null) {
      setError("Select an existing campaign to clone");
      return;
    }

    const cloneName = window.prompt("New campaign name", `${selected.campaign_name}-copy`);
    if (cloneName == null || cloneName.trim() === "") {
      return;
    }

    setError(null);

    let campaignKey: string | undefined;
    try {
      const existingNameMatches = await lookupCampaigns(selectedBusinessId, cloneName.trim());
      if (existingNameMatches.matches.length > 0) {
        const provided = window.prompt(
          "That campaign name already exists. Enter a secondary key to make it unique (example: 2026)",
          ""
        );
        if (provided == null || provided.trim() === "") {
          return;
        }
        campaignKey = provided.trim();
      }

      const cloned = await cloneCampaignForBusiness(selectedBusinessId, selectedCampaignId, {
        new_campaign_name: cloneName.trim(),
        campaign_key: campaignKey,
      });

      const refreshedCampaigns = await listCampaignsForBusiness(selectedBusinessId);
      setCampaigns(refreshedCampaigns);
      setSelectedCampaignId(cloned.id);
      setCampaignMode("edit");
      setCampaignForm({
        campaign_name: cloned.campaign_name,
        campaign_key: cloned.campaign_key ?? "",
        title: cloned.title,
        objective: cloned.objective ?? "",
      });
      setCollisionMatches([]);
      await regenerateCampaignPreview(cloned.id, "campaign cloned");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Failed to clone campaign";
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
          await regenerateCampaignPreview(activatedCampaignId, "chat clone");
          setChatStatus(
            `Campaign '${campaignName}' created and active. Do you want to view the new promotion PDF now?`
          );
        } else {
          setChatStatus(
            `Campaign '${String(result.new_campaign_name)}' created. It is now the active campaign — continue editing below.`
          );
        }
      } else if (selectedCampaignId != null) {
        await regenerateCampaignPreview(selectedCampaignId, "chat edit");
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
      const artifact = await renderArtifact(selectedCampaignId, artifactType);
      if (artifactType === "flyer") {
        setPreviewArtifactId(artifact.id);
      }
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
    setCampaignMode("edit");
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
        <div className="section-header-row">
          <h2>Business Profile</h2>
          {businessMode !== "list" && (
            <button
              type="button"
              className="ghost-button"
              onClick={() => setBusinessMode("list")}
            >
              ← Business List
            </button>
          )}
        </div>

        {businessMode === "list" && (
          <>
            {businesses.length === 0 ? (
              <p>No businesses yet. Create your first business profile below.</p>
            ) : (
              <ul className="business-list">
                {businesses.map((biz) => (
                  <li key={biz.id}>
                    <button
                      type="button"
                      className={`business-list-item${selectedBusinessId === biz.id ? " business-list-item--selected" : ""}`}
                      onClick={() => {
                        setSelectedBusinessId(biz.id);
                        setBusinessMode("edit");
                      }}
                    >
                      <span className="business-list-name">{biz.display_name}</span>
                      <span className="business-list-sub">{biz.legal_name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <button
              type="button"
              onClick={() => {
                setBusinessEditForm({
                  legal_name: "",
                  display_name: "",
                  timezone: "America/New_York",
                  is_active: true,
                  phone: "",
                  address_line1: "",
                  address_line2: "",
                  city: "",
                  state: "",
                  postal_code: "",
                  country: "US",
                });
                setBusinessMode("create");
              }}
            >
              Create New Business
            </button>
          </>
        )}

        {businessMode === "edit" && (
          <form className="grid-form" onSubmit={handleBusinessUpdate}>
            <label className="stacked-label" htmlFor="edit-legal-name">
              <span>Legal name</span>
              <input
                id="edit-legal-name"
                value={businessEditForm.legal_name}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, legal_name: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="edit-display-name">
              <span>Display name</span>
              <input
                id="edit-display-name"
                value={businessEditForm.display_name}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, display_name: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="edit-timezone">
              <span>Timezone</span>
              <input
                id="edit-timezone"
                value={businessEditForm.timezone}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, timezone: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="edit-phone">
              <span>Phone</span>
              <input
                id="edit-phone"
                value={businessEditForm.phone}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, phone: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="edit-address-line1">
              <span>Address Line 1</span>
              <input
                id="edit-address-line1"
                value={businessEditForm.address_line1}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, address_line1: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="edit-address-line2">
              <span>Address Line 2</span>
              <input
                id="edit-address-line2"
                value={businessEditForm.address_line2}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, address_line2: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="edit-city">
              <span>City</span>
              <input
                id="edit-city"
                value={businessEditForm.city}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, city: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="edit-state">
              <span>State</span>
              <input
                id="edit-state"
                value={businessEditForm.state}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, state: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="edit-postal-code">
              <span>Postal Code</span>
              <input
                id="edit-postal-code"
                value={businessEditForm.postal_code}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, postal_code: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="edit-country">
              <span>Country</span>
              <input
                id="edit-country"
                value={businessEditForm.country}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, country: event.target.value }))}
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
            <button type="submit">Save Changes</button>
          </form>
        )}

        {businessMode === "create" && (
          <form className="grid-form" onSubmit={handleBusinessCreate}>
            <label className="stacked-label" htmlFor="new-legal-name">
              <span>Legal name</span>
              <input
                id="new-legal-name"
                value={businessEditForm.legal_name}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, legal_name: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="new-display-name">
              <span>Display name</span>
              <input
                id="new-display-name"
                value={businessEditForm.display_name}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, display_name: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="new-timezone">
              <span>Timezone</span>
              <input
                id="new-timezone"
                value={businessEditForm.timezone}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, timezone: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="new-phone">
              <span>Phone</span>
              <input
                id="new-phone"
                value={businessEditForm.phone}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, phone: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="new-address-line1">
              <span>Address Line 1</span>
              <input
                id="new-address-line1"
                value={businessEditForm.address_line1}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, address_line1: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="new-address-line2">
              <span>Address Line 2</span>
              <input
                id="new-address-line2"
                value={businessEditForm.address_line2}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, address_line2: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="new-city">
              <span>City</span>
              <input
                id="new-city"
                value={businessEditForm.city}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, city: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="new-state">
              <span>State</span>
              <input
                id="new-state"
                value={businessEditForm.state}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, state: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="new-postal-code">
              <span>Postal Code</span>
              <input
                id="new-postal-code"
                value={businessEditForm.postal_code}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, postal_code: event.target.value }))}
              />
            </label>
            <label className="stacked-label" htmlFor="new-country">
              <span>Country</span>
              <input
                id="new-country"
                value={businessEditForm.country}
                onChange={(event) => setBusinessEditForm((prev) => ({ ...prev, country: event.target.value }))}
              />
            </label>
            <button type="submit">Create Business</button>
          </form>
        )}
      </section>

      <div className="workspace-layout section-gap">
        <div className="workspace-main">
      <section className="card">
        <h2>Campaign Builder</h2>

        <label className="stacked-label" htmlFor="campaign-select">
          <span>Select existing campaign</span>
          <select
            id="campaign-select"
            value={selectedCampaignId ?? ""}
            onChange={(event) => {
              const value = parseSelectedId(event.target.value);
              setSelectedCampaignId(value);
              if (value == null) {
                setCampaignMode("list");
              } else {
                setCampaignMode("edit");
              }
            }}
          >
            <option value="">Choose a campaign...</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.campaign_name}
                {campaign.campaign_key ? ` (${campaign.campaign_key})` : ""}
              </option>
            ))}
          </select>
        </label>

        <div className="campaign-actions-row">
          <button
            type="button"
            onClick={() => {
              setCampaignMode("create");
              setSelectedCampaignId(null);
              setCampaignForm({
                campaign_name: "",
                campaign_key: "",
                title: "",
                objective: "",
              });
            }}
          >
            Create Campaign
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void handleCloneFromBuilder()}
            disabled={selectedCampaignId == null}
            title={selectedCampaignId == null ? "Select a campaign to clone" : "Clone selected campaign"}
          >
            Clone Existing Campaign
          </button>
        </div>

        {campaignMode === "create" ? (
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
        ) : null}

        {campaignMode === "edit" && selectedCampaignId != null ? (
          <form className="grid-form" onSubmit={handleCampaignUpdate}>
            <label className="stacked-label" htmlFor="campaign-name-readonly">
              <span>Campaign name</span>
              <input
                id="campaign-name-readonly"
                value={campaignForm.campaign_name}
                disabled
              />
            </label>
            <label className="stacked-label" htmlFor="campaign-key-readonly">
              <span>Secondary key</span>
              <input
                id="campaign-key-readonly"
                value={campaignForm.campaign_key || "(none)"}
                disabled
              />
            </label>
            <label className="stacked-label" htmlFor="campaign-title-edit">
              <span>Title</span>
              <input
                id="campaign-title-edit"
                value={campaignForm.title}
                onChange={(event) => setCampaignForm((prev) => ({ ...prev, title: event.target.value }))}
                required
              />
            </label>
            <label className="stacked-label" htmlFor="campaign-objective-edit">
              <span>Objective (optional)</span>
              <input
                id="campaign-objective-edit"
                value={campaignForm.objective}
                onChange={(event) => setCampaignForm((prev) => ({ ...prev, objective: event.target.value }))}
              />
            </label>
            <button type="submit">Save Campaign</button>
          </form>
        ) : null}

        {campaignMode === "list" ? (
          <p>Select a campaign, create a new one, or clone an existing campaign to begin.</p>
        ) : null}

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
          {selectedCampaignId != null ? (
            <button
              type="button"
              className="ghost-button"
              onClick={() => void regenerateCampaignPreview(selectedCampaignId, "manual refresh")}
              disabled={previewRendering}
            >
              {previewRendering ? "Refreshing Preview..." : "Refresh Preview"}
            </button>
          ) : null}
        </div>
        {renderStatus ? <p>{renderStatus}</p> : null}
        {previewStatus ? <p>{previewStatus}</p> : null}

        <div className="preview-window">
          {previewArtifactId != null ? (
            <iframe
              title="Campaign PDF Preview"
              className="preview-frame"
              src={artifactPreviewUrl(previewArtifactId)}
            />
          ) : (
            <p>Select or create a campaign and generate changes to see the live PDF preview.</p>
          )}
        </div>

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
        </div>

        <aside className="workspace-side">
      <section className="card chat-panel">
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
        </aside>
      </div>

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

      {reconciliationReport ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="reconcile-title">
          <div className="modal-card">
            <h3 id="reconcile-title">Data Conflict Detected</h3>
            <p>
              The database and your local DATA_DIR are out of sync. Choose how to proceed:
            </p>
            {reconciliationReport.yaml_only.length > 0 && (
              <p>
                <strong>In DATA_DIR only:</strong>{" "}
                {reconciliationReport.yaml_only.join(", ")}
              </p>
            )}
            {reconciliationReport.db_only.length > 0 && (
              <p>
                <strong>In database only:</strong>{" "}
                {reconciliationReport.db_only.join(", ")}
              </p>
            )}
            {reconciliationReport.content_differs.length > 0 && (
              <p>
                <strong>Campaign sets differ:</strong>{" "}
                {reconciliationReport.content_differs.join(", ")}
              </p>
            )}
            {reconciliationReport.yaml_latest_mtime && (
              <p className="reconcile-timestamp">
                DATA_DIR last modified:{" "}
                {new Date(reconciliationReport.yaml_latest_mtime).toLocaleString()}
              </p>
            )}
            {reconciliationReport.db_latest_updated_at && (
              <p className="reconcile-timestamp">
                Database last updated:{" "}
                {new Date(reconciliationReport.db_latest_updated_at).toLocaleString()}
              </p>
            )}
            <div className="modal-actions reconcile-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleReconciliationChoice("db_to_yaml")}
              >
                Overwrite DATA_DIR from DB
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleReconciliationChoice("yaml_to_db")}
              >
                Load DATA_DIR into DB
              </button>
              <button
                type="button"
                onClick={() =>
                  void handleReconciliationChoice(pickMostRecentDirection(reconciliationReport))
                }
              >
                Use Most Recent (Recommended)
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
