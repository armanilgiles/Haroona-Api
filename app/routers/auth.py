import os
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests
from fastapi import APIRouter, Response


from app.auth.jwt import create_access_token

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

class GoogleAuthRequest(BaseModel):
    id_token: str


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key="access_token", 
        path="/", 
        httponly=True, 
        secure=False,  # True in prod
        samesite="lax",
    )
    
    

    return {"message": "Logged out"}


@router.post("/auth/google")
def google_auth(data: GoogleAuthRequest, response: Response):
    try:
        idinfo = id_token.verify_oauth2_token(
            data.id_token,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    # Trusted Google identity
    google_id = idinfo["sub"]
    email = idinfo.get("email")
    name = idinfo.get("name")
    avatar = idinfo.get("picture")

    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    # TODO (later):
    # user = find_or_create_user(email=email, google_id=google_id)

    access_token = create_access_token({
        "sub": str(google_id),
        "email": email
    })

    # 🔥 MVP BEST PRACTICE: HttpOnly cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,      # set False locally if needed
        samesite="lax",
        max_age=60 * 60 * 24 * 7
    )

    return {
        "email": email,
        "name": name,
        "avatar": avatar
    }
