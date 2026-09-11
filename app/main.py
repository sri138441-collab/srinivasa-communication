from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SrinivasaCommunication/2.0)"}
FJA_HOSTS = {"freejobalert.com", "www.freejobalert.com"}
BAD_HOST_PARTS = {
    "facebook.com", "instagram.com", "youtube.com", "twitter.com", "x.com",
    "telegram.me", "t.me", "whatsapp.com", "google.com", "googletagmanager.com",
    "doubleclick.net", "ads.com"
}

# Safe, well-known official homepages used only when the detail page does not expose
# a direct official link. The detail-page link is always preferred.
OFFICIAL_FALLBACKS = [
    (r"\bssc\b|staff selection commission", "https://ssc.gov.in/"),
    (r"\bupsc\b|union public service commission", "https://upsc.gov.in/"),
    (r"\brrb\b|railway recruitment board", "https://www.rrbapply.gov.in/"),
    (r"\bsbi\b|state bank of india", "https://sbi.co.in/web/careers"),
    (r"\bibps\b", "https://www.ibps.in/"),
    (r"\bindia post\b|\bpost office\b|gds", "https://www.indiapost.gov.in/"),
    (r"\baiims\b", "https://www.aiimsexams.ac.in/"),
    (r"\bnta\b|neet|cuet", "https://www.nta.ac.in/"),
    (r"\bupsc\b", "https://upsc.gov.in/"),
    (r"\bupsssc\b", "https://upsssc.gov.in/"),
    (r"\buppsc\b", "https://uppsc.up.nic.in/"),
    (r"\bappsc\b", "https://psc.ap.gov.in/"),
    (r"\btslprb\b|telangana police", "https://www.tgprb.in/"),
    (r"\btspsc\b|telangana public service commission", "https://websitenew.tspsc.gov.in/"),
    (r"\bmpesb\b|madhya pradesh employees selection board", "https://esb.mp.gov.in/"),
    (r"\bmp psc\b|mppsc", "https://mppsc.mp.gov.in/"),
    (r"\bkerala psc\b|\bkpsc\b", "https://www.keralapsc.gov.in/"),
    (r"\brpsc\b|rajasthan public service commission", "https://rpsc.rajasthan.gov.in/"),
    (r"\bbpsc\b|bihar public service commission", "https://www.bpsc.bih.nic.in/"),
    (r"\bwbpsc\b", "https://psc.wb.gov.in/"),
    (r"\bup home guard\b", "https://uppbpb.gov.in/"),
]


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


def parse_display_date(value):
    if not value:
        return None
    for fmt in ("%d-%m-%Y %I:%M %p", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def extract_deadline(soup):
    text = clean_title(soup.get_text(" ", strip=True))
    # Prefer dates near common deadline labels.
    patterns = [
        r"(?:last date|closing date|application last date|online application last date|registration last date|apply before|ends on)\s*[:\-]?\s*(\d{1,2}[\/-]\d{1,2}[\/-]\d{4})",
        r"(?:last date|closing date|application last date|registration last date)\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if not m:
            continue
        raw = m.group(1).replace("/", "-")
        for fmt in ("%d-%m-%Y", "%d %B %Y", "%d %b %Y"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime("%d-%m-%Y")
            except ValueError:
                pass
    return ""


def should_keep(title, href, keywords):
    low = title.lower()
    if not title or len(title) < 12:
        return False
    if href.startswith("#"):
        return False
    if any(x in href.lower() for x in ["/category/", "/author/", "/page/", "/tag/", "/search"]):
        return False
    return any(k in low for k in keywords)


def host(url):
    return (urlparse(url).hostname or "").lower().replace("www.", "")


def looks_external(url):
    h = host(url)
    return bool(h) and h not in {"freejobalert.com"} and not any(bad in h for bad in BAD_HOST_PARTS)


def score_official_link(href, text, title):
    h = host(href)
    low = f"{text} {href} {title}".lower()
    score = 0
    if any(k in low for k in ["official website", "official site", "apply online", "apply now", "admit card", "download", "result", "registration", "application"]):
        score += 30
    if h.endswith(".gov.in") or ".gov.in" in h:
        score += 40
    if h.endswith(".nic.in") or ".nic.in" in h:
        score += 35
    if h.endswith(".ac.in") or ".ac.in" in h:
        score += 30
    if h.endswith(".edu.in"):
        score += 25
    if any(k in h for k in ["sbi.co.in", "ibps.in", "rrbapply.gov.in", "aiimsexams.ac.in"]):
        score += 25
    if any(k in h for k in ["freejobalert", "jobresulthub", "fresherslive", "testbook", "jagranjosh"]):
        score -= 100
    return score


def find_official_url(detail_url, title):
    """Find an official destination from the public detail page, never a FJA URL."""
    try:
        response = requests.get(detail_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        candidates = []
        for a in soup.select("a[href]"):
            href = urljoin(detail_url, a.get("href", "").strip())
            text = clean_title(a.get_text(" ", strip=True))
            if not href.startswith(("http://", "https://")) or not looks_external(href):
                continue
            # Ignore tracking/utility URLs and generic external pages.
            if any(x in href.lower() for x in ["mailto:", "javascript:", "/privacy", "/terms"]):
                continue
            candidates.append((score_official_link(href, text, title), href, text))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            if best[0] >= 20:
                return best[1]
    except Exception:
        pass

    combined = title.lower()
    for pattern, fallback in OFFICIAL_FALLBACKS:
        if re.search(pattern, combined, flags=re.I):
            return fallback
    return ""


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
        official_url = find_official_url(href, title)
        deadline = ""
        try:
            detail_response = requests.get(href, headers=HEADERS, timeout=12)
            detail_response.raise_for_status()
            deadline = extract_deadline(BeautifulSoup(detail_response.text, "html.parser"))
        except Exception:
            pass
        found.append({
            "title": title,
            "category": category,
            "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
            "deadline": deadline,
            "source": "Official Website" if official_url else "Official link pending",
            "url": official_url,
            "official_url": official_url,
            "source_url": href,
            "description": "Official website link automatically detected. Open the official website for the latest details and application/result/hall-ticket action."
                if official_url else
                "Official website link could not be detected automatically yet.",
        })
        if len(found) >= 25:
            break
    return found


def repair_existing_links():
    """Convert old records that still point to FreeJobAlert into official links."""
    items = load()
    changed = 0
    processed = 0
    for item in items:
        old = item.get("url", "")
        official = item.get("official_url", "")
        if official and host(official) not in FJA_HOSTS:
            continue
        detail = item.get("source_url") or old
        if not detail or host(detail) not in FJA_HOSTS:
            continue
        if processed >= 40:
            break
        processed += 1
        official = find_official_url(detail, item.get("title", ""))
        if official:
            item["official_url"] = official
            item["url"] = official
            item["source"] = "Official Website"
            item["description"] = "Official website link automatically detected. Open the official website for the latest details and application/result/hall-ticket action."
            changed += 1
        else:
            item["official_url"] = ""
            item["source_url"] = detail
            item["source"] = "Official link pending"
    if changed:
        save(items)
    return changed


def sync():
    items = load()
    existing = {x.get("source_url") or x.get("url") for x in items if x.get("source_url") or x.get("url")}
    total = 0
    errors = []
    for category, page_url, keywords in SOURCES:
        try:
            new_items = scrape_source(category, page_url, keywords)
            for item in reversed(new_items):
                key = item.get("source_url") or item.get("url")
                if key and key not in existing:
                    items.insert(0, item)
                    existing.add(key)
                    total += 1
        except Exception as exc:
            errors.append(f"{category}: {type(exc).__name__}")
    repaired = repair_existing_links()
    save(items)
    if errors and total == 0:
        set_sync_status(False, "Automatic sources could not be reached: " + ", ".join(errors))
    elif errors:
        set_sync_status(True, f"Added {total} updates and repaired {repaired} official links. Some sources failed: " + ", ".join(errors))
    else:
        set_sync_status(True, f"Automatic sync completed. Added {total} updates; repaired {repaired} official links.")
    return total


def is_closing_soon(item):
    deadline = item.get("deadline", "")
    if deadline:
        try:
            d = datetime.strptime(deadline, "%d-%m-%Y")
            days = (d.date() - datetime.now().date()).days
            return 0 <= days <= 7
        except ValueError:
            pass
    title = item.get("title", "").lower()
    return any(k in title for k in ["closing soon", "last date", "last day", "ends today", "apply before"])


def is_today(item):
    d = parse_display_date(item.get("date", ""))
    return bool(d and d.date() == datetime.now().date())


def is_new(item):
    d = parse_display_date(item.get("date", ""))
    return bool(d and (datetime.now() - d).total_seconds() <= 24 * 3600)


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
def home(request: Request, q: str = "", category: str = "", view: str = ""):
    maybe_sync()
    items = load()
    if q:
        needle = q.lower()
        items = [x for x in items if needle in (x.get("title", "") + " " + x.get("description", "")).lower()]
    if category:
        items = [x for x in items if x.get("category") == category]
    if view == "closing":
        items = [x for x in items if is_closing_soon(x)]
    elif view == "today":
        items = [x for x in items if is_today(x)]
    elif view == "new":
        items = [x for x in items if is_new(x)]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "items": items,
        "categories": CATEGORIES,
        "q": q,
        "category": category,
        "view": view,
        "sync": sync_status(),
    })


@app.post("/admin/add")
def add(title: str = Form(...), category: str = Form(...), url: str = Form(...), source: str = Form("Official Website"), description: str = Form("")):
    items = load()
    items.insert(0, {
        "title": title,
        "category": category,
        "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
        "source": source or "Official Website",
        "url": url,
        "official_url": url,
        "source_url": "",
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
