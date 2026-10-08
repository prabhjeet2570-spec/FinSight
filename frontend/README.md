# FinSight workbench UI

A responsive research desk with navy navigation and a light document canvas built with React and TypeScript. It includes issuer scope, filing library, source inspection, financial derivations, persisted history, JSON exports, import status, and recorded evaluation results.

From this directory:

```bash
npm ci
npm run dev
npm run build
npm run lint
```

Vite proxies requests to the local API. The production build uses same-origin API requests and is served by FastAPI. There are no external font requests or analytics scripts.

With the local API running:

```bash
npm run test:e2e
npm run screenshots
```

Browser checks use installed Chrome on macOS or Playwright Chromium on other platforms. Set `CHROME_PATH` to choose an explicit executable.

[Local walkthrough](../docs/walkthrough.md) · [Source and calculation contracts](../docs/architecture.md)
