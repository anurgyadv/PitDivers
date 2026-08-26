# PitDivers console frontend

React + TypeScript dashboard for the PitDivers rover vision console, built with
Vite, Tailwind CSS v4, Framer Motion, Recharts, and Lucide icons. The visual
language is an "elevated dark console": layered glass panels, an amber rover
accent, spring-based motion, and animated pop-out windows.

## Commands

```bash
npm install     # once
npm run dev     # hot-reload dev server on :5173, proxies /api to :8765
npm run build   # type-check + production build into dist/
npm run preview # serve the production build locally
```

FastAPI (`webapp/app.py`) serves `dist/index.html` at the catch-all route and
mounts `dist/assets` at `/assets`. The build in `dist/` is committed so the
Python-only launcher can serve it without Node; rebuild and commit it whenever
you change anything under `src/`.

## Layout

| Path | Purpose |
|---|---|
| `src/lib/` | API client, shared types, formatting helpers |
| `src/hooks/` | React Query polling hooks + sensor history |
| `src/components/ui/` | Design-system primitives (buttons, modal, toasts, forms) |
| `src/components/live/` | Live-tab widgets (streams, metrics, charts) |
| `src/components/modals/` | Photo, reconstruct, 3D viewer, lightbox dialogs |
| `src/pages/` | Live, Captures, 3D Models, DA3 Models screens |
| `src/index.css` | Tailwind theme tokens and console styling |

All dependencies are bundled locally at build time — the app makes no external
network requests, matching the offline/no-login constraints of the dashboard.
The 3D viewer (`@google/model-viewer`) is code-split so its Three.js payload
loads only when a scene is opened.
