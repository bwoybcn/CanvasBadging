# OpenCredential website

A single static page that explains the project to course staff, students, technology-enhanced
learning teams and institutional decision makers. Plain HTML, CSS and a few lines of JavaScript: no build step, no dependencies,
no third-party requests.

## Preview

```bash
python3 -m http.server 8765 --directory site
```

Then open <http://localhost:8765/>.

## Publishing

The Website workflow (`.github/workflows/site.yml`) publishes this folder to GitHub Pages
whenever `site/` changes on `main`, at <https://bwoybcn.github.io/CanvasBadging/>. It needs
Settings > Pages > Source set to "GitHub Actions" once. It can also be run by hand from the
Actions tab.

## Notes

- Motion is CSS only (scroll-driven animations where the browser supports them) and is switched
  off under `prefers-reduced-motion`. The page is complete without JavaScript.
- Follows the visitor's light or dark preference.
- Screenshots in `assets/` were taken on 24 November 2026 from the demonstration stack
  (`docker compose up`, or the steps in `docs/development/local-setup.md`) with synthetic data
  only. Each is served as AVIF with a WebP fallback at two widths. Retake them when the screens
  they show change.
- The page describes only what is on `main`. Anything still to come goes in the "Where the
  project is" section, marked as not built. Keep its "Before a pilot" list in step with the
  Status section of the top-level README.
- Words follow CONTRIBUTING.md, "Words on the screen": badge and student, with "credential
  file" only for the signed file.
