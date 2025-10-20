import os
from fastapi import Header, HTTPException, status
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_KEY") or "secret123"

def verify_api_key(x_api_key: str | None = Header(default=None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
