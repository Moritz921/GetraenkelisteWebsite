"""
This module handles OpenID Connect (OIDC) authentication using FastAPI and Authlib.
Routes:
    /login/oidc (GET): Initiates the OIDC login flow by redirecting the user to the identity provider's authorization endpoint.
    /authorize (ANY): Handles the callback from the identity provider, exchanges the authorization code for tokens, retrieves user profile information, stores it in the session, and ensures the user exists in the database.
    /logout (GET): Logs the user out by clearing session data and redirecting to the identity provider's logout endpoint.
Environment Variables:
    OIDC_CLIENT_ID: The client ID for the OIDC application.
    OIDC_CLIENT_SECRET: The client secret for the OIDC application.
    OIDC_CONFIG_URL: The OIDC discovery document URL.
    OIDC_REDIRECT_URL: The redirect URI registered with the OIDC provider.
    OIDC_LOGOUT_URL: The logout endpoint URL (optional fallback).
Dependencies:
    - FastAPI
    - Authlib
    - SQLAlchemy
    - python-dotenv
    - Starlette
Session Keys:
    SESSION_KEY: Key for storing user profile information in the session ("user_authentik").
    "user_db_id": Key for storing the user's database ID in the session.
Database:
    Uses SQLAlchemy to check for and create users in the 'users_postpaid' table.
Functions:
    login(request): Starts the OIDC login process.
    authorize(request): Handles the OIDC callback, processes user info, and manages user records.
    logout(request): Logs the user out and redirects to the identity provider's logout endpoint.
"""
import os
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from sqlalchemy import text

from dotenv import load_dotenv

from db.models import (
    engine,
    create_postpaid_user,
)

oauth = OAuth()
router = APIRouter()
SESSION_KEY = "user_authentik"


load_dotenv()

oauth.register(
    name="auth0",
    client_id=os.getenv("OIDC_CLIENT_ID"),
    client_secret=os.getenv("OIDC_CLIENT_SECRET"),
    server_metadata_url=os.getenv("OIDC_CONFIG_URL"),
    client_kwargs={
        "scope": "openid email profile"
    },
)

@router.get("/login/oidc")
async def login(request: Request):
    """
    Initiates the OAuth2 login flow using Auth0 and redirects the user to the Auth0 authorization endpoint.
    Args:
        request (Request): The incoming HTTP request object.
    Returns:
        Response: A redirect response to the Auth0 authorization URL.
    Raises:
        Exception: If the Auth0 client cannot be created or the redirect fails.
    Environment Variables:
        OIDC_REDIRECT_URL: The URL to which Auth0 should redirect after authentication.
    """

    auth0_client = oauth.create_client("auth0")
    redirect_uri = os.getenv("OIDC_REDIRECT_URL")
    return await auth0_client.authorize_redirect(request, redirect_uri)

@router.route("/authorize")
async def authorize(request: Request):
    """
    Handles the OAuth2 authorization callback, retrieves the user's profile from the identity provider,
    stores user information in the session, checks if the user exists in the database (and creates them if not),
    and redirects to the home page.
    Args:
        request (Request): The incoming HTTP request containing the OAuth2 callback.
    Returns:
        RedirectResponse: A redirect response to the home page after successful authorization and user handling.
    Side Effects:
        - Stores user profile and database user ID in the session.
        - May create a new user in the database if not already present.
    """

    token = await oauth.auth0.authorize_access_token(request)
    userinfo_endpoint = oauth.auth0.server_metadata.get("userinfo_endpoint")
    resp = await oauth.auth0.get(userinfo_endpoint, token=token)
    resp.raise_for_status()
    profile = resp.json()

    # save user info in session
    request.session[SESSION_KEY] = profile

    # check if user is already in the database
    with engine.connect() as conn:
        t = text("SELECT id FROM users_postpaid WHERE username = :username")
        result = conn.execute(t, {"username": profile["preferred_username"]}).fetchone()
        if result:
            user_db_id = result[0]
        else:
            print("Create User in DB")
            user_db_id = create_postpaid_user(profile["preferred_username"])

    request.session["user_db_id"] = user_db_id
    return RedirectResponse(url="/", status_code=303)

@router.get("/logout")
async def logout(request: Request):
    """
    Logs out the current user by clearing session data and redirecting to the OIDC provider's logout endpoint.
    Args:
        request (Request): The incoming HTTP request containing the user's session.
    Returns:
        RedirectResponse: A response that redirects the user to the OIDC provider's logout URL with a 303 status code.
    Notes:
        - Removes the authentication session key and user database information from the session.
        - Determines the logout URL from the OIDC provider's metadata or an environment variable.
    """

    request.session.pop(SESSION_KEY, None)
    request.session.pop("user_db", None)
    logout_url = oauth.auth0.server_metadata.get("end_session_endpoint")
    if not logout_url:
        logout_url = os.getenv("OIDC_LOGOUT_URL")
    return RedirectResponse(url=logout_url, status_code=303)
