"use client";

import Link from "next/link";
import React, { useState } from "react";

import { fetchBackendHealth, type HealthResponse } from "../lib/api";

export default function HomePage() {
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    </main>
  );
}
