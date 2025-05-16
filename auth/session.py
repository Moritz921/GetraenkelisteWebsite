"""
This module provides session management utilities for postpaid users in a FastAPI application.
It includes functions to log in a user by username, log out the current user, and retrieve the
currently logged-in user from the session.

Functions:
    login_postpaid_user(request: Request, username: str):
        Raises HTTPException if the user is not found.

    logout_user(request: Request):

    get_current_user(request: Request):
        Retrieves the current user from the session, returning the user object if present.
"""
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import text

from db.models import engine, get_postpaid_user


SESSION_KEY = "user_db_id"


def login_postpaid_user(request: Request, username: str):
    """
    Logs in a postpaid user by their username and stores their user ID in the session.
    Args:
        request (Request): The incoming HTTP request object, which contains the session.
        username (str): The username of the postpaid user to log in.
    Returns:
        int or None: The user ID if the user is found and logged in; otherwise, None.
    Raises:
        HTTPException: If the user with the given username is not found (404 error).
    """

    t = text("SELECT id FROM users_postpaid WHERE username = :username")
    with engine.connect() as conn:
        result = conn.execute(t, {"username": username}).fetchone()
        if result:
            user_id = result[0]
        else:
            raise HTTPException(status_code=404, detail="User nicht gefunden")
    if user_id:
        request.session[SESSION_KEY] = user_id
        return user_id
    return None


def logout_user(request: Request):
    """
    Logs out the current user by removing their session data.
    This function removes the user's session key and any associated user database information
    from the session, effectively logging the user out.
    Args:
        request (Request): The incoming request object containing the session.
    Returns:
        None
    """

    request.session.pop(SESSION_KEY, None)
    request.session.pop("user_db", None)


def get_current_user(request: Request):
    """
    Retrieve the current user from the session in the given request.
    Args:
        request (Request): The incoming HTTP request containing the session.
    Returns:
        User or None: The user object associated with the session if present, otherwise None.
    """

    user_id = request.session.get(SESSION_KEY)
    if not user_id:
        return None
    user = get_postpaid_user(user_id)
    return user
