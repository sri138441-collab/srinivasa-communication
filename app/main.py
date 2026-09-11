from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone
import json
import threading
import time
import re

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data" / "alerts.json"
META = BASE / "data" / "sync.json"
DATA.parent.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(BASE / "app" / "templates"))
app = FastAPI(title="Srinivasa Communication Job Alert")

CATEGORIES = [
    "Latest Jobs", "Government Jobs", "Private Jobs", "Admit Card",
    "Results", "Admissions", "Answer Key", "Exam Dates", "Scholarships"
]

SOURCES = [
    ("Latest Jobs", "https://www.freejobalert.com/latest-notifications/", [
        "online form", "recruitment", "vacancy", "various posts", "apprentice",
        "officer", "assistant", "engineer", "constable", "teacher", "jobs"
    ]),
    ("New Updates", "https://www.freejobalert.com/new-updates/", [
        "online form", "recruitment", "result", "admit card", "answer key", "syllabus",
        "vacancy", "posts", "notification"
    ]),
    ("Admit Card", "https://www.freejobalert.com/admit-card/", [
        "admit card", "hall ticket", "call letter", "city intimation"
    ]),
    ("Results", "https://www.freejobalert.com/exam-results/", [
        "result", "scorecard", "merit list", "cutoff", "cut-off"
    ]),
    ("Admissions", "https://www.freejobalert.com/new-edu-updates/", [
        "admission", "counselling", "counseling", "seat allotment", "neet", "cet",
        "entrance", "allotment", "registration"
    ]),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SrinivasaCommunication/1.0)"}


def load():
    try:
        value = json.loads(DATA.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def save(items):
    DATA.write_text(json.dumps(items[:500], indent=2, ensure_ascii=False), encoding="utf-8")


def set_sync_status(ok=True, message=""):
    META.write_text(json.dumps({
        "ok": ok,
        "message": message,
        "time": datetime.now(timezone.utc).isoformat()
    }), encoding="utf-8")


def sync_status():
    try:
        return json.loads(META.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "message": "Automatic sync has not run yet.", "time": ""}


def clean_title(text):
    return re.sub(r"\s+", " ", text or "").strip()


def should_keep(title, href, keywords):
    low = title.lower()
    if not title or len(title) < 12:
        return False
    if href.startswith("#"):
        return False
    if any(x in href.lower() for x in ["/category/", "/author/", "/page/", "/tag/", "/search"]):
        return False
    return any(k in low for k in keywords)


def scrape_source(category, page_url, keywords):
    response = requests.get(page_url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found = []
    seen = set()
    for a in soup.select("a[href]"):
        title = clean_title(a.get_text(" ", strip=True))
        href = a.get("href", "").strip()
        if href.startswith("/"):
            href = "https://www.freejobalert.com" + href
        if not href.startswith("https://www.freejobalert.com/"):
            continue
        if href in seen or not should_keep(title, href, keywords):
            continue
        seen.add(href)
        # Do not copy article text; store only the title and source/detail URL.
        found.append({
            "title": title,
            "category": category,
            "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
            "source": "FreeJobAlert",
            "url": href,
            "description": "Latest update detected from the public source page. Open the source for full details and the official application/result link."
        })
        if len(found) >= 25:
            break
    return found


def sync():
    items = load()
    existing = {x.get("url") for x in items if x.get("url")}
    total = 0
    errors = []
    for category, page_url, keywords in SOURCES:
        try:
            new_items = scrape_source(category, page_url, keywords)
            for item in reversed(new_items):
                if item["url"] not in existing:
                    items.insert(0, item)
                    existing.add(item["url"])
                    total += 1
        except Exception as exc:
            errors.append(f"{category}: {type(exc).__name__}")
    save(items)
    if errors and total == 0:
        set_sync_status(False, "Automatic sources could not be reached: " + ", ".join(errors))
    elif errors:
        set_sync_status(True, f"Added {total} updates. Some sources failed: " + ", ".join(errors))
    else:
        set_sync_status(True, f"Automatic sync completed. Added {total} new updates.")
    return total


def maybe_sync():
    status = sync_status()
    last = status.get("time", "")
    try:
        last_dt = datetime.fromisoformat(last)
        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
    except Exception:
        age = 10**9
    if age > 600:
        try:
            sync()
        except Exception as exc:
            set_sync_status(False, f"Automatic sync error: {type(exc).__name__}")


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", category: str = ""):
    maybe_sync()
    items = load()
    if q:
        needle = q.lower()
        items = [x for x in items if needle in (x.get("title", "") + " " + x.get("description", "")).lower()]
    if category:
        items = [x for x in items if x.get("category") == category]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "items": items,
        "categories": CATEGORIES,
        "q": q,
        "category": category,
        "sync": sync_status(),
    })


@app.post("/admin/add")
def add(title: str = Form(...), category: str = Form(...), url: str = Form(...), source: str = Form(...), description: str = Form("")):
    items = load()
    items.insert(0, {
        "title": title,
        "category": category,
        "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
        "source": source or "Official Website",
        "url": url,
        "description": description,
    })
    save(items)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/refresh")
def refresh():
    sync()
    return RedirectResponse("/", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "updates": len(load()), "sync": sync_status()}


@app.on_event("startup")
def startup():
    DATA.parent.mkdir(exist_ok=True)
    if not DATA.exists():
        save([])
    if not META.exists():
        set_sync_status(False, "Automatic sync has not run yet.")

    def worker():
        while True:
            try:
                sync()
            except Exception as exc:
                set_sync_status(False, f"Background sync error: {type(exc).__name__}")
            time.sleep(900)

    threading.Thread(target=worker, daemon=True).start()
