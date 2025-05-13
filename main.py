from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from db.models import Base, engine, get_db, User

from auth.session import get_current_user

from auth import oidc

import uvicorn
from sqlalchemy.orm import Session


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="my_secret_key")
app.include_router(oidc.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# DB
Base.metadata.create_all(bind=engine)

@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    db_user = db.query(User).filter_by(username=user["preferred_username"]).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    users = None
    if "Fachschaft Admins" in user["groups"]:
        users = db.query(User).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "users": users, "db_user": db_user})

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/set_money")
def set_money(request: Request, username: str = Form(...), money: float = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user or "Fachschaft Admins" not in user["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    db_user = db.query(User).filter_by(username=username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    db_user.money = money*100
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/drink")
def drink(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user or "Fachschaft" not in user["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    db_user = db.query(User).filter_by(username=user["preferred_username"]).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    db_user.money -= 100
    db.commit()
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
