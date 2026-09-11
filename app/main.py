from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import json, threading, time, feedparser
from datetime import datetime

BASE=Path(__file__).resolve().parent.parent
DATA=BASE/"data"/"alerts.json"
DATA.parent.mkdir(parents=True, exist_ok=True)
templates=Jinja2Templates(directory=str(BASE/"app"/"templates"))
app=FastAPI(title="Srinivasa Communication Job Alert")
CATEGORIES=["Latest Jobs","Government Jobs","Private Jobs","Admit Card","Results","Admissions","Answer Key","Exam Dates","Scholarships"]
FEEDS=[("FreeJobAlert","https://www.freejobalert.com/rss/"),("Sarkari Result","https://www.sarkariresult.com/rss.xml")]

def load():
    try: return json.loads(DATA.read_text())
    except: return []
def save(x): DATA.write_text(json.dumps(x,indent=2,ensure_ascii=False))

@app.get("/",response_class=HTMLResponse)
def home(request:Request,q:str="",category:str=""):
    items=load()
    if q: items=[x for x in items if q.lower() in (x.get("title","")+" "+x.get("description","")).lower()]
    if category: items=[x for x in items if x.get("category")==category]
    return templates.TemplateResponse("index.html",{"request":request,"items":items,"categories":CATEGORIES,"q":q,"category":category})

@app.post("/admin/add")
def add(title:str=Form(...),category:str=Form(...),url:str=Form(...),source:str=Form(...),description:str=Form("")):
    items=load()
    items.insert(0,{"title":title,"category":category,"date":datetime.now().strftime("%d-%m-%Y %I:%M %p"),"source":source or "Official Website","url":url,"description":description})
    save(items); return RedirectResponse("/",status_code=303)

@app.post("/admin/refresh")
def refresh():
    sync(); return RedirectResponse("/",status_code=303)

def sync():
    items=load(); existing={x.get("url") for x in items}
    for name,url in FEEDS:
        try:
            feed=feedparser.parse(url)
            for e in feed.entries[:15]:
                link=e.get("link","#")
                if link not in existing:
                    items.insert(0,{"title":e.get("title","New Update"),"category":"Latest Jobs","date":datetime.now().strftime("%d-%m-%Y %I:%M %p"),"source":name,"url":link,"description":e.get("summary","")[:500]})
                    existing.add(link)
        except Exception: pass
    save(items)

@app.get("/health")
def health(): return {"status":"ok"}

@app.on_event("startup")
def startup():
    DATA.parent.mkdir(exist_ok=True)
    if not DATA.exists(): save([])
    def worker():
        while True:
            sync(); time.sleep(1800)
    threading.Thread(target=worker,daemon=True).start()
