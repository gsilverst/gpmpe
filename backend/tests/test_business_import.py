from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import yaml

from .conftest import make_test_client, write_isolated_config


def _business_zip(
    business_name: str,
    *,
    legal_name: str | None = None,
    campaign_name: str | None = None,
    title: str | None = None,
    include_card_theme: bool = False,
) -> bytes:
    legal_name = legal_name or f"{business_name.title()} LLC"
    campaign_name = campaign_name or "spring-sale"
    title = title or "Spring Sale"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr(
            f"{business_name}/{business_name}.yaml",
            yaml.safe_dump(
                {
                    "display_name": business_name,
                    "legal_name": legal_name,
                    "timezone": "America/New_York",
                    "contacts": [
                        {
                            "contact_type": "phone",
                            "contact_value": "555-0100",
                            "is_primary": True,
                        }
                    ],
                    "brand_theme": {
                        "primary_color": "#4b2354",
                        "secondary_color": "#ffffff",
                    },
                },
                sort_keys=False,
            ),
        )
        package.writestr(
            f"{business_name}/promotions/{campaign_name}/{campaign_name}.yaml",
            yaml.safe_dump(
                {
                    "campaign_name": campaign_name,
                    "display_name": campaign_name,
                    "title": title,
                    "status": "draft",
                    "components": [],
                },
                sort_keys=False,
            ),
        )
        if include_card_theme:
            package.writestr(
                f"{business_name}/business_cards/black-and-white/card.html",
                "<!doctype html><title>Card</title>",
            )
    return buffer.getvalue()


def test_admin_business_import_preview_and_import(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)
    package = _business_zip("merci", include_card_theme=True)

    with make_test_client(monkeypatch, config_path) as client:
        preview_response = client.post(
            "/admin/business-imports/preview",
            content=package,
            headers={"Content-Type": "application/zip"},
        )
        import_response = client.post(
            "/admin/business-imports",
            content=package,
            headers={"Content-Type": "application/zip", "X-GPMPE-Actor": "admin-user"},
        )
        businesses_response = client.get("/businesses")
        audit_response = client.get("/admin/audit-logs")

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["business_directory"] == "merci"
    assert preview["display_name"] == "merci"
    assert preview["campaigns"] == ["spring-sale"]
    assert preview["business_card_themes"] == ["black-and-white"]
    assert preview["directory_exists"] is False
    assert preview["database_business_exists"] is False

    assert import_response.status_code == 200
    imported = import_response.json()
    assert imported["ok"] is True
    assert imported["businesses_synced"] == 1
    assert imported["campaigns_synced"] == 1
    assert (data_dir / "merci" / "merci.yaml").exists()
    assert (data_dir / "merci" / "promotions" / "spring-sale" / "spring-sale.yaml").exists()

    assert businesses_response.status_code == 200
    businesses = businesses_response.json()
    assert [row["display_name"] for row in businesses] == ["merci"]

    audit = audit_response.json()["items"][0]
    assert audit["actor"] == "admin-user"
    assert audit["action"] == "business_import.import"
    assert audit["scope"] == "merci"
    assert audit["metadata"]["business_card_themes"] == ["black-and-white"]


def test_admin_business_import_rejects_existing_business_without_replace(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)
    package = _business_zip("merci")

    with make_test_client(monkeypatch, config_path) as client:
        first = client.post(
            "/admin/business-imports",
            content=package,
            headers={"Content-Type": "application/zip"},
        )
        second = client.post(
            "/admin/business-imports",
            content=package,
            headers={"Content-Type": "application/zip"},
        )

    assert first.status_code == 200
    assert second.status_code == 400
    assert "already exists" in second.json()["detail"]


def test_admin_business_import_replace_updates_only_target_business(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)

    with make_test_client(monkeypatch, config_path) as client:
        merci = client.post(
            "/admin/business-imports",
            content=_business_zip("merci", campaign_name="spring-sale", title="Spring Sale"),
            headers={"Content-Type": "application/zip"},
        )
        acme = client.post(
            "/admin/business-imports",
            content=_business_zip("acme", campaign_name="launch", title="Launch"),
            headers={"Content-Type": "application/zip"},
        )
        replaced = client.post(
            "/admin/business-imports?conflict_action=replace",
            content=_business_zip("merci", campaign_name="summer-sale", title="Summer Sale"),
            headers={"Content-Type": "application/zip"},
        )
        businesses_response = client.get("/businesses")

    assert merci.status_code == 200
    assert acme.status_code == 200
    assert replaced.status_code == 200
    assert replaced.json()["campaigns"] == ["summer-sale"]

    businesses = businesses_response.json()
    assert sorted(row["display_name"] for row in businesses) == ["acme", "merci"]
    assert (data_dir / "acme" / "promotions" / "launch" / "launch.yaml").exists()
    assert not (data_dir / "merci" / "promotions" / "spring-sale").exists()
    assert (data_dir / "merci" / "promotions" / "summer-sale" / "summer-sale.yaml").exists()


def test_admin_business_import_rejects_unsafe_zip(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("../evil.txt", "nope")

    with make_test_client(monkeypatch, config_path) as client:
        response = client.post(
            "/admin/business-imports/preview",
            content=buffer.getvalue(),
            headers={"Content-Type": "application/zip"},
        )

    assert response.status_code == 400
    assert "parent path" in response.json()["detail"]
