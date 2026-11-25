import hashlib
import hmac
import ipaddress
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.v2.storage import secret_file

router = APIRouter()
COOKIE = "momentrix_studio"


def equal(actual: str, expected: str):
    return bool(expected) and hmac.compare_digest(actual.encode(), expected.encode())


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticated(request):
    token = request.cookies.get(COOKIE, "")
    if not token:
        return False
    with request.app.state.database.transaction() as c:
        return c.execute("SELECT 1 FROM sessions WHERE digest=? AND expires>?",
                         (digest(token), time.time())).fetchone() is not None


def internal_configured(settings):
    return (bool(settings.service_token and settings.webhook_secret)
            and len({settings.api_token, settings.service_token, settings.webhook_secret}) == 3)


def browser_origin(request):
    origin = request.headers.get("origin")
    if not origin:
        return True
    parsed = urlsplit(origin)
    return (parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1","localhost","::1"}
            and (parsed.netloc == request.headers.get("host") or parsed.port == 5173))


async def guard(request, call_next):
    settings = request.app.state.settings
    path = request.url.path
    if path == "/" or path == "/studio" or path.startswith("/studio/"):
        return await call_next(request)
    if path.startswith("/api/v2/internal/"):
        if not internal_configured(settings) or not equal(request.headers.get("x-momentrix-service",""),settings.service_token):
            return JSONResponse({"detail":"Invalid service credential"}, status_code=401)
        return await call_next(request)
    if path.startswith("/api/v2/"):
        if request.url.hostname not in {"localhost","127.0.0.1","::1"}:
            return JSONResponse({"detail":"Website access requires a local hostname"}, status_code=403)
        if request.method not in {"GET","HEAD","OPTIONS"} and (
                request.headers.get("X-Momentrix-Client") != "website" or not browser_origin(request)):
            return JSONResponse({"detail":"Invalid website request origin"}, status_code=403)
        if path != "/api/v2/session" and not authenticated(request):
            return JSONResponse({"detail":"Sign in to the local studio"}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    if settings.api_token:
        if not equal(request.headers.get("x-api-token",""),settings.api_token):
            return JSONResponse({"detail":"Invalid or missing X-API-Token"},status_code=401)
    else:
        try:
            local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not local or request.url.hostname not in {"localhost","127.0.0.1","::1"}:
            return JSONResponse({"detail":"Configure an API token for access outside localhost"}, status_code=403)
    return await call_next(request)


class Login(BaseModel):
    token: str = Field(max_length=180)


@router.get("/session")
def session(request: Request):
    return {"authenticated": authenticated(request)}


@router.post("/session")
def login(data: Login, request: Request, response: Response):
    if not equal(data.token, secret_file(request.app.state.settings, "studio.key")):
        raise HTTPException(401,"Invalid studio access key. Run scripts/show_studio_key.ps1 locally.")
    token = secrets.token_urlsafe(32)
    with request.app.state.database.transaction(write=True) as c:
        c.execute("DELETE FROM sessions WHERE expires < ?",(time.time(),))
        c.execute("INSERT INTO sessions VALUES (?,?)",(digest(token),time.time()+43200))
    response.set_cookie(COOKIE,token,max_age=43200,httponly=True,samesite="strict",
                        secure=request.url.scheme=="https",path="/api/v2")
    return {"authenticated":True}


@router.delete("/session")
def logout(request: Request, response: Response):
    with request.app.state.database.transaction(write=True) as c:
        c.execute("DELETE FROM sessions WHERE digest=?",(digest(request.cookies.get(COOKIE,"")),))
    response.delete_cookie(COOKIE,path="/api/v2")
    return {"authenticated":False}

