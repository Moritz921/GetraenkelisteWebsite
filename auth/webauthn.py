from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from webauthn import (
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    options_to_json,
    base64url_to_bytes,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialHint,
    ResidentKeyRequirement,
)

import os

router = APIRouter()

# Simulierte Userdatenbank (nur zum Testen!)
fake_users = {
    "admin@example.com": {
        "id": b"user-id-in-bytes",
        "credential_id": b"credential-id-in-bytes",
        "public_key": b"public-key-in-bytes",
        "sign_count": 0
    }
}

RP_ID = "localhost"  # Oder deine Domain bei Produktivbetrieb
ORIGIN = "http://localhost:8000"

@router.get("/login/webauthn/start")
async def start_webauthn(request: Request):
    email = "admin@example.com"  # Hardcoded Demo-User

    if email not in fake_users:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    user = fake_users[email]

    options = PublicKeyCredentialRequestOptions(
    challenge=os.urandom(32),
    rp_id=RP_ID,
    allow_credentials=[...],
    timeout=60000,
)

    # Speichere Challenge für später
    request.session["challenge"] = options.challenge
    return JSONResponse(content=options.model_dump())

@router.post("/login/webauthn/finish")
async def finish_webauthn(request: Request):
    body = await request.json()
    email = "admin@example.com"  # Again, Demo-User

    if email not in fake_users:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    user = fake_users[email]

    try:
        verified_auth = verify_authentication_response(
            credential=AuthenticationCredential.parse_obj(body),
            expected_challenge=request.session.get("challenge"),
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            credential_public_key=user["public_key"],
            credential_current_sign_count=user["sign_count"],
            credential_id=user["credential_id"]
        )

        # Erfolg – setze Session
        request.session["user"] = email
        return RedirectResponse(url="/", status_code=303)

    except Exception as e:
        return JSONResponse({"detail": f"WebAuthn fehlgeschlagen: {str(e)}"}, status_code=400)
