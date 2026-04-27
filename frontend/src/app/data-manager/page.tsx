"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import {
  fetchDataManagerBusiness,
  fetchDataManagerBusinesses,
  fetchDataManagerCampaignDetail,
  fetchDataManagerCampaigns,
  type BusinessDetail,
  type BusinessListItem,
  type CampaignDetailResponse,
  type CampaignListItem,
} from "../../lib/api";

export default function DataManagerPage() {
  const [businesses, setBusinesses] = useState<BusinessListItem[]>([]);
  const [selectedBusiness, setSelectedBusiness] = useState<string>("");
  const [businessDetail, setBusinessDetail] = useState<BusinessDetail | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<string>("");
  const [selectedQualifier, setSelectedQualifier] = useState<string>("");
  const [campaignDetail, setCampaignDetail] = useState<CampaignDetailResponse | null>(null);
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

  function handleCampaignSelect(value: string) {
    const [campaignName, qualifier = ""] = value.split("::");
    setSelectedCampaign(campaignName);
    setSelectedQualifier(qualifier);
  }

  return (
    <main>
      <div className="page-header">
        <div>
          <h1>Step 4a Data Manager</h1>
          <p>Read-only inspection view for YAML-synced business and campaign data.</p>
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
