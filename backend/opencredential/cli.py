# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator CLI (``oc --help``): migrate, seed, issue-demo, verify, revoke, reissue, worker, api."""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(help="OpenCredential operator commands", no_args_is_help=True)


@app.command()
def migrate(revision: str = "head") -> None:
    """Apply database migrations (owner role, OC_DATABASE_OWNER_URL)."""
    from opencredential.db.migrate import upgrade

    upgrade(revision)
    typer.echo(f"migrated to {revision}")


@app.command()
def seed(reset: bool = typer.Option(False, help="Rebuild the database first (dev only)")) -> None:
    """Load the development demo institution, issuer, badges and synthetic learners."""
    from opencredential.seed import run

    result = run(reset=reset)
    if result.created:
        typer.echo(f"seeded demo institution {result.institution_id}: {result.counts}")
    else:
        typer.echo(f"demo institution already present ({result.institution_id}); nothing to do")


@app.command("issue-demo")
def issue_demo(
    out: Path = typer.Option(None, help="Also write each signed credential to this directory"),
) -> None:
    """Dev only: award and issue real signed credentials to the demo learners who qualify."""
    from opencredential.issuance.demo import issue_demo_credentials

    result = issue_demo_credentials(out_dir=out)
    typer.echo(json.dumps(result, indent=2, default=str))


@app.command("verify")
def verify(path: Path) -> None:
    """Verify a credential file with this service's verifier (needs the signer and database)."""
    from opencredential.settings import get_settings
    from opencredential.signer_client import SignerClient
    from opencredential.verification.service import Verifier
    from opencredential.verification.sources import DefaultSources, own_origins

    settings = get_settings()
    doc = json.loads(path.read_text(encoding="utf-8"))
    signer = SignerClient(settings)
    try:
        result = Verifier(signer, DefaultSources(own_origins(settings.public_base_url))).verify(doc)
    finally:
        signer.close()
    typer.echo(json.dumps(result.to_dict(), indent=2))
    raise typer.Exit(0 if result.result == "verified" else 1)


@app.command("revoke")
def revoke(
    credential_id: str,
    reason_code: str = typer.Option(..., help="One of the status reason codes"),
    reason_text: str = typer.Option(None, help="Free-text reason, kept with the status record"),
) -> None:
    """Operator revocation (break-glass): record a reason and republish the status list now.

    Day-to-day revocation goes through the API, which checks the revoker policy. This command is
    for operators (for example during a key-compromise response) and is audited as ``system``.
    """
    import uuid

    from sqlalchemy import select

    from opencredential.db.models import Credential
    from opencredential.db.session import owner_session, tenant_session
    from opencredential.settings import get_settings
    from opencredential.signer_client import SignerClient
    from opencredential.status import service as status_service

    cid = uuid.UUID(credential_id)
    with owner_session() as db:
        iid = db.scalar(select(Credential.institution_id).where(Credential.id == cid))
    if iid is None:
        typer.echo(f"no credential {cid}", err=True)
        raise typer.Exit(1)
    settings = get_settings()
    signer = SignerClient(settings)
    try:
        with tenant_session(iid) as db:
            result = status_service.revoke(
                db, cid, reason_code=reason_code, reason_text=reason_text, actor_user_id=None
            )
            if result.status_list_id is not None:
                status_service.publish(db, result.status_list_id, signer, settings)
    except status_service.StatusError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        signer.close()
    typer.echo(json.dumps({"credential_id": str(cid), "changed": result.changed}))


@app.command("reissue")
def reissue(
    credential_ids: list[str],
    justification: str = typer.Option(..., help="Why (kept on the new award decision)"),
) -> None:
    """Issue replacement credentials for revoked ones (for example after a key compromise)."""
    import uuid

    from sqlalchemy import select

    from opencredential.db.models import AwardDecision, Credential
    from opencredential.db.session import owner_session, tenant_session
    from opencredential.issuance import decisions
    from opencredential.issuance.service import issue
    from opencredential.settings import get_settings
    from opencredential.signer_client import SignerClient

    settings = get_settings()
    signer = SignerClient(settings)
    failed = False
    try:
        for raw in credential_ids:
            cid = uuid.UUID(raw)
            with owner_session() as db:
                iid = db.scalar(select(Credential.institution_id).where(Credential.id == cid))
            if iid is None:
                typer.echo(f"{cid}: no such credential", err=True)
                failed = True
                continue
            try:
                with tenant_session(iid) as db:
                    cred = db.get(Credential, cid)
                    original = db.get(AwardDecision, cred.award_decision_id) if cred else None
                    assert original is not None
                    new = decisions.reissue(
                        db, original, justification=justification, decided_by=None
                    )
                    new_id = new.id
            except decisions.DecisionError as exc:
                typer.echo(f"{cid}: {exc}", err=True)
                failed = True
                continue
            result = issue(iid, new_id, signer=signer, settings=settings)
            typer.echo(json.dumps({"revoked": str(cid), "replacement": str(result.credential_id)}))
    finally:
        signer.close()
    raise typer.Exit(1 if failed else 0)


@app.command()
def worker(queue: list[str] = typer.Option(None, help="Queues to consume (default: all)")) -> None:
    """Run the background job worker."""
    from opencredential.worker import run

    run(queues=queue or None)


@app.command()
def api(
    host: str = "0.0.0.0",  # noqa: S104
    port: int = 8000,
    workers: int = typer.Option(
        None, min=1, max=64, help="API processes to start (default: OC_API_WORKERS, or 1)"
    ),
) -> None:
    """Run the HTTP API with uvicorn."""
    import uvicorn

    from opencredential.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "opencredential.main:app",
        host=host,
        port=port,
        workers=workers or settings.api_workers,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


@app.command()
def openapi(out: Path = typer.Option(None, help="Write to file instead of stdout")) -> None:
    """Print the OpenAPI document (committed as docs/api/openapi.json)."""
    from opencredential.api.app import create_app

    doc = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if out:
        out.write_text(doc)
    else:
        typer.echo(doc, nl=False)


if __name__ == "__main__":
    app()


def _register_subcommands() -> None:
    from opencredential.cli_canvas import admin_app, canvas_app, lti_app

    app.add_typer(lti_app, name="lti")
    app.add_typer(canvas_app, name="canvas")
    app.add_typer(admin_app, name="admin")


_register_subcommands()
