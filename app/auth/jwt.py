import os
from datetime import datetime, timedelta
from jose import jwt


SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7
print("GOOGLE_CLIENT_ID:", os.getenv("GOOGLE_CLIENT_ID"))

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set")


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
