# SPDX-License-Identifier: AGPL-3.0-or-later
"""Certificate PDF and badge image downloads (product review recommendation 12).

Only the holder can download them; anyone else is told "not found". The certificate carries a
QR code only while the holder has a public link, prints the name unless asked not to, and is
refused for a revoked badge. Real PostgreSQL and the real signer.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from string import Template

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from opencredential.api.app import create_app
from opencredential.authz import sessions
from opencredential.credentials import certificate as certificates
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.issuance import decisions
from opencredential.issuance.service import issue
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient
from opencredential.status import service as status_service
from opencredential.storage import get_store
from tests.integration.issuance_factory import Tenant, build_tenant

pytestmark = pytest.mark.db

TEMPLATES = Path(certificates.__file__).parents[1] / "authoring" / "artwork_templates"


@pytest.fixture(scope="module")
def signer(database: None, signer_available: bool) -> Iterator[SignerClient]:
    client = SignerClient(get_settings())
    yield client
    client.close()


@pytest.fixture
def client(signer: SignerClient, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def tenant(signer: SignerClient) -> Tenant:
    return build_tenant(get_settings())


def _headers(iid: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    token, _ = sessions.issue(get_settings(), user_id=user_id, institution_id=iid, method="dev")
    return {"authorization": f"Bearer {token}"}


def _badge_with_artwork(t: Tenant) -> uuid.UUID:
    """A published badge that has artwork (the factory's badges have none)."""
    svg = Template((TEMPLATES / "roundel.svg").read_text(encoding="utf-8")).substitute(
        primary="#0B3D91", secondary="#F2A900", text="#FFFFFF", label="Test"
    )
    key, sha = get_store().put(svg.encode(), "image/svg+xml")
    with owner_session() as db:
        asset = m.BadgeAsset(
            institution_id=t.institution_id,
            kind="template",
            media_type="image/svg+xml",
            storage_key=key,
            sha256=sha,
            bytes=len(svg),
            alt_text="A round blue badge",
            sanitised=True,
        )
        db.add(asset)
        definition = m.AchievementDefinition(
            institution_id=t.institution_id,
            issuer_id=t.issuer_id,
            owner_user_id=t.admin_id,
            state="published",
            award_policy="automatic",
        )
        db.add(definition)
        db.flush()
        version = m.AchievementVersion(
            institution_id=t.institution_id,
            definition_id=definition.id,
            version_no=1,
            title="Research Data Management",
            short_description="Planning, storing and sharing research data responsibly.",
            description="Holders planned, stored and shared research data responsibly.",
            learning_outcomes=["Write a data management plan"],
            criteria_narrative="Complete the workshop and submit a plan.",
            category="Research",
            achievement_type="Badge",
            demonstration_kind="completing",
            asset_id=asset.id,
            published_at=datetime.now(UTC),
            published_by=t.admin_id,
        )
        db.add(version)
        db.flush()
        version.frozen = True
        return version.id


def _issue_for(
    t: Tenant, signer: SignerClient, student: int = 0, version_id: uuid.UUID | None = None
) -> uuid.UUID:
    with tenant_session(t.institution_id) as db:
        d, _ = decisions.decide(
            db,
            institution_id=t.institution_id,
            user_id=t.student_ids[student],
            version_id=version_id or t.version_id,
            kind="manual",
            justification="Completed all modules (test)",
            decided_by=t.admin_id,
        )
        decision_id = d.id
    result = issue(t.institution_id, decision_id, signer=signer, settings=get_settings())
    assert result.outcome == "issued"
    with tenant_session(t.institution_id) as db:
        status_service.publish(db, result.status_list_id, signer, get_settings())
    return result.credential_id


def _page(pdf: bytes) -> tuple[str, set[str]]:
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    links = {a.get_object()["/A"]["/URI"] for a in page.get("/Annots", [])}
    return " ".join(page.extract_text().split()), links


def test_holder_downloads_a_certificate_with_and_without_name_and_link(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred = _issue_for(tenant, signer, 0, _badge_with_artwork(tenant))
    me = _headers(tenant.institution_id, tenant.student_ids[0])

    # Private badge: the name is printed, there is no QR code, and the page says how to check.
    r = client.get(f"/api/v1/credentials/{cred}/certificate", headers=me)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == (
        'attachment; filename="research-data-management-certificate.pdf"'
    )
    assert r.headers["cache-control"] == "no-store"
    text, links = _page(r.content)
    assert "This certifies that Student 0 has earned the badge" in text
    assert "Research Data Management" in text
    assert "Planning, storing and sharing research data responsibly." in text
    assert "Ask the holder for the credential file" in text and "/verify" in text
    assert "Scan to check" not in text and links == set()
    # The artwork was drawn into the page.
    assert len(list(PdfReader(io.BytesIO(r.content)).pages[0].images)) == 1

    # Without the name.
    r = client.get(f"/api/v1/credentials/{cred}/certificate?show_name=false", headers=me)
    text, _ = _page(r.content)
    assert "Student 0" not in text
    assert "This certificate records the award of the badge" in text

    # With a public link the QR code and the printed address open that page.
    url = client.put(f"/api/v1/credentials/{cred}/share", json={}, headers=me).json()["share"][
        "url"
    ]
    text, links = _page(client.get(f"/api/v1/credentials/{cred}/certificate", headers=me).content)
    assert "Scan to check this badge" in text and url in text
    assert links == {url}

    # Stop sharing: the next certificate has no code again.
    client.delete(f"/api/v1/credentials/{cred}/share", headers=me)
    text, links = _page(client.get(f"/api/v1/credentials/{cred}/certificate", headers=me).content)
    assert "Scan to check" not in text and links == set()


def test_badge_image_is_a_png_for_the_holder(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred = _issue_for(tenant, signer, 0)
    me = _headers(tenant.institution_id, tenant.student_ids[0])
    # No artwork on this badge: a clear "nothing to download", and the certificate still works.
    r = client.get(f"/api/v1/credentials/{cred}/image", headers=me)
    assert r.status_code == 404 and r.json()["code"] == "NO_IMAGE"
    assert client.get(f"/api/v1/credentials/{cred}/certificate", headers=me).status_code == 200

    cred = _issue_for(tenant, signer, 0, _badge_with_artwork(tenant))
    r = client.get(f"/api/v1/credentials/{cred}/image", headers=me)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == (
        'attachment; filename="research-data-management-badge.png"'
    )
    assert r.content.startswith(certificates.PNG_SIGNATURE)


def test_only_the_holder_and_only_while_the_badge_stands(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred = _issue_for(tenant, signer, 0, _badge_with_artwork(tenant))
    me = _headers(tenant.institution_id, tenant.student_ids[0])
    other = _headers(tenant.institution_id, tenant.student_ids[1])
    admin = _headers(tenant.institution_id, tenant.admin_id)
    for path in ("certificate", "image"):
        # Someone else's badge looks exactly like a missing one, even to an administrator.
        assert client.get(f"/api/v1/credentials/{cred}/{path}", headers=other).status_code == 404
        assert client.get(f"/api/v1/credentials/{cred}/{path}", headers=admin).status_code == 404
        assert (
            client.get(f"/api/v1/credentials/{uuid.uuid4()}/{path}", headers=me).status_code == 404
        )
        assert client.get(f"/api/v1/credentials/{cred}/{path}").status_code == 401

    body = {"reason_code": "issued_in_error", "reason_text": "Awarded to the wrong student"}
    assert (
        client.post(f"/api/v1/credentials/{cred}/revoke", json=body, headers=admin).status_code
        == 200
    )
    r = client.get(f"/api/v1/credentials/{cred}/certificate", headers=me)
    assert r.status_code == 409 and r.json()["code"] == "CERTIFICATE_NOT_AVAILABLE"
    assert "revoked" in r.json()["detail"]


def test_a_name_the_certificate_cannot_print_is_explained(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred = _issue_for(tenant, signer, 0)
    me = _headers(tenant.institution_id, tenant.student_ids[0])
    with owner_session() as db:
        user = db.get(m.User, tenant.student_ids[0])
        assert user is not None
        user.display_name = "王伟"
    # Chinese and Japanese names print, through the bundled fallback font.
    r = client.get(f"/api/v1/credentials/{cred}/certificate", headers=me)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    with owner_session() as db:
        user = db.get(m.User, tenant.student_ids[0])
        assert user is not None
        user.display_name = "محمد"  # right-to-left: still not printable
    r = client.get(f"/api/v1/credentials/{cred}/certificate", headers=me)
    assert r.status_code == 409 and r.json()["code"] == "NAME_NOT_PRINTABLE"
    assert "Put my name on the certificate" in r.json()["detail"]
    # Without the name it downloads.
    r = client.get(f"/api/v1/credentials/{cred}/certificate?show_name=false", headers=me)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
