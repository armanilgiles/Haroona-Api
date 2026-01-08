import os
from fastapi import APIRouter, HTTPException, Response, Depends
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests

from sqlalchemy.orm import Session


from app.auth.jwt import create_access_token
from app.database import get_db
from app.models import User

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
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
    )
    
    

    return {"message": "Logged out"}


@router.post("/auth/google")
def google_auth(
    data: GoogleAuthRequest,
    response: Response,
    db: Session = Depends(get_db),
):
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

    # Find or create your app user (this is what enables `welcome_seen` to persist).
    user = db.query(User).filter(User.id == str(google_id)).first()
    if not user:
        user = User(
            id=str(google_id),
            email=email,
            name=name,
            avatar=avatar,
            welcome_seen=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Keep profile fresh (optional)
        changed = False
        if user.email != email:
            user.email = email
            changed = True
        if name and user.name != name:
            user.name = name
            changed = True
        if avatar and user.avatar != avatar:
            user.avatar = avatar
            changed = True
        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)

    access_token = create_access_token({
        "sub": user.id,
        "email": user.email,
    })

    # 🔥 MVP BEST PRACTICE: HttpOnly cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        max_age=60 * 60 * 24 * 7
    )

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar": user.avatar,
        "welcome_seen": user.welcome_seen,
    }
