import random

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
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
from db.models import drink_prepaid_user
from db.models import toggle_activate_prepaid_user
from db.models import set_prepaid_user_money
from db.models import del_user_prepaid

from auth import oidc
import os
from dotenv import load_dotenv



ADMIN_GROUP = "Getraenkeliste Verantwortliche"
FS_GROUP = "Getraenkeliste Postpaid"

app = FastAPI()
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "my_secret_key")

app.add_middleware(SessionMiddleware, secret_key=str(SECRET_KEY))
app.include_router(oidc.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    
    # Check if user is logged in and has a valid session
    user_db_id = request.session.get("user_db_id")
    user_authentik = request.session.get("user_authentik")
    if not user_db_id or not user_authentik:
        return RedirectResponse(url="/login", status_code=303)

    user_db_id = request.session.get("user_db_id")
    user_authentik = request.session.get("user_authentik")
    if not user_db_id or not user_authentik:
        raise HTTPException(status_code=404, detail="User not found")

    # if user is Admin, load all postpaid users
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

    # if user is in Fachschaft, load all prepaid users
    prepaid_users_from_curr_user = []
    if FS_GROUP in user_authentik["groups"]:
        with engine.connect() as conn:
            t = text("SELECT id FROM users_prepaid")
            result = conn.execute(t).fetchall()
            if result:
                db_users_prepaid = []
                for row in result:
                    prepaid_user = get_prepaid_user(row[0])
                    if prepaid_user:
                        db_users_prepaid.append(prepaid_user)
            # additionally load all prepaid users from the current user
            t = text("SELECT id, username, user_key, money, last_drink FROM users_prepaid WHERE postpaid_user_id = :user_db_id")
            result = conn.execute(t, {"user_db_id": user_db_id}).fetchall()
            if result:
                prepaid_users_from_curr_user = []
                for row in result:
                    prepaid_user = get_prepaid_user(row[0])
                    if prepaid_user:
                        prepaid_users_from_curr_user.append(prepaid_user)

    # load current user from database
    try:
        if user_authentik["prepaid"]:
            db_user = get_prepaid_user(user_db_id)
        else:
            db_user = get_postpaid_user(user_db_id)
    except KeyError:
        db_user = get_postpaid_user(user_db_id)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user_authentik,
        "users": users,
        "user_db_id": user_db_id,
        "db_user": db_user, 
        "db_users_prepaid": db_users_prepaid,
        "prepaid_users_from_curr_user": prepaid_users_from_curr_user,})

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

    user = get_postpaid_user_by_username(username)
    requested_user_id = user["id"]

    set_postpaid_user_money(requested_user_id, money*100)
    return RedirectResponse(url="/", status_code=303)

@app.post("/drink")
async def drink(request: Request):
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
    if not user_authentik or FS_GROUP not in user_authentik["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    form = await request.form()
    getraenk = str(form.get("getraenk"))
    print(f"User {user_authentik['preferred_username']} requested drink: {getraenk}")

    drink_postpaid_user(user_db_id, getraenk)
    return RedirectResponse(url="/", status_code=303)

@app.post("/payup")
def payup(request: Request, username: str = Form(...), money: float = Form(...)):
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = get_postpaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")
    if money < 0 or money > 1000:
        raise HTTPException(status_code=400, detail="Money must be between 0 and 1000")

    curr_user_money = get_postpaid_user(user_db_id)["money"]
    set_postpaid_user_money(user_db_id, curr_user_money + money*100)

    current_user_db_id = request.session.get("user_db_id")
    if not current_user_db_id:
        raise HTTPException(status_code=404, detail="Current user not found")
    current_user_money = get_postpaid_user(current_user_db_id)["money"]
    set_postpaid_user_money(current_user_db_id, current_user_money - money*100)
    return RedirectResponse(url="/", status_code=303)

@app.post("/toggle_activated_user_postpaid")
def toggle_activated_user_postpaid(request: Request, username: str = Form(...)):
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = get_postpaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    toggle_activate_postpaid_user(user_db_id)

    return RedirectResponse(url="/", status_code=303)


@app.post("/add_prepaid_user")
def add_prepaid_user(request: Request, username: str = Form(...), start_money: float = Form(...)):
    active_user_auth = request.session.get("user_authentik")
    active_user_db_id = request.session.get("user_db_id")
    if not active_user_auth or FS_GROUP not in active_user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    if not active_user_db_id:
        raise HTTPException(status_code=404, detail="Current user not found")
    if not username:
        raise HTTPException(status_code=400, detail="Username is empty")

    user_exists = False
    try:
        get_postpaid_user_by_username(username)
        user_exists = True
        get_prepaid_user_by_username(username)
        user_exists = True
    except HTTPException:
        pass

    if user_exists:
        raise HTTPException(status_code=400, detail="User already exists")

    if start_money < 0 or start_money > 100:
        raise HTTPException(status_code=400, detail="Start money must be between 0 and 100")
    if len(username) < 3 or len(username) > 20:
        raise HTTPException(status_code=400, detail="Username must be between 3 and 20 characters")

    create_prepaid_user(username, active_user_db_id, int(start_money*100))

    prev_money = get_postpaid_user(active_user_db_id)["money"]
    set_postpaid_user_money(active_user_db_id, prev_money - int(start_money*100))

    return RedirectResponse(url="/", status_code=303)

@app.post("/drink_prepaid")
def drink_prepaid(request: Request):
    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")
    user_authentik = request.session.get("user_authentik")
    if not user_authentik:
        raise HTTPException(status_code=404, detail="User not found")
    if not user_authentik["prepaid"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    drink_prepaid_user(user_db_id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/toggle_activated_user_prepaid")
def toggle_activated_user_prepaid(request: Request, username: str = Form(...)):
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = get_prepaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    toggle_activate_prepaid_user(user_db_id)

    return RedirectResponse(url="/", status_code=303)

@app.post("/add_money_prepaid_user")
def add_money_prepaid_user(request: Request, username: str = Form(...), money: float = Form(...)):
    curr_user_auth = request.session.get("user_authentik")
    if not curr_user_auth or FS_GROUP not in curr_user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    curr_user_db_id = request.session.get("user_db_id")
    if not curr_user_db_id:
        raise HTTPException(status_code=404, detail="Logged In User not found")

    prepaid_user_dict = get_prepaid_user_by_username(username)
    prepaid_user_db_id = prepaid_user_dict["id"]
    if not prepaid_user_db_id:
        raise HTTPException(status_code=404, detail="Prepaid User not found")

    if money < 0 or money > 100:
        raise HTTPException(status_code=400, detail="Money must be between 0 and 100")

    curr_user_money = get_postpaid_user(curr_user_db_id)["money"]
    prepaid_user_money = prepaid_user_dict["money"]

    set_postpaid_user_money(curr_user_db_id, curr_user_money - money*100)
    set_prepaid_user_money(prepaid_user_db_id, prepaid_user_money + money*100, curr_user_db_id)

    return RedirectResponse(url="/", status_code=303)

@app.post("/del_prepaid_user")
def delete_prepaid_user(request: Request, username: str = Form(...)):
    # check if user is in ADMIN_GROUP
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")

    user_to_del = get_prepaid_user_by_username(username)
    if not user_to_del["id"]:
        raise HTTPException(status_code=404, detail="User not found")

    del_user_prepaid(user_to_del["id"])

    return RedirectResponse(url="/", status_code=303)

@app.get("/popup_getraenke")
async def popup_getraenke():
    alle_getraenke = ["Wasser", "Cola", "Bier", "Mate", "Saft", "Tee", "Kaffee", "Limo"]
    return JSONResponse(content={"getraenke": random.sample(alle_getraenke, 4)})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
