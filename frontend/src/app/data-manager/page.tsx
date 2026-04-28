"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  fetchDataManagerBusiness,
  fetchDataManagerBusinesses,
  fetchDataManagerCampaignDetail,
  fetchDataManagerCampaigns,
  saveCampaign,
  renderArtifact,
  fetchArtifacts,
  artifactDownloadUrl,
  type ArtifactItem,
  type BusinessDetail,
  type BusinessListItem,
  type CampaignDetailResponse,
  type CampaignListItem,
  type CampaignSaveResponse,
} from "../../lib/api";

export default function DataManagerPage() {
  const [businesses, setBusinesses] = useState<BusinessListItem[]>([]);
  const [selectedBusiness, setSelectedBusiness] = useState<string>("");
  const [businessDetail, setBusinessDetail] = useState<BusinessDetail | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<string>("");
  const [selectedQualifier, setSelectedQualifier] = useState<string>("");
  const [campaignDetail, setCampaignDetail] = useState<CampaignDetailResponse | null>(null);
  const [commitMessage, setCommitMessage] = useState<string>("");
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [saveResult, setSaveResult] = useState<CampaignSaveResponse | null>(null);
  const [saving, setSaving] = useState<boolean>(false);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [rendering, setRendering] = useState<boolean>(false);
  const [renderStatus, setRenderStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadBusinesses() {
      setLoading(true);
      setError(null);
      try {
        const items = await fetchDataManagerBusinesses();
        if (!active) {
          return;
        }
        setBusinesses(items);
        const firstBusiness = items[0]?.display_name ?? "";
        setSelectedBusiness(firstBusiness);
      } catch (caught) {
        if (!active) {
          return;
        }
        const message = caught instanceof Error ? caught.message : "Failed to load businesses";
        setError(message);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadBusinesses();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    if (!selectedBusiness) {
      setBusinessDetail(null);
      setCampaigns([]);
      setSelectedCampaign("");
      setCampaignDetail(null);
      return;
    }

    async function loadBusinessContext() {
      setError(null);
      try {
        const [business, businessCampaigns] = await Promise.all([
          fetchDataManagerBusiness(selectedBusiness),
          fetchDataManagerCampaigns(selectedBusiness),
        ]);
        if (!active) {
          return;
        }
        setBusinessDetail(business);
        setCampaigns(businessCampaigns);
        const firstCampaign = businessCampaigns[0];
        setSelectedCampaign(firstCampaign?.campaign_name ?? "");
        setSelectedQualifier(firstCampaign?.qualifier ?? "");
      } catch (caught) {
        if (!active) {
          return;
        }
        const message = caught instanceof Error ? caught.message : "Failed to load business";
        setError(message);
      }
    }

    void loadBusinessContext();
    return () => {
      active = false;
    };
  }, [selectedBusiness]);

  useEffect(() => {
    let active = true;
    if (!selectedBusiness || !selectedCampaign) {
      setCampaignDetail(null);
      return;
    }

    async function loadCampaignDetail() {
      setError(null);
      try {
        const detail = await fetchDataManagerCampaignDetail(
          selectedBusiness,
          selectedCampaign,
          selectedQualifier || undefined
        );
        if (!active) {
          return;
        }
        setCampaignDetail(detail);
      } catch (caught) {
        if (!active) {
          return;
        }
        const message = caught instanceof Error ? caught.message : "Failed to load campaign";
        setError(message);
      }
    }

    void loadCampaignDetail();
    return () => {
      active = false;
    };
  }, [selectedBusiness, selectedCampaign, selectedQualifier]);

  useEffect(() => {
    if (!campaignDetail) {
      setArtifacts([]);
      return;
    }
    let active = true;
    async function loadArtifacts() {
      if (!campaignDetail) return;
      try {
        const items = await fetchArtifacts(campaignDetail.campaign.id);
        if (active) setArtifacts(items);
      } catch {
        // artifacts panel is non-critical; silently ignore
      }
    }
    void loadArtifacts();
    return () => {
      active = false;
    };
  }, [campaignDetail]);

  function handleCampaignSelect(value: string) {
    const [campaignName, qualifier = ""] = value.split("::");
    setSelectedCampaign(campaignName);
    setSelectedQualifier(qualifier);
    setSaveStatus(null);
    setSaveResult(null);
    setArtifacts([]);
    setRenderStatus(null);
  }

  async function handleRender(artifactType: "flyer" | "poster") {
    if (!campaignDetail) return;
    setRendering(true);
    setRenderStatus(null);
    try {
      await renderArtifact(campaignDetail.campaign.id, artifactType);
      const updated = await fetchArtifacts(campaignDetail.campaign.id);
      setArtifacts(updated);
      setRenderStatus(`${artifactType} generated successfully.`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Render failed";
      setRenderStatus(`Render failed: ${message}`);
    } finally {
      setRendering(false);
    }
  }

  async function handleSave() {
    if (!campaignDetail) {
      return;
    }

    setSaving(true);
    setSaveStatus(null);
    try {
      const result = await saveCampaign(campaignDetail.campaign.id, commitMessage || undefined);
      setSaveResult(result);
      if (result.saved) {
        setSaveStatus(result.auto_commit.performed ? "Save commit completed." : "No staged changes to commit.");
      } else if (result.reason === "commit_on_save_disabled") {
        setSaveStatus("Save is disabled because COMMIT_ON_SAVE is false.");
      } else if (result.reason === "git_config_incomplete") {
        setSaveStatus("Save did nothing because git settings in .config are incomplete.");
      } else {
        setSaveStatus("Save did not perform a commit.");
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Save request failed";
      setSaveStatus(`Save request failed: ${message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <div className="page-header">
        <div>
          <h1>GPMPE Data Manager</h1>
          <p>Inspection view for YAML-synced business and campaign data.</p>
          <p>This screen reads from SQLite after the backend imports YAML into the database at startup.</p>
        </div>
        <Link className="text-link" href="/">
          Back to home
        </Link>
      </div>

      {loading ? <p>Loading sample data...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}

      <section className="data-manager-grid">
        <aside className="card selector-panel">
          <h2>Business</h2>
          <label className="stacked-label">
            <span>Select a business</span>
            <select value={selectedBusiness} onChange={(event) => setSelectedBusiness(event.target.value)}>
              {businesses.map((business) => (
                <option key={business.display_name} value={business.display_name}>
                  {business.display_name}
                </option>
              ))}
            </select>
          </label>

          <h2>Campaign</h2>
          <label className="stacked-label">
            <span>Select a campaign</span>
            <select
              value={selectedCampaign ? `${selectedCampaign}::${selectedQualifier}` : ""}
              onChange={(event) => handleCampaignSelect(event.target.value)}
            >
              {campaigns.map((campaign) => (
                <option
                  key={`${campaign.campaign_name}-${campaign.qualifier ?? ""}`}
                  value={`${campaign.campaign_name}::${campaign.qualifier ?? ""}`}
                >
                  {campaign.display_name}
                  {campaign.qualifier ? ` (${campaign.qualifier})` : ""}
                </option>
              ))}
            </select>
          </label>
        </aside>

        <section className="detail-column">
          <article className="card detail-card">
            <h2>Business Detail</h2>
            {businessDetail ? (
              <>
                <p>
                  <strong>{businessDetail.display_name}</strong> · {businessDetail.legal_name}
                </p>
                <p>Timezone: {businessDetail.timezone}</p>
                <p>Status: {businessDetail.is_active ? "Active" : "Inactive"}</p>
                <h3>Contacts</h3>
                <ul>
                  {businessDetail.contacts.map((contact) => (
                    <li key={`${contact.contact_type}-${contact.contact_value}`}>
                      {contact.contact_type}: {contact.contact_value}
                      {contact.is_primary ? " (primary)" : ""}
                    </li>
                  ))}
                </ul>
                <h3>Locations</h3>
                <ul>
                  {businessDetail.locations.map((location) => (
                    <li key={`${location.line1}-${location.postal_code}`}>
                      {location.label ? `${location.label}: ` : ""}
                      {location.line1}, {location.city}, {location.state} {location.postal_code}
                    </li>
                  ))}
                </ul>
                <h3>Brand Theme</h3>
                {businessDetail.brand_theme ? (
                  <dl className="inline-grid">
                    <div>
                      <dt>Primary</dt>
                      <dd>{businessDetail.brand_theme.primary_color ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Secondary</dt>
                      <dd>{businessDetail.brand_theme.secondary_color ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Accent</dt>
                      <dd>{businessDetail.brand_theme.accent_color ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Font</dt>
                      <dd>{businessDetail.brand_theme.font_family ?? "-"}</dd>
                    </div>
                  </dl>
                ) : (
                  <p>No brand theme found.</p>
                )}
              </>
            ) : (
              <p>No business selected.</p>
            )}
          </article>

          <article className="card detail-card">
            <h2>Campaign Detail</h2>
            {campaignDetail ? (
              <>
                <p>
                  <strong>{campaignDetail.campaign.display_name}</strong>
                  {campaignDetail.campaign.qualifier ? ` (${campaignDetail.campaign.qualifier})` : ""}
                </p>
                <p>{campaignDetail.campaign.title}</p>
                <p>Status: {campaignDetail.campaign.status}</p>
                <p>
                  Dates: {campaignDetail.campaign.start_date ?? "-"} to {campaignDetail.campaign.end_date ?? "-"}
                </p>
                <p>Objective: {campaignDetail.campaign.objective ?? "-"}</p>

                <h3>Offers</h3>
                <ul>
                  {campaignDetail.campaign.offers.map((offer) => (
                    <li key={offer.offer_name}>
                      {offer.offer_name}: {offer.offer_value ?? "-"}
                    </li>
                  ))}
                </ul>

                <h3>Assets</h3>
                <ul>
                  {campaignDetail.campaign.assets.map((asset) => (
                    <li key={`${asset.asset_type}-${asset.source_path}`}>
                      {asset.asset_type}: {asset.source_path} ({asset.mime_type})
                    </li>
                  ))}
                </ul>

                <h3>Template</h3>
                {campaignDetail.campaign.template_binding ? (
                  <>
                    <p>
                      {campaignDetail.campaign.template_binding.template_name} · {campaignDetail.campaign.template_binding.template_kind}
                    </p>
                    <p>Size: {campaignDetail.campaign.template_binding.size_spec ?? "-"}</p>
                  </>
                ) : (
                  <p>No template binding found.</p>
                )}

                <div className="save-controls">
                  <label className="stacked-label" htmlFor="commit-message">
                    <span>Commit message (optional)</span>
                    <input
                      id="commit-message"
                      type="text"
                      placeholder="Save campaign update"
                      value={commitMessage}
                      onChange={(event) => setCommitMessage(event.target.value)}
                    />
                  </label>
                  <button type="button" onClick={() => void handleSave()} disabled={saving}>
                    {saving ? "Saving..." : "Save"}
                  </button>
                  {saveStatus ? <p className="save-status">{saveStatus}</p> : null}
                  {saveResult?.auto_commit?.commit_id ? (
                    <p className="save-status">Commit id: {saveResult.auto_commit.commit_id}</p>
                  ) : null}
                </div>

                <h3>Generated Artifacts</h3>
                <div className="artifact-controls">
                  <button type="button" onClick={() => void handleRender("flyer")} disabled={rendering}>
                    {rendering ? "Generating..." : "Generate Flyer"}
                  </button>
                  <button type="button" onClick={() => void handleRender("poster")} disabled={rendering}>
                    {rendering ? "Generating..." : "Generate Poster"}
                  </button>
                  {renderStatus ? <p className="save-status">{renderStatus}</p> : null}
                </div>
                {artifacts.length > 0 ? (
                  <ul className="artifact-list">
                    {artifacts.map((artifact) => (
                      <li key={artifact.id}>
                        <span>{artifact.artifact_type}</span>
                        <span className="artifact-date">{artifact.created_at ?? ""}</span>
                        <a
                          href={artifactDownloadUrl(artifact.id)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-link"
                        >
                          Download PDF
                        </a>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No artifacts generated yet.</p>
                )}
              </>
            ) : (
              <p>No campaign selected.</p>
            )}
          </article>
        </section>
      </section>
    </main>
  );
}
