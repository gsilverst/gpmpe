"""Tests for the render pipeline and artifact API endpoints."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.renderer import _collect_render_context, _file_checksum, render_flyer


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / ".config"
    output_dir = tmp_path / "output"
    database_path = tmp_path / "data" / "test.db"
    data_dir = tmp_path / "yaml-data"
    config_path.write_text(
        "\n".join(
            [
                f"OUTPUT_DIR={output_dir}",
                f"DATABASE_PATH={database_path}",
                f"DATA_DIR={data_dir}",
                "COMMIT_ON_SAVE=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _make_client(monkeypatch, config_path: Path) -> TestClient:
    monkeypatch.setenv("GPMPE_CONFIG_FILE", str(config_path))
    return TestClient(create_app())


def _seed_full_campaign(client: TestClient) -> tuple[int, int]:
    """Seed a business+campaign with offers, a template, and a binding."""
    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "TestCo LLC",
            "display_name": "TestCo",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    # Add a location and contact so the footer renders
    client.post(
        f"/businesses/{business_id}/campaigns",
        json={"campaign_name": "summer", "title": "Summer Sale", "objective": "Drive traffic"},
    )
    campaign_id = client.get(f"/businesses/{business_id}/campaigns").json()["items"][0]["id"]

    client.post(
        f"/campaigns/{campaign_id}/offers",
        json={
            "offer_name": "buy-one-get-one",
            "offer_type": "bundle",
            "offer_value": "Buy 1, get 1 free",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "terms_text": "In-store only.",
        },
    )

    tmpl = client.post(
        "/templates",
        json={
            "template_name": "flyer-standard",
            "template_kind": "flyer",
            "size_spec": "letter",
            "layout": {"headline_slot": "top"},
            "default_values": {"headline": "Summer Event", "cta": "Visit us today"},
        },
    ).json()

    client.post(
        f"/campaigns/{campaign_id}/template-bindings",
        json={
            "template_name": "flyer-standard",
            "override_values": {"headline": "Summer Blowout"},
        },
    )

    return business_id, campaign_id


def test_render_artifact_returns_201(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_full_campaign(client)

    response = client.post(f"/campaigns/{campaign_id}/render", json={"artifact_type": "flyer"})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["campaign_id"] == campaign_id
    assert data["artifact_type"] == "flyer"
    assert data["status"] == "complete"
    assert data["checksum"]


def test_render_creates_pdf_on_disk(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_full_campaign(client)

    response = client.post(f"/campaigns/{campaign_id}/render")
    assert response.status_code == 201
    file_path = Path(response.json()["file_path"])
    assert file_path.exists(), f"Expected PDF at {file_path}"
    # PDF magic bytes
    assert file_path.read_bytes().startswith(b"%PDF"), "Output is not a valid PDF"


def test_render_checksum_matches_file(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_full_campaign(client)

    response = client.post(f"/campaigns/{campaign_id}/render")
    assert response.status_code == 201
    data = response.json()
    actual = hashlib.sha256(Path(data["file_path"]).read_bytes()).hexdigest()
    assert actual == data["checksum"]


def test_list_artifacts_returns_rendered_items(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_full_campaign(client)

    client.post(f"/campaigns/{campaign_id}/render")
    client.post(f"/campaigns/{campaign_id}/render")

    response = client.get(f"/campaigns/{campaign_id}/artifacts")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    for item in items:
        assert item["status"] == "complete"
        assert item["campaign_id"] == campaign_id


def test_download_artifact_returns_pdf_bytes(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_full_campaign(client)

    render_data = client.post(f"/campaigns/{campaign_id}/render").json()
    artifact_id = render_data["id"]

    dl = client.get(f"/artifacts/{artifact_id}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/pdf"
    assert dl.content.startswith(b"%PDF")


def test_download_artifact_404_for_missing(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)

    response = client.get("/artifacts/99999/download")
    assert response.status_code == 404


def test_render_artifact_404_for_bad_campaign(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)

    response = client.post("/campaigns/99999/render")
    assert response.status_code == 404


def test_render_flyer_returns_valid_pdf() -> None:
    """Unit test the renderer directly without the HTTP layer."""
    ctx = {
        "campaign_id": 1,
        "campaign_name": "test-promo",
        "title": "Test Promotion",
        "objective": "Drive sales",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "business_display_name": "ACME",
        "business_legal_name": "ACME LLC",
        "theme": {
            "primary_color": "#209dd7",
            "secondary_color": "#753991",
            "accent_color": "#ecad0a",
        },
        "location": {
            "line1": "123 Main St",
            "line2": None,
            "city": "Raleigh",
            "state": "NC",
            "postal_code": "27601",
        },
        "contacts": [
            {"contact_type": "phone", "contact_value": "555-0100", "is_primary": True},
            {"contact_type": "website", "contact_value": "https://acme.example", "is_primary": False},
        ],
        "offers": [
            {
                "offer_name": "buy-one-get-one",
                "offer_type": "bundle",
                "offer_value": "Buy 1, get 1 free",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "terms_text": "In-store only.",
            }
        ],
        "effective_values": {
            "headline": "January Blowout",
            "cta": "Visit us today!",
        },
        "template_name": "flyer-standard",
    }
    pdf_bytes = render_flyer(ctx)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    checksum = _file_checksum(pdf_bytes)
    assert len(checksum) == 64  # sha256 hex


    def test_render_flyer_is_deterministic_for_same_context() -> None:
        ctx = {
            "campaign_id": 99,
            "campaign_name": "determinism-check",
            "title": "Determinism Check",
            "objective": "Verify stable rendering",
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
            "business_display_name": "ACME",
            "business_legal_name": "ACME LLC",
            "theme": {
                "primary_color": "#209dd7",
                "secondary_color": "#753991",
                "accent_color": "#ecad0a",
            },
            "location": None,
            "contacts": [],
            "offers": [],
            "components": [
                {
                    "component_key": "featured",
                    "component_kind": "featured-offers",
                    "display_title": "Featured",
                    "subtitle": "Deterministic content",
                    "description_text": None,
                    "display_order": 0,
                    "items": [
                        {
                            "item_name": "Swedish",
                            "item_kind": "service",
                            "duration_label": "60 min",
                            "item_value": "$65",
                            "description_text": None,
                            "terms_text": None,
                            "display_order": 0,
                        },
                        {
                            "item_name": "Deep Tissue",
                            "item_kind": "service",
                            "duration_label": "60 min",
                            "item_value": "$75",
                            "description_text": None,
                            "terms_text": None,
                            "display_order": 1,
                        },
                    ],
                }
            ],
            "effective_values": {
                "business_name": "ACME",
                "business_subtitle": "LLC",
                "footer": "acme.example • 555-0100",
                "legal": "Offer valid while supplies last.",
            },
            "template_name": "flyer-standard",
        }

        first = render_flyer(ctx)
        second = render_flyer(ctx)

        assert first == second
        assert _file_checksum(first) == _file_checksum(second)


def test_file_checksum_is_deterministic() -> None:
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert _file_checksum(data) == expected
    assert _file_checksum(data) == _file_checksum(data)


def test_collect_render_context_prefers_ordered_components(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_full_campaign(client)

    with client:
        pass

    from app.config import resolve_config
    from app.db import connect_database

    config = resolve_config()
    with connect_database(config) as connection:
        component_id = connection.execute(
            """
            INSERT INTO campaign_components (
              campaign_id, component_key, component_kind, display_title, subtitle, description_text, display_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                campaign_id,
                "weekday-specials",
                "weekday-specials",
                "Weekday Specials",
                "Tuesday through Thursday",
                "Focused booking windows",
                0,
            ),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO campaign_component_items (
              component_id, item_name, item_kind, duration_label, item_value, description_text, terms_text, display_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                component_id,
                "Deep Tissue Massage",
                "service",
                "90 min",
                "$120",
                "Includes hot towels",
                "Weekdays only",
                0,
            ),
        )
        connection.commit()

        ctx = _collect_render_context(connection, campaign_id)

    assert ctx["components"][0]["component_key"] == "weekday-specials"
    assert ctx["components"][0]["items"][0]["item_name"] == "Deep Tissue Massage"
    assert ctx["components"][0]["items"][0]["item_value"] == "$120"


def test_render_flyer_supports_multi_component_context() -> None:
    ctx = {
        "campaign_id": 1,
        "campaign_name": "test-promo",
        "title": "Test Promotion",
        "objective": "Drive sales",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "business_display_name": "ACME",
        "business_legal_name": "ACME LLC",
        "theme": {
            "primary_color": "#209dd7",
            "secondary_color": "#753991",
            "accent_color": "#ecad0a",
        },
        "location": None,
        "contacts": [],
        "offers": [],
        "components": [
            {
                "component_key": "featured",
                "component_kind": "featured-offers",
                "display_title": "Featured Services",
                "subtitle": "Popular this month",
                "description_text": "A focused set of premium services",
                "display_order": 0,
                "items": [
                    {
                        "item_name": "Hydrating Facial",
                        "item_kind": "service",
                        "duration_label": "60 min",
                        "item_value": "$89",
                        "description_text": "Includes LED add-on",
                        "terms_text": "Valid while appointments last",
                    }
                ],
            },
            {
                "component_key": "legal",
                "component_kind": "legal-note",
                "display_title": "Offer Notes",
                "subtitle": None,
                "description_text": None,
                "display_order": 1,
                "items": [
                    {
                        "item_name": "Offer valid through January 31",
                        "item_kind": "promo-note",
                        "duration_label": None,
                        "item_value": "See spa for full terms",
                        "description_text": None,
                        "terms_text": None,
                    }
                ],
            },
        ],
        "effective_values": {
            "headline": "January Blowout",
            "cta": "Visit us today!",
        },
        "template_name": "flyer-standard",
    }
    pdf_bytes = render_flyer(ctx)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")


def test_render_flyer_preserves_weekday_item_order(monkeypatch) -> None:
    from app import renderer as renderer_module

    captured_titles: list[str] = []

    original_draw_weekday_strip = renderer_module._draw_weekday_strip

    def _capture_strip(pdf, x, y, w, title, detail, price, palette):
        captured_titles.append(title)
        return original_draw_weekday_strip(pdf, x, y, w, title, detail, price, palette)

    monkeypatch.setattr(renderer_module, "_draw_weekday_strip", _capture_strip)

    ctx = {
        "campaign_id": 42,
        "campaign_name": "weekday-order",
        "title": "Weekday Order",
        "objective": "Preserve item ordering",
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "business_display_name": "ACME",
        "business_legal_name": "ACME LLC",
        "theme": {
            "primary_color": "#3E1C5C",
            "secondary_color": "#6E4A8E",
            "accent_color": "#E0559A",
        },
        "location": None,
        "contacts": [],
        "offers": [],
        "components": [
            {
                "component_key": "featured",
                "component_kind": "featured-offers",
                "display_title": "Featured",
                "subtitle": "Subtitle",
                "description_text": None,
                "display_order": 0,
                "items": [
                    {
                        "item_name": "A",
                        "item_kind": "service",
                        "duration_label": "60 min",
                        "item_value": "$10",
                        "description_text": None,
                        "terms_text": None,
                        "display_order": 0,
                    },
                    {
                        "item_name": "B",
                        "item_kind": "service",
                        "duration_label": "60 min",
                        "item_value": "$20",
                        "description_text": None,
                        "terms_text": None,
                        "display_order": 1,
                    },
                ],
            },
            {
                "component_key": "weekday-specials",
                "component_kind": "weekday-specials",
                "display_title": "Weekday Specials",
                "subtitle": "Wednesday-Friday",
                "description_text": None,
                "display_order": 1,
                "items": [
                    {
                        "item_name": "Chair Massage",
                        "item_kind": "service",
                        "duration_label": "30 minutes",
                        "item_value": "$40",
                        "description_text": None,
                        "terms_text": None,
                        "display_order": 0,
                    },
                    {
                        "item_name": "Lymphatic Drainage",
                        "item_kind": "service",
                        "duration_label": "60 minutes",
                        "item_value": "$135",
                        "description_text": None,
                        "terms_text": None,
                        "display_order": 1,
                    },
                    {
                        "item_name": "Body Sculpting Lymphatic",
                        "item_kind": "service",
                        "duration_label": "90 minutes",
                        "item_value": "$195",
                        "description_text": None,
                        "terms_text": None,
                        "display_order": 2,
                    },
                ],
            },
        ],
        "effective_values": {
            "business_name": "ACME",
            "business_subtitle": "LLC",
            "footer": "acme.example • 555-0100",
            "legal": "Offer valid while supplies last.",
        },
        "template_name": "flyer-standard",
    }

    pdf_bytes = render_flyer(ctx)

    assert pdf_bytes.startswith(b"%PDF")
    assert captured_titles == [
        "Chair Massage",
        "Lymphatic Drainage",
        "Body Sculpting Lymphatic",
    ]


def test_render_flyer_places_component_footnote_in_box_and_campaign_footnote_in_footer(monkeypatch) -> None:
    from app import renderer as renderer_module

    centered_texts: list[str] = []
    wrapped_texts: list[str] = []

    original_centered = renderer_module._draw_centered
    original_wrapped = renderer_module._draw_wrapped_centered

    def _capture_centered(pdf, text, x, y, font, size, color):
        centered_texts.append(text or "")
        return original_centered(pdf, text, x, y, font, size, color)

    def _capture_wrapped(pdf, text, cx, top_y, max_w, font, size, leading, color):
        wrapped_texts.append(text or "")
        return original_wrapped(pdf, text, cx, top_y, max_w, font, size, leading, color)

    monkeypatch.setattr(renderer_module, "_draw_centered", _capture_centered)
    monkeypatch.setattr(renderer_module, "_draw_wrapped_centered", _capture_wrapped)

    ctx = {
        "campaign_id": 9,
        "campaign_name": "footnotes",
        "title": "Footnote Test",
        "objective": "Footnote behavior",
        "campaign_footnote_text": "Promotion-wide disclaimer",
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "business_display_name": "ACME",
        "business_legal_name": "ACME LLC",
        "theme": {
            "primary_color": "#3E1C5C",
            "secondary_color": "#6E4A8E",
            "accent_color": "#E0559A",
        },
        "location": None,
        "contacts": [],
        "offers": [],
        "components": [
            {
                "component_key": "featured",
                "component_kind": "featured-offers",
                "display_title": "Featured Services",
                "footnote_text": "Featured section terms",
                "subtitle": "Subtitle",
                "description_text": None,
                "display_order": 0,
                "items": [
                    {
                        "item_name": "A",
                        "item_kind": "service",
                        "duration_label": "60 min",
                        "item_value": "$10",
                        "description_text": None,
                        "terms_text": None,
                        "display_order": 0,
                    }
                ],
            }
        ],
        "effective_values": {
            "business_name": "ACME",
            "business_subtitle": "LLC",
            "footer": "acme.example • 555-0100",
            "legal": "Offer valid while supplies last.",
        },
        "template_name": "flyer-standard",
    }

    pdf_bytes = render_flyer(ctx)

    assert pdf_bytes.startswith(b"%PDF")
    assert any(text.endswith(" **") for text in centered_texts if "FEATURED" in text.upper())
    assert "** Featured section terms" in centered_texts
    assert "** Promotion-wide disclaimer" in wrapped_texts
