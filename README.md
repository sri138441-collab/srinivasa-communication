# Srinivasa Communication Job Alert

Render-ready FastAPI job-alert website. It fetches current public update listings from configured source pages when the site is opened or when **Refresh Now** is pressed.

## Sources
- FreeJobAlert latest notifications
- FreeJobAlert new updates
- FreeJobAlert admit cards
- FreeJobAlert exam results
- FreeJobAlert education updates

The site stores only notification titles and source/detail URLs; users should open the source page for full details and official application/result links.

## Render
Use Docker runtime and deploy from the repository root. `Dockerfile` is at the repository root.

## Important Render note
Render Free web services have an ephemeral filesystem and can spin down when idle. The app therefore re-syncs when a visitor opens it. For true scheduled 24/7 background fetching independent of visitors, use a paid Render Cron Job or an external scheduler.
