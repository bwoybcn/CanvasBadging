# Releasing a version

A release is a version number, a section in `CHANGELOG.md`, two container images on the GitHub
container registry and a page on the repository's Releases tab. The **Release** workflow
(`.github/workflows/release.yml`) builds and publishes all of it; what is left for a person is
to decide the number and say what changed.

## Before the release

1. Make sure `main` is green in CI, including "Production kit smoke test".
2. Choose the version (`MAJOR.MINOR.PATCH`, [Semantic Versioning](https://semver.org/)). Until
   an institution runs it in production, stay below 1.0.0.
3. In one pull request:
   * set the version in `backend/pyproject.toml`, `backend/opencredential/__init__.py`,
     `signer/package.json` and `frontend/package.json` (then run `uv lock` in `backend/` and
     `npm install` in `signer/` and `frontend/` so the lock files agree, and regenerate
     `docs/api/openapi.json`);
   * in `CHANGELOG.md`, rename `## [Unreleased]` to `## [1.2.3] - 2026-12-01` and add a new,
     empty `## [Unreleased]` above it. Lead the section with anything an installer must do
     when upgrading.
4. Merge it.

## Publishing

On GitHub: **Actions**, **Release**, **Run workflow**, branch `main`, and type the version
(without the `v`). Or push a tag: `git tag v1.2.3 && git push origin v1.2.3`.

The workflow refuses to run if the number does not match the code, if the changelog has no
section for it, or if that version was already released: a published version is never replaced.
It then builds `ghcr.io/<owner>/canvasbadging-api:<version>` and
`ghcr.io/<owner>/canvasbadging-signer:<version>`, pushes them, creates the tag and publishes
the release with the changelog section as its notes.

**The first time only:** GitHub creates container packages as private. Open each of the two
packages (the repository's front page, **Packages**), **Package settings**, **Change
visibility**, **Public**, so installers can pull the images without signing in.

## After the release

Installations upgrade by setting the new `OC_VERSION` (see
[production.md](../deployment/production.md#quick-start-the-production-kit)). There is no
`latest` tag on purpose: an installation states the version it runs.
