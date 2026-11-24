// SPDX-License-Identifier: AGPL-3.0-or-later
// Small progressive enhancements. The page is complete without this file.

// Scrollspy. Where the browser supports it, CSS (:target-current) paints the
// active link; this mirrors the state to aria-current for assistive
// technology and is the visual fallback everywhere else.
(() => {
  const links = [...document.querySelectorAll('.site-nav a[href^="#"]')];
  const byId = new Map(links.map((a) => [a.hash.slice(1), a]));
  const sections = [...byId.keys()].map((id) => document.getElementById(id)).filter(Boolean);
  if (!sections.length || !('IntersectionObserver' in window)) return;

  // Only paint with a class where CSS cannot do it, so the two never disagree.
  const cssPaints = CSS.supports('scroll-target-group: auto');
  const visible = new Set();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) visible.add(entry.target);
        else visible.delete(entry.target);
      }
      const current = sections.find((s) => visible.has(s));
      for (const [id, link] of byId) {
        const on = current?.id === id;
        if (!cssPaints) link.classList.toggle('is-current', on);
        if (on) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      }
    },
    // A thin band just above the middle of the viewport decides the section.
    { rootMargin: '-45% 0px -50% 0px' },
  );
  for (const section of sections) observer.observe(section);
})();

// Copy-to-clipboard for the quick start command.
for (const button of document.querySelectorAll('[data-copy]')) {
  if (!navigator.clipboard) {
    button.hidden = true;
    continue;
  }
  button.addEventListener('click', async () => {
    const status = document.querySelector('.status-line');
    try {
      await navigator.clipboard.writeText(document.querySelector(button.dataset.copy).textContent);
      status.textContent = 'Command copied.';
    } catch {
      status.textContent = 'Could not copy. Select the command and copy it by hand.';
    }
  });
}
