---
name: Console browser verification
description: Current verification workflow and historical Replit browser setup
---

Use the [console UI audit skill](../skills/console-ui-audit/SKILL.md) for scenario coverage and evidence against a real control plane. Choose the browser automation backend available in the current environment. The repository does not install a Playwright, Cypress, or Puppeteer end-to-end harness.

The default local ports are control plane `8000` and console `5000`; an isolated verification deployment can use separate ports with `CONTROL_PLANE_URL` and `PORT` configured accordingly. Seed disposable test accounts through the CLI or API. Do not save passwords or minted secrets in memory.

Vitest and mocked API tests do not replace real-browser verification. Report browser-tooling blockers separately from product failures and do not claim a manual pass without observing the scenarios.

Historical Replit verification used `puppeteer-core` with Chromium from the Nix store after a browser download failed. That was an environment-specific workaround, not a prerequisite for macOS or other development environments. Prefer semantic locators and supported click actions; only investigate CSS casing or Radix pointer events when a concrete interaction fails.
