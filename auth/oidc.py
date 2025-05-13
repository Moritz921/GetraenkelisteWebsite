from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request

from dotenv import load_dotenv
import os

oauth = OAuth()
router = APIRouter()

# OIDC-Provider konfigurieren (hier als Beispiel Auth0)
# oauth.register(
#     name="auth0",
#     client_id="ZUZYpdYmqjMwdBDb2GdWWX4xkASNe2gsYqLlF9dy",
#     client_secret="o6LXTspeaiAMhvPyX2vplQ0RUsRGhthFadg1M5LOJylpQXm9A0d8YJ4CeNwq0kAg2BrdCM7UyfZFOlnVjrJS2o4fBvvhLWDfbd7LhScCzde4Heh5P3C26ZWCRGQppJhb",
#     authorize_url="https://login.fs.cs.uni-frankfurt.de/application/o/authorize/",
#     authorize_params=None,
#     access_token_url="https://login.fs.cs.uni-frankfurt.de/application/o/token/",
#     access_token_params=None,
#     client_kwargs={"scope": "openid profile email"},
#     server_metadata_url="https://login.fs.cs.uni-frankfurt.de/application/o/testkicker/.well-known/openid-configuration",
#     api_base_url="https://login.fs.cs.uni-frankfurt.de/application/o/testkicker/",
#     jwks_uri="https://login.fs.cs.uni-frankfurt.de/application/o/testkicker/jwks/",
#     userinfo_endpoint="https://login.fs.cs.uni-frankfurt.de/application/o/userinfo/",
# )

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
    auth0_client = oauth.create_client("auth0")
    redirect_uri = os.getenv("OIDC_REDIRECT_URI")
    return await auth0_client.authorize_redirect(request, redirect_uri)

@router.route("/authorize")
async def authorize(request: Request):
    token = await oauth.auth0.authorize_access_token(request)
    userinfo_endpoint = oauth.auth0.server_metadata.get("userinfo_endpoint")
    resp = await oauth.auth0.get(userinfo_endpoint, token=token)
    resp.raise_for_status()
    profile = resp.json()
    print("Profile:", profile)

    # save user info in session
    request.session["user"] = profile

    return RedirectResponse(url="/", status_code=303)

@router.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    logout_url = oauth.auth0.server_metadata.get("end_session_endpoint")
    if not logout_url:
        logout_url = os.getenv("OIDC_LOGOUT_URL")
    return RedirectResponse(url=logout_url, status_code=303)
