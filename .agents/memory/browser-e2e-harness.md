---
name: Browser e2e verification approach
description: How to do real-browser verification of the console when no e2e framework is installed
---

No Playwright/Cypress is installed and Playwright's browser download does not work on NixOS. For real-browser passes, drive a Chromium already present in the Nix store with puppeteer-core (headless, no sandbox) against the console dev server, signing in with the fixture admin account.

**Why:** unit tests (vitest + MSW) cannot catch rendering/interaction regressions; this is the lightest reliable way to get a true end-to-end pass here.

**How to apply:** match visible text case-insensitively (labels are CSS-uppercased), and drive Radix triggers (tabs, selects) with a full pointer-event sequence rather than a bare programmatic click.
