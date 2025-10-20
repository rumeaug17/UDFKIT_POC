from fastapi import FastAPI
from app.udfkit import attach_to_app
from app.security import verify_api_key
import app.my_udfs  # import des fonctions métiers

app = FastAPI(title="Excel Python Local Server (UDFKit)")

@app.get("/health")
def health():
    return {"ok": True}

attach_to_app(app, security_dep=verify_api_key)
