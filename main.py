import os
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import uvicorn
from sqlalchemy import text

from db.models import engine
import db.models

from auth import oidc



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
                    user_db = db.models.get_postpaid_user(row[0])
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
                    prepaid_user = db.models.get_prepaid_user(row[0])
                    if prepaid_user:
                        db_users_prepaid.append(prepaid_user)
            # additionally load all prepaid users from the current user
            t = text("SELECT id, username, user_key, money, last_drink FROM users_prepaid WHERE postpaid_user_id = :user_db_id")
            result = conn.execute(t, {"user_db_id": user_db_id}).fetchall()
            if result:
                prepaid_users_from_curr_user = []
                for row in result:
                    prepaid_user = db.models.get_prepaid_user(row[0])
                    if prepaid_user:
                        prepaid_users_from_curr_user.append(prepaid_user)

    # load current user from database
    user_is_postpaid = get_is_postpaid(user_authentik)
    if user_is_postpaid:
        db_user = db.models.get_postpaid_user(user_db_id)
    else:
        db_user = db.models.get_prepaid_user(user_db_id)

    # get last drink for current user, if not less than 60 seconds ago
    last_drink = db.models.get_last_drink(user_db_id, user_is_postpaid, 60)

    most_used_drinks = db.models.get_most_used_drinks(user_db_id, user_is_postpaid, 3)
    most_used_drinks.append({"drink_type": "Sonstiges", "count": 0})  # ensure "Sonstiges" is in

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user_authentik,
        "users": users,
        "user_db_id": user_db_id,
        "db_user": db_user, 
        "db_users_prepaid": db_users_prepaid,
        "prepaid_users_from_curr_user": prepaid_users_from_curr_user,
        "last_drink": last_drink,
        "avail_drink_types": most_used_drinks,
    })

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

    user = db.models.get_postpaid_user_by_username(username)
    requested_user_id = user["id"]

    db.models.set_postpaid_user_money(requested_user_id, money*100)
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

    db.models.drink_postpaid_user(user_db_id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/payup")
def payup(request: Request, username: str = Form(...), money: float = Form(...)):
    """
    Handles the payment process for a postpaid user.
    This endpoint allows an authenticated admin user to record a payment for a specified user.
    It validates the admin's permissions, checks the validity of the username and payment amount,
    and updates the user's postpaid balance accordingly.
    Args:
        request (Request): The incoming HTTP request, containing session data.
        username (str): The username of the user whose balance is to be updated (form data).
        money (float): The amount of money to be paid (form data, must be between 0 and 1000).
    Raises:
        HTTPException: If the user is not authenticated as an admin (403).
        HTTPException: If the specified user is not found (404).
        HTTPException: If the payment amount is invalid (400).
        HTTPException: If the current user is not found in the session (404).
    Returns:
        RedirectResponse: Redirects to the home page ("/") with a 303 status code upon success.
    """
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = db.models.get_postpaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")
    if money < 0 or money > 1000:
        raise HTTPException(status_code=400, detail="Money must be between 0 and 1000")

    current_user_db_id = request.session.get("user_db_id")
    if not current_user_db_id:
        raise HTTPException(status_code=404, detail="Current user not found")

    db.models.payup_postpaid_user(current_user_db_id, user_db_id, int(money*100))

    return RedirectResponse(url="/", status_code=303)

@app.post("/toggle_activated_user_postpaid")
def toggle_activated_user_postpaid(request: Request, username: str = Form(...)):
    """
    Toggles the activation status of a postpaid user account.
    Args:
        request (Request): The incoming HTTP request, containing session information.
        username (str): The username of the postpaid user to toggle, provided via form data.
    Raises:
        HTTPException: If the user is not authenticated as an admin (status code 403).
        HTTPException: If the specified user is not found (status code 404).
    Returns:
        RedirectResponse: Redirects to the homepage ("/") with a 303 status code after toggling.
    """
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = db.models.get_postpaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    db.models.toggle_activate_postpaid_user(user_db_id)

    return RedirectResponse(url="/", status_code=303)


@app.post("/add_prepaid_user")
def add_prepaid_user(request: Request, username: str = Form(...), start_money: float = Form(...)):
    """
    Handles the creation of a new prepaid user account.
    This endpoint validates the current user's authentication and group membership,
    checks for the existence of the username among prepaid and postpaid users,
    validates the input parameters, creates the prepaid user, and deducts the starting
    money from the current user's postpaid balance.
    Args:
        request (Request): The incoming HTTP request, containing session data.
        username (str): The username for the new prepaid user (form field, required).
        start_money (float): The initial balance for the new prepaid user (form field, required).
    Raises:
        HTTPException: 
            - 403 if the current user is not authorized.
            - 404 if the current user is not found in the session.
            - 400 if the username is empty, already exists, or does not meet length requirements.
            - 400 if the start_money is not between 0 and 100.
    Returns:
        RedirectResponse: Redirects to the homepage ("/") with status code 303 upon successful creation.
    """
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
        db.models.get_postpaid_user_by_username(username)
        user_exists = True
        db.models.get_prepaid_user_by_username(username)
        user_exists = True
    except HTTPException:
        pass

    if user_exists:
        raise HTTPException(status_code=400, detail="User already exists")

    if start_money < 0 or start_money > 100:
        raise HTTPException(status_code=400, detail="Start money must be between 0 and 100")
    if len(username) < 3 or len(username) > 20:
        raise HTTPException(status_code=400, detail="Username must be between 3 and 20 characters")

    db.models.create_prepaid_user(username, active_user_db_id, int(start_money*100))

    prev_money = db.models.get_postpaid_user(active_user_db_id)["money"]
    db.models.set_postpaid_user_money(active_user_db_id, prev_money - int(start_money*100))

    return RedirectResponse(url="/", status_code=303)

@app.post("/drink_prepaid")
def drink_prepaid(request: Request):
    """
    Handles a prepaid drink request for a user.
    This function checks if the user is authenticated and has prepaid privileges.
    If the user is not found in the session or does not have prepaid access, it raises an HTTPException.
    If the user is valid and has prepaid access, it records the prepaid drink for the user in the database
    and redirects to the home page.
    Args:
        request (Request): The incoming HTTP request containing session data.
    Raises:
        HTTPException: If the user is not found in the session or does not have prepaid privileges.
    Returns:
        RedirectResponse: Redirects the user to the home page with a 303 status code.
    """
    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")
    user_authentik = request.session.get("user_authentik")
    if not user_authentik:
        raise HTTPException(status_code=404, detail="User not found")
    if not user_authentik["prepaid"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    db.models.drink_prepaid_user(user_db_id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/toggle_activated_user_prepaid")
def toggle_activated_user_prepaid(request: Request, username: str = Form(...)):
    """
    Toggle the activation status of a prepaid user account.
    This endpoint is restricted to users who are members of the ADMIN_GROUP.
    It retrieves the user by username, toggles their activation status, and redirects to the homepage.
    Args:
        request (Request): The incoming HTTP request, containing session data.
        username (str): The username of the prepaid user to toggle, provided via form data.
    Raises:
        HTTPException: If the user is not authenticated as an admin (403).
        HTTPException: If the specified user is not found (404).
    Returns:
        RedirectResponse: Redirects to the homepage with a 303 status code after toggling.
    """
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    user_db_id = db.models.get_prepaid_user_by_username(username)["id"]
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    db.models.toggle_activate_prepaid_user(user_db_id)

    return RedirectResponse(url="/", status_code=303)

@app.post("/add_money_prepaid_user")
def add_money_prepaid_user(request: Request, username: str = Form(...), money: float = Form(...)):
    """
    Handles the transfer of a specified amount of money from the currently logged-in postpaid user to a prepaid user.
    Args:
        request (Request): The incoming HTTP request containing session data.
        username (str): The username of the prepaid user to whom money will be added (provided via form data).
        money (float): The amount of money to transfer (provided via form data, must be between 0 and 100).
    Raises:
        HTTPException: 
            - 403 if the current user is not authorized (not in the required group).
            - 404 if the logged-in user or the prepaid user is not found.
            - 400 if the money amount is not within the allowed range.
    Returns:
        RedirectResponse: Redirects the user to the homepage ("/") with a 303 status code after a successful transfer.
    """
    curr_user_auth = request.session.get("user_authentik")
    if not curr_user_auth or FS_GROUP not in curr_user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    curr_user_db_id = request.session.get("user_db_id")
    if not curr_user_db_id:
        raise HTTPException(status_code=404, detail="Logged In User not found")

    prepaid_user_dict = db.models.get_prepaid_user_by_username(username)
    prepaid_user_db_id = prepaid_user_dict["id"]
    if not prepaid_user_db_id:
        raise HTTPException(status_code=404, detail="Prepaid User not found")

    if money < 0 or money > 100:
        raise HTTPException(status_code=400, detail="Money must be between 0 and 100")

    curr_user_money = db.models.get_postpaid_user(curr_user_db_id)["money"]
    prepaid_user_money = prepaid_user_dict["money"]

    db.models.set_postpaid_user_money(curr_user_db_id, curr_user_money - money*100)
    db.models.set_prepaid_user_money(prepaid_user_db_id, prepaid_user_money + money*100, curr_user_db_id)

    return RedirectResponse(url="/", status_code=303)

@app.post("/del_prepaid_user")
def delete_prepaid_user(request: Request, username: str = Form(...)):
    """
    Deletes a prepaid user from the system.
    This endpoint allows an admin user to delete a prepaid user by their username.
    It checks if the requester is part of the ADMIN_GROUP, retrieves the user to be deleted,
    and removes them from the database. If the user is not found or the requester is not authorized,
    an appropriate HTTPException is raised.
    Args:
        request (Request): The incoming HTTP request, containing session information.
        username (str): The username of the prepaid user to delete, provided via form data.
    Raises:
        HTTPException: If the requester is not authorized (status code 403).
        HTTPException: If the user to delete is not found (status code 404).
    Returns:
        RedirectResponse: Redirects to the homepage ("/") with status code 303 upon successful deletion.
    """
    # check if user is in ADMIN_GROUP
    user_auth = request.session.get("user_authentik")
    if not user_auth or ADMIN_GROUP not in user_auth["groups"]:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")

    user_to_del = db.models.get_prepaid_user_by_username(username)
    if not user_to_del["id"]:
        raise HTTPException(status_code=404, detail="User not found")

    db.models.del_user_prepaid(user_to_del["id"])

    return RedirectResponse(url="/", status_code=303)

@app.post("/del_last_drink")
def del_last_drink(request: Request):
    """
    Handles the deletion (reversion) of the last drink entry for the currently authenticated user.
    Args:
        request (Request): The incoming HTTP request containing session data.
    Raises:
        HTTPException: If the user is not found in the session.
    Returns:
        RedirectResponse: Redirects to the homepage ("/") after attempting to revert the last drink.
    """
    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")
    user_authentik = request.session.get("user_authentik")
    if not user_authentik:
        raise HTTPException(status_code=404, detail="User not found")

    last_drink = db.models.get_last_drink(user_db_id, True, 60)
    if not last_drink:
        return RedirectResponse(url="/", status_code=303)

    user_is_postpaid = get_is_postpaid(user_authentik)

    db.models.revert_last_drink(user_db_id, user_is_postpaid, last_drink["id"])

    return RedirectResponse(url="/", status_code=303)

@app.post("/update_drink_post")
def update_drink_post(request: Request, drink_type: str = Form(...)):
    """
    Handles a POST request to update the type of the user's last drink.
    Args:
        request (Request): The incoming HTTP request containing session data.
        drink_type (str, optional): The new type of drink to set, provided via form data.
    Raises:
        HTTPException: If the user is not found in the session or if the drink type is empty.
    Returns:
        RedirectResponse: Redirects to the home page after updating the drink type, or if no last drink is found.
    """
    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    user_authentik = request.session.get("user_authentik")
    if not user_authentik:
        raise HTTPException(status_code=404, detail="User not found")

    last_drink = db.models.get_last_drink(user_db_id, True, 60)
    if not last_drink:
        return RedirectResponse(url="/", status_code=303)

    if not drink_type:
        raise HTTPException(status_code=400, detail="Drink type is empty")

    db.models.update_drink_type(user_db_id, get_is_postpaid(user_authentik), last_drink["id"], drink_type)

    return RedirectResponse(url="/", status_code=303)

@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    """
    Handles the statistics page request for authenticated admin users.
    Args:
        request (Request): The incoming HTTP request object containing session data.
    Raises:
        HTTPException: If the user is not authenticated as an admin (403).
        HTTPException: If the user's database ID is not found in the session (404).
    Returns:
        TemplateResponse: Renders the "stats.html" template with user and drink type statistics.
    """
    user_authentik = request.session.get("user_authentik")
    if not user_authentik or ADMIN_GROUP not in user_authentik["groups"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    user_db_id = request.session.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=404, detail="User not found")

    drink_types = db.models.get_stats_drink_types()

    return templates.TemplateResponse("stats.html", {
        "request": request,
        "user": user_authentik,
        "user_db_id": user_db_id,
        "stats_drink_types": drink_types,
    })


def get_is_postpaid(user_authentik: dict) -> bool:
    """
    Determine if a user is postpaid based on their authentication information.
    Args:
        user_authentik (dict): A dictionary containing user authentication data, expected to have a 'prepaid' key.
    Returns:
        bool: True if the user is postpaid, False if the user is prepaid. If the 'prepaid' key is missing, defaults to True (postpaid).
    """
    try:
        if user_authentik["prepaid"]:
            user_is_postpaid = False
        else:
            user_is_postpaid = True
    except KeyError:
        user_is_postpaid = True
    return user_is_postpaid

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
