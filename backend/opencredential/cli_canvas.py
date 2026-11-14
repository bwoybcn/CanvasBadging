# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator commands for the Canvas connection: ``oc lti …``, ``oc canvas …``, ``oc admin …``.

These run with the owner database role (install-time administration), print no secrets and
read the API client secret from ``OC_CANVAS_API_CLIENT_SECRET`` or a hidden prompt.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import typer
from sqlalchemy import select

lti_app = typer.Typer(help="LTI 1.3 tool key and Canvas configuration", no_args_is_help=True)
canvas_app = typer.Typer(help="Register and connect a Canvas instance", no_args_is_help=True)
admin_app = typer.Typer(help="Institution administration bootstrap", no_args_is_help=True)


@lti_app.command("keygen")
def lti_keygen(
    out: Path = typer.Option(None, help="PEM path (default OC_LTI_PRIVATE_KEY_FILE)"),
) -> None:
    """Create the tool's RSA signing key (refuses to overwrite)."""
    from opencredential.lti.keys import generate
    from opencredential.settings import get_settings

    path = out or Path(get_settings().lti_private_key_file)
    if path.exists():
        typer.echo(f"{path} already exists; not overwriting", err=True)
        raise typer.Exit(1)
    key = generate(path)
    typer.echo(f"wrote {path} (kid {key.kid})")


@lti_app.command("config")
def lti_config(
    label: str = typer.Option("Micro-Credentials", help="Course navigation menu text"),
    jwks_url: bool = typer.Option(False, help="Reference /lti/jwks instead of embedding the key"),
    privacy_level: str = typer.Option("public", help="public | name_only | email_only | anonymous"),
) -> None:
    """Print the JSON to paste into a Canvas LTI 1.3 developer key."""
    from opencredential.lti.config import canvas_tool_config
    from opencredential.settings import get_settings

    cfg = canvas_tool_config(
        get_settings(), label=label, privacy_level=privacy_level, include_public_jwk=not jwks_url
    )
    typer.echo(json.dumps(cfg, indent=2))


def _institution_id(db, slug: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    from opencredential.db.models import Institution

    inst = db.scalar(select(Institution).where(Institution.slug == slug))
    if inst is None:
        typer.echo(f"no institution with slug {slug!r}", err=True)
        raise typer.Exit(1)
    return inst.id


@canvas_app.command("register")
def canvas_register(
    institution: str = typer.Option(..., help="Institution slug"),
    base_url: str = typer.Option(..., help="Canvas URL users see, e.g. http://localhost:3000"),
    client_id: str = typer.Option(..., help="LTI developer key client id"),
    deployment_id: list[str] = typer.Option([], help="Approved deployment id(s)"),
    issuer: str = typer.Option("https://canvas.instructure.com", help="LTI issuer (iss)"),
    name: str = typer.Option("Canvas", help="Display name"),
    api_client_id: str = typer.Option(None, help="REST API developer key client id"),
    auth_url: str = typer.Option(None, help="Default <base>/api/lti/authorize_redirect"),
    token_url: str = typer.Option(None, help="Default <base>/login/oauth2/token"),
    jwks_url: str = typer.Option(None, help="Default <base>/api/lti/security/jwks"),
    privacy_level: str = typer.Option("public"),
    create_institution: str = typer.Option(
        None, help="Create the institution with this display name if it does not exist"
    ),
) -> None:
    """Create or update a Canvas integration (LTI registration + REST API key)."""
    from opencredential import audit, secretbox
    from opencredential.db.models import CanvasIntegration, Institution, LtiDeployment
    from opencredential.db.session import owner_session
    from opencredential.integrations.canvas.oauth import secret_context
    from opencredential.settings import get_settings

    settings = get_settings()
    base = base_url.rstrip("/")
    secret = None
    if api_client_id:
        secret = os.environ.get("OC_CANVAS_API_CLIENT_SECRET") or typer.prompt(
            "Canvas API developer key secret", hide_input=True
        )
    with owner_session() as db:
        inst = db.scalar(select(Institution).where(Institution.slug == institution))
        if inst is None:
            if not create_institution:
                typer.echo(f"no institution {institution!r} (use --create-institution)", err=True)
                raise typer.Exit(1)
            inst = Institution(slug=institution, name=create_institution, is_demo=False)
            db.add(inst)
            db.flush()
        integ = db.scalar(
            select(CanvasIntegration).where(
                CanvasIntegration.lti_issuer == issuer, CanvasIntegration.lti_client_id == client_id
            )
        )
        if integ is None:
            integ = CanvasIntegration(
                institution_id=inst.id, lti_issuer=issuer, lti_client_id=client_id, status="pending"
            )
            db.add(integ)
        elif integ.institution_id != inst.id:
            typer.echo("that LTI registration belongs to another institution", err=True)
            raise typer.Exit(1)
        integ.name, integ.base_url, integ.privacy_level = name, base, privacy_level
        integ.lti_auth_url = auth_url or f"{base}/api/lti/authorize_redirect"
        integ.lti_token_url = token_url or f"{base}/login/oauth2/token"
        integ.lti_jwks_url = jwks_url or f"{base}/api/lti/security/jwks"
        db.flush()
        if api_client_id:
            integ.api_client_id = api_client_id
            integ.api_client_secret_enc = secretbox.seal(
                settings, secret or "", secret_context(integ.id)
            )
        for dep in deployment_id:
            exists = db.scalar(
                select(LtiDeployment).where(
                    LtiDeployment.canvas_integration_id == integ.id,
                    LtiDeployment.deployment_id == dep,
                )
            )
            if exists is None:
                db.add(
                    LtiDeployment(
                        institution_id=inst.id,
                        canvas_integration_id=integ.id,
                        deployment_id=dep,
                        scope="account",
                    )
                )
        audit.record(
            db,
            action="canvas.integration_registered",
            resource_type="canvas_integration",
            resource_id=integ.id,
            institution_id=inst.id,
            actor_kind="system",
            data={"client_id": client_id, "deployments": list(deployment_id)},
        )
        typer.echo(f"integration {integ.id} for {inst.slug} ({integ.status})")


@canvas_app.command("connect")
def canvas_connect(
    institution: str = typer.Option(..., help="Institution slug"),
    admin_email: str = typer.Option(..., help="Email of an institution admin (audited actor)"),
    client_id: str = typer.Option(None, help="LTI client id, if the institution has several"),
) -> None:
    """Print a one-time link that authorises the Canvas integration account for REST access.

    Open it in a browser signed in to Canvas as the integration account."""
    from opencredential.db.models import CanvasIntegration, Membership, User
    from opencredential.db.session import owner_session
    from opencredential.integrations.canvas import oauth
    from opencredential.settings import get_settings

    settings = get_settings()
    with owner_session() as db:
        iid = _institution_id(db, institution)
        q = select(CanvasIntegration).where(CanvasIntegration.institution_id == iid)
        if client_id:
            q = q.where(CanvasIntegration.lti_client_id == client_id)
        integrations = list(db.scalars(q))
        if len(integrations) != 1:
            typer.echo(f"found {len(integrations)} integrations; pass --client-id", err=True)
            raise typer.Exit(1)
        user = db.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.institution_id == iid,
                User.email == admin_email,
                Membership.role == "inst_admin",
                Membership.revoked_at.is_(None),
            )
        )
        if user is None:
            typer.echo("no institution admin with that email (see `oc admin grant`)", err=True)
            raise typer.Exit(1)
        state = oauth.make_state(
            settings, institution_id=iid, integration_id=integrations[0].id, user_id=user.id
        )
        typer.echo(oauth.authorize_url(settings, integrations[0], state))


@admin_app.command("grant")
def admin_grant(
    institution: str = typer.Option(..., help="Institution slug"),
    email: str = typer.Option(..., help="User email (the user must have launched once)"),
    role: str = typer.Option("inst_admin", help="Only inst_admin is supported here"),
) -> None:
    """Bootstrap the first institution administrator (later grants happen in the app)."""
    from opencredential import audit
    from opencredential.db.models import Membership, User
    from opencredential.db.session import owner_session

    if role != "inst_admin":
        typer.echo("only inst_admin can be bootstrapped from the CLI", err=True)
        raise typer.Exit(1)
    with owner_session() as db:
        iid = _institution_id(db, institution)
        users = list(
            db.scalars(select(User).where(User.institution_id == iid, User.email == email))
        )
        if len(users) != 1:
            typer.echo(f"found {len(users)} users with that email", err=True)
            raise typer.Exit(1)
        exists = db.scalar(
            select(Membership).where(
                Membership.user_id == users[0].id,
                Membership.role == "inst_admin",
                Membership.revoked_at.is_(None),
            )
        )
        if exists is None:
            db.add(
                Membership(
                    institution_id=iid,
                    user_id=users[0].id,
                    scope_type="institution",
                    scope_id=iid,
                    role="inst_admin",
                    source="grant",
                )
            )
            audit.record(
                db,
                action="membership.granted",
                resource_type="user",
                resource_id=users[0].id,
                institution_id=iid,
                actor_kind="system",
                data={"role": "inst_admin", "via": "cli"},
            )
        typer.echo(f"{email} is inst_admin of {institution}")


@admin_app.command("set-verification-host")
def admin_set_verification_host(
    institution: str = typer.Option(..., help="Institution slug"),
    host: str = typer.Option("", help="Public verification domain, such as badges.liverpool.ac.uk"),
    clear: bool = typer.Option(False, "--clear", help="Remove the host instead"),
) -> None:
    """Set an institution's public verification domain (operator only).

    Check first that the institution controls the domain: issuers get did:web identifiers on
    it and this service vouches for them. The host is unique across institutions and locked
    once issuers sign on it.
    """
    from opencredential.db.models import Institution
    from opencredential.db.session import owner_session
    from opencredential.errors import DomainError
    from opencredential.governance.institution import set_verification_host

    if bool(host) == clear:
        typer.echo("pass either --host or --clear", err=True)
        raise typer.Exit(1)
    with owner_session() as db:
        inst = db.get(Institution, _institution_id(db, institution))
        assert inst is not None
        try:
            set_verification_host(db, inst, None if clear else host)
        except DomainError as exc:
            typer.echo(f"{exc.code}: {exc.title}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"{institution} verification host: {inst.verification_host or '(none)'}")
