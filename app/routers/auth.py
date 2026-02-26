import os
import requests
from fastapi import APIRouter, HTTPException, Response, Request, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.jwt import create_access_token

router = APIRouter()
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

class GoogleAuthRequest(BaseModel):
    access_token: str

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
    r = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {data.access_token}"},
        timeout=10,
    )

    if r.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Google token rejected: {r.text}")

    profile = r.json()
    google_id = profile.get("sub")
    email = profile.get("email")
    name = profile.get("name")
    avatar = profile.get("picture")

    if not google_id:
        raise HTTPException(status_code=401, detail="Google userinfo missing sub")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    jwt_token = create_access_token({"sub": str(google_id), "email": email})

    # IMPORTANT: secure=True blocks cookies on http://localhost
    is_prod = os.getenv("ENV", "dev").lower() in {"prod", "production"}
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        secure=is_prod,   # False locally, True in prod (https)
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )

    return {"email": email, "name": name, "avatar": avatar}





@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)

        return {
            "authenticated": True,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "avatar": user.avatar,
                "welcome_seen": user.welcome_seen,
            },
        }
    except Exception:
        # Guest user
        return {
            "authenticated": False,
            "user": None,
        }
