# Srinivasa Communication Job Alert
Render-ready FastAPI project inspired by the requested job-alert layout.
Run: `uvicorn app.main:app --reload --port 8000`
Render: Docker deploy. Health endpoint: `/health`.
Automatic RSS refresh runs every 30 minutes. Replace/add feeds only where you have permission to consume them. Protect the admin endpoint with authentication before public production use.
