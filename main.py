from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import uvicorn
from sqlalchemy import text

from db.models import engine
from db.models import get_postpaid_user
from db.models import get_postpaid_user_by_username
from db.models import set_postpaid_user_money
from db.models import drink_postpaid_user
from db.models import toggle_activate_postpaid_user
from db.models import get_prepaid_user
from db.models import get_prepaid_user_by_username
from db.models import create_prepaid_user

from auth.session import get_current_user

from auth import oidc



ADMIN_GROUP = "Fachschaft Admins"

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="my_secret_key")
app.include_router(oidc.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user_db_id = request.session.get("user_db_id")
    user_authentik = request.session.get("user_authentik")
    if not user_db_id or not user_authentik:
        return RedirectResponse(url="/login", status_code=303)

    user_db_id = request.session.get("user_db_id")
    user_authentik = request.session.get("user_authentik")
    if not user_db_id or not user_authentik:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    users = None
    db_users_prepaid = None
    if ADMIN_GROUP in user_authentik["groups"]:
        with engine.connect() as conn:
            t = text("SELECT id FROM users_postpaid")
            result = conn.execute(t).fetchall()
            if result:
                users = []
                for row in result:
                    user_db = get_postpaid_user(row[0])
                    if user_db:
                        users.append(user_db)
            t = text("SELECT id FROM users_prepaid")
            result = conn.execute(t).fetchall()
            print(f"Result: {result}")
            if result:
                db_users_prepaid = []
                for row in result:
                    prepaid_user = get_prepaid_user(row[0])
                    if prepaid_user:
                        db_users_prepaid.append(prepaid_user)
    db_user = get_postpaid_user(user_db_id)
    print("db_users_prepaid", db_users_prepaid)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user_authentik,
        "users": users,
        "user_db_id": user_db_id,
        "db_user": db_user, 
        "db_users_prepaid": db_users_prepaid})

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    """
    Renders the login form template.
    Args:
        request (Request): The incoming HTTP request object.
    Returns:
        TemplateResponse: The rendered login.html template with the request context.
    """
    
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/set_money_postpaid")
def set_money_postpaid(request: Request, username = Form(...), money: float = Form(...)):
    """
    Handles a POST request to set the postpaid money balance for a specified user.
    Args:
        request (Request): The incoming HTTP request, containing session information for authentication.
        username (str, Form): The username of the user whose postpaid balance is to be set (provided via form data).
        money (float, Form): The new balance amount to set for the user (provided via form data).
    Raises:
        HTTPException: 
            - 403 if the current user is not authenticated as an admin.
            - 404 if the specified user does not exist.
    Returns:
        RedirectResponse: Redirects to the home page ("/") with a 303 status code upon successful update.
    """

    user_authentik = request.session.get("user_authentik")
    if not user_authentik or ADMIN_GROUP not in user_authentik["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")

    with engine.connect() as conn:
        t = text("SELECT id FROM users_postpaid WHERE username = :username")
        result = conn.execute(t, {"username": username}).fetchone()
        if result:
            requested_user_id = result[0]
        else:
            raise HTTPException(status_code=404, detail="User nicht gefunden")

    set_postpaid_user_money(requested_user_id, money*100)
    return RedirectResponse(url="/", status_code=303)

@app.post("/drink")
def drink(request: Request):
    """
    Handles a drink purchase request for a user.
    Checks if the user is authenticated and belongs to the admin group. If not, raises a 403 error.
    Verifies that the user's database ID is present in the session; if not, raises a 404 error.
    Retrieves the current user's balance and processes the drink purchase.
    Redirects the user to the homepage after processing.
    Args:
        request (Request): The incoming HTTP request containing session data.
    Raises:
        HTTPException: If the user is not authenticated as an admin (403).
        HTTPException: If the user's database ID is not found in the session (404).
    Returns:
        RedirectResponse: Redirects to the homepage after processing the drink purchase.
    """

    user_authentik = request.session.get("user_authentik")
    if not user_authentik or ADMIN_GROUP not in user_authentik["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")

    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    drink_postpaid_user(user_db_id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/payup")
def payup(request: Request, username: str = Form(...), money: float = Form(...)):
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")

    user_db_id = get_postpaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    curr_user_money = get_postpaid_user(user_db_id)["money"]
    set_postpaid_user_money(user_db_id, curr_user_money + money*100)

    current_user_db_id = request.session.get("user_db_id")
    if not current_user_db_id:
        raise HTTPException(status_code=404, detail="Aktueller User nicht gefunden")
    current_user_money = get_postpaid_user(current_user_db_id)["money"]
    set_postpaid_user_money(current_user_db_id, current_user_money - money*100)
    return RedirectResponse(url="/", status_code=303)

@app.post("/toggle_activated_user_postpaid")
def toggle_activated_user_postpaid(request: Request, username: str = Form(...)):
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")

    user_db_id = get_postpaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    toggle_activate_postpaid_user(user_db_id)

    return RedirectResponse(url="/", status_code=303)


@app.post("/add_prepaid_user")
def add_prepaid_user(request: Request, username: str = Form(...), start_money: float = Form(...)):
    active_user_auth = request.session.get("user_authentik")
    active_user_db_id = request.session.get("user_db_id")
    if not active_user_auth or ADMIN_GROUP not in active_user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    if not active_user_db_id:
        raise HTTPException(status_code=404, detail="Aktueller User nicht gefunden")
    if not username:
        raise HTTPException(status_code=400, detail="Username ist leer")

    user_exists = False
    try:
        get_postpaid_user_by_username(username)
        user_exists = True
        get_prepaid_user_by_username(username)
        user_exists = True
    except HTTPException:
        pass

    if user_exists:
        raise HTTPException(status_code=400, detail="User existiert bereits")

    create_prepaid_user(username, active_user_db_id, int(start_money*100))

    prev_money = get_postpaid_user(active_user_db_id)["money"]
    set_postpaid_user_money(active_user_db_id, prev_money - int(start_money*100))

    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
