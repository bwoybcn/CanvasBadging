# OpenCredential website

A single static page that explains the project to lecturers, students and institutional
decision makers. Plain HTML, CSS and a few lines of JavaScript: no build step, no dependencies,
no third-party requests.

## Preview

```bash
python3 -m http.server 8765 --directory site
```

Then open <http://localhost:8765/>.

## Notes

- Motion is CSS only (scroll-driven animations where the browser supports them) and is switched
  off under `prefers-reduced-motion`. The page is complete without JavaScript.
- Follows the visitor's light or dark preference.
- Screenshots in `assets/` come from the real-Canvas run of 13 November 2026 and show no
  personal data. Each is served as AVIF with a WebP fallback at two widths.
- Figures in the "Where the project is" section come from `docs/reports/rtm-evidence.md` and
  `docs/reports/dod.md`. Update them together.
