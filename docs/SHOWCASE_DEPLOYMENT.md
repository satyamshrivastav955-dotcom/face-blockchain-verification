# FaceProof Public Showcase — GitHub Pages Deployment Guide

This document describes the architecture, configuration, and manual deployment procedure for the **FaceProof Public Showcase** hosted on GitHub Pages.

---

## 1. Architectural Distinction

FaceProof deliberately separates the public web presence from the local verification engine:

| Property | Local Verification App (`web/` + `src/web/`) | Public Showcase (`showcase/`) |
|---|---|---|
| **Purpose** | Live interactive case intake, face detection, provider search, evidence sealing | Project showcase, architecture explanation, benchmark review, reproducibility guide |
| **Hosting** | **Loopback only** (`127.0.0.1:8765`), single-user workstation | **Static GitHub Pages** (`https://<user>.github.io/<repo>/`) |
| **Backend** | Python FastAPI server with direct filesystem and computer vision access | **None** (100% static client bundle) |
| **Authentication** | None (intentionally local; MUST NOT be exposed to networks) | N/A (public static content) |
| **Data Handled** | User photographs, candidate downloads, face crops, raw API keys | Public diagrams, benchmark tables, verified demo captures |
| **Network Exposure** | Bound to loopback interface only | Distributed over GitHub global CDN |

> [!CAUTION]
> **Do not attempt to deploy `web/dist` directly to a public static host.** The local application frontend makes live calls to `/api/jobs`, `/api/health`, and filesystem artifact endpoints. Simply hosting `web/dist` without a backend produces a broken interface, and exposing the FastAPI backend to the public internet violates the project's security architecture (no authentication, unrestricted local execution).

---

## 2. Showcase Architecture

The showcase is an independent React 19 + TypeScript + Vite project located in `showcase/`:

* **Zero Backend Dependency**: All interactive components (benchmark comparisons, trust boundary explorer, architecture diagrams) evaluate locally in client state.
* **Hermetic Bundling**: All verified visual assets (`hero.svg`, `pipeline.svg`, `evidence_ladder.svg`, `benchmark.svg`, `demo.gif`, UI captures) are stored in `showcase/public/assets/` and copied to `showcase/dist/assets/` on build.
* **Subpath Resilient**: Configured with Vite base path `/face-blockchain-verification/` (with fallback to relative `./`), ensuring asset URLs resolve whether accessed at the GitHub Pages project subpath or a custom domain.
* **Fallback Routing**: Includes `showcase/public/404.html` styled in the FaceProof design language for unindexed URLs.

---

## 3. GitHub Pages Configuration (One-Time Setup)

To enable GitHub Pages deployment using GitHub Actions:

1. Open your repository on GitHub:
   ```
   https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification
   ```
2. Navigate to **Settings** &rarr; **Pages** (under the "Code and automation" section in the left sidebar).
3. Under **Build and deployment**:
   * **Source**: Select **GitHub Actions** (do NOT select "Deploy from a branch").
4. Under **Custom domain** (optional):
   * Leave blank unless you have configured a custom DNS domain.
5. Under **Enforce HTTPS**:
   * Ensure **Enforce HTTPS** is checked.

---

## 4. Manual Deployment Procedure

Once GitHub Pages is set to use GitHub Actions as the source:

### Option A — Manual Trigger via GitHub Web UI (Recommended for Initial Release)
1. Go to the **Actions** tab of the repository.
2. In the left workflow sidebar, click **Deploy Showcase to GitHub Pages**.
3. Click the **Run workflow** dropdown on the right.
4. Select the **main** branch and click the green **Run workflow** button.
5. The workflow will:
   * Check out the repository.
   * Install dependencies via `npm ci` in `showcase/`.
   * Compile TypeScript and bundle assets to `showcase/dist/`.
   * Upload the artifact using `actions/upload-pages-artifact@v3`.
   * Deploy the static bundle using `actions/deploy-pages@v4` to the `github-pages` environment.

### Option B — Automatic Trigger via Commit
Any push to `main` that touches files in `showcase/**` or `.github/workflows/deploy-showcase.yml` will automatically trigger a deployment.

---

## 5. Local Build and Verification

Before triggering a remote deployment, verify the build locally:

```bash
cd showcase
npm ci
npm run build
npm run preview
```

Open the preview URL (typically `http://localhost:4173/`) and verify:
1. All SVG diagrams and PNG captures load without HTTP 404 errors.
2. The browser console reports zero JavaScript runtime errors.
3. No requests to `/api/*` are dispatched.
4. All external links point to the correct GitHub repository and documentation files.
5. The responsive layout adapts cleanly between mobile and desktop viewports.

---

## 6. Public Showcase URL

Following deployment, the public website will be accessible at:

```
https://satyamshrivastav955-dotcom.github.io/face-blockchain-verification/
```
