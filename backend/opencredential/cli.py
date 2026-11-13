# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator CLI: ``oc migrate | seed | worker | api | openapi``."""

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


@app.command()
def worker(queue: list[str] = typer.Option(None, help="Queues to consume (default: all)")) -> None:
    """Run the background job worker."""
    from opencredential.worker import run

    run(queues=queue or None)


@app.command()
def api(host: str = "0.0.0.0", port: int = 8000) -> None:  # noqa: S104
    """Run the HTTP API with uvicorn."""
    import uvicorn

    uvicorn.run("opencredential.main:app", host=host, port=port, proxy_headers=True)


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
