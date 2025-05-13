from fastapi import Depends, HTTPException
from starlette.requests import Request
from db.models import User, SessionLocal
from sqlalchemy.orm import Session

from starlette.requests import Request
from db.models import User, get_db
from sqlalchemy.orm import Session

SESSION_KEY = "user"


def login_user(request: Request, db: Session, username: str):
    user = db.query(User).filter(User.username == username).first()
    if user:
        request.session[SESSION_KEY] = user.id
        return user
    return None


def logout_user(request: Request):
    request.session.pop(SESSION_KEY, None)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get(SESSION_KEY)
    # if user_id is None:
    #     raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    # user = db.query(User).filter(User.id == user_id).first()
    user = user_id
    return user
