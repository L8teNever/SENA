import os
import urllib.parse
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from typing import Optional

import app.database as db
import app.oauth as oauth
import app.gmail_worker as gmail_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Database
    db.init_db()
    
    # Set default settings if not exists
    if db.get_setting("verification_cleanup_enabled") is None:
        db.set_setting("verification_cleanup_enabled", "true")
        
    # Start background worker
    gmail_worker.start_worker()
    
    yield
    
    # Stop background worker
    gmail_worker.stop_worker()

app = FastAPI(title="SENA Email Automator", lifespan=lifespan)

# Mount static and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Helper to check login status
def get_current_user_email(request: Request):
    email = request.cookies.get("sena_user_email")
    if not email:
        return None
    # Verify user exists in db
    user = db.get_user(email)
    if not user:
        return None
    return email

# Helper to dynamically get the redirect URI supporting reverse proxies
def get_redirect_uri(request: Request) -> str:
    # Prioritize environment variable if explicitly configured
    env_redirect = os.environ.get("REDIRECT_URI")
    if env_redirect:
        return env_redirect
        
    # Get host, prioritizing proxy headers
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
    
    # Get scheme, prioritizing proxy headers
    x_proto = request.headers.get("x-forwarded-proto")
    if x_proto:
        # Standard proxy chains can provide comma-separated protocols
        proto = x_proto.split(",")[0].strip().lower()
    else:
        proto = request.url.scheme
        
    return f"{proto}://{host}/oauth2callback"

# Pydantic schemas for API inputs
class RuleCreate(BaseModel):
    name: str
    rule_type: str # 'from', 'to', 'from_subject', 'subject_keywords'
    condition_sender: Optional[str] = None
    condition_recipient: Optional[str] = None
    condition_subject: Optional[str] = None
    target_label: str
    remove_from_inbox: bool = True
    remove_from_important: bool = True

class ContactCreate(BaseModel):
    email: EmailStr

# --- UI Routes ---

@app.get("/")
async def index(request: Request):
    user_email = get_current_user_email(request)
    
    # Check if Google client credentials are set
    client_config = oauth.get_google_client_config()
    credentials_configured = client_config is not None
    
    # Generate dynamic redirect URI to display/use
    redirect_uri = get_redirect_uri(request)
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user_email": user_email,
            "credentials_configured": credentials_configured,
            "google_client_id": os.environ.get("GOOGLE_CLIENT_ID") or db.get_setting("google_client_id") or "",
            "redirect_uri": redirect_uri
        }
    )

# --- Settings & Setup API ---

@app.post("/api/settings/setup")
async def setup_credentials(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(...),
    redirect_uri: Optional[str] = Form(None)
):
    if not redirect_uri:
        redirect_uri = get_redirect_uri(request)
        
    db.set_setting("google_client_id", client_id.strip())
    db.set_setting("google_client_secret", client_secret.strip())
    db.set_setting("google_redirect_uri", redirect_uri.strip())
    
    return RedirectResponse("/", status_code=303)

@app.get("/api/settings")
async def get_settings(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    cleanup = db.get_setting("verification_cleanup_enabled", "true") == "true"
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or db.get_setting("google_client_id") or ""
    
    return {
        "verification_cleanup_enabled": cleanup,
        "google_client_id": client_id
    }

@app.post("/api/settings/toggle-cleanup")
async def toggle_cleanup(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    current = db.get_setting("verification_cleanup_enabled", "true") == "true"
    new_state = "false" if current else "true"
    db.set_setting("verification_cleanup_enabled", new_state)
    
    return {"status": "success", "verification_cleanup_enabled": new_state == "true"}

# --- Google OAuth Routes ---

@app.get("/oauth/login")
async def oauth_login(request: Request):
    # Determine callback URI dynamically
    redirect_uri = get_redirect_uri(request)
    
    # Store dynamic redirect URI in DB as override
    db.set_setting("google_redirect_uri", redirect_uri)
    
    auth_url, state, code_verifier = oauth.get_auth_url(redirect_uri)
    if not auth_url:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error_message": "Google-API-Client-Zugangsdaten sind nicht eingerichtet.",
                "credentials_configured": False,
                "redirect_uri": redirect_uri
            }
        )
    
    response = RedirectResponse(auth_url)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True)
    if code_verifier:
        response.set_cookie("oauth_code_verifier", code_verifier, max_age=600, httponly=True)
    return response

@app.get("/oauth2callback")
async def oauth_callback(request: Request, response: Response):
    state = request.cookies.get("oauth_state")
    code_verifier = request.cookies.get("oauth_code_verifier")
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state cookie.")

    # Reconstruct exact redirect URI used during authorization request
    redirect_uri = get_redirect_uri(request)

    # Full callback URL parsed
    full_url = str(request.url)
    # google-auth-oauthlib expects https in redirect URI unless it's localhost/127.0.0.1
    # We can override safety check for local development/testing in docker
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    
    try:
        email = oauth.handle_oauth_callback(
            authorization_response=full_url,
            state=state,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier
        )
        
        db.add_log(email, "Google-Konto erfolgreich verbunden und autorisiert.", "success")
        
        # Set user login cookie
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("sena_user_email", email, max_age=30*24*3600, httponly=True) # 30 days
        response.delete_cookie("oauth_state")
        response.delete_cookie("oauth_code_verifier")
        return response
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error_message": f"OAuth-Fehler: {str(e)}",
                "credentials_configured": True,
                "redirect_uri": redirect_uri
            }
        )

@app.post("/api/logout")
async def logout(response: Response):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("sena_user_email")
    return response

# --- User & Status API ---

@app.get("/api/status")
async def get_status(request: Request):
    email = get_current_user_email(request)
    if not email:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "email": email
    }

# --- Custom Rules API ---

@app.get("/api/rules")
async def get_rules(request: Request):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return db.get_rules(email)

@app.post("/api/rules")
async def create_rule(request: Request, rule: RuleCreate):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    db.add_rule(
        user_email=email,
        name=rule.name,
        rule_type=rule.rule_type,
        condition_sender=rule.condition_sender,
        condition_recipient=rule.condition_recipient,
        condition_subject=rule.condition_subject,
        target_label=rule.target_label,
        remove_from_inbox=rule.remove_from_inbox,
        remove_from_important=rule.remove_from_important
    )
    db.add_log(email, f"Neue Regel '{rule.name}' erstellt.", "info")
    return {"status": "success"}

@app.delete("/api/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: int):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.delete_rule(rule_id, email)
    db.add_log(email, f"Regel #{rule_id} gelöscht.", "info")
    return {"status": "success"}

@app.post("/api/rules/{rule_id}/toggle")
async def toggle_rule(request: Request, rule_id: int, active_payload: dict):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    active = active_payload.get("active", True)
    db.toggle_rule(rule_id, email, active)
    db.add_log(email, f"Regel #{rule_id} {'aktiviert' if active else 'deaktiviert'}.", "info")
    return {"status": "success"}

# --- Super Wichtig Contacts API ---

@app.get("/api/contacts")
async def get_contacts(request: Request):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return db.get_super_wichtig_contacts(email)

@app.post("/api/contacts")
async def add_contact(request: Request, contact: ContactCreate):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    db.add_super_wichtig_contact(email, contact.email, source="manual")
    db.add_log(email, f"Kontakt manuell als 'Super Wichtig' hinzugefügt: {contact.email}", "info")
    return {"status": "success"}

@app.delete("/api/contacts/{contact_email}")
async def delete_contact(request: Request, contact_email: str):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    # Unquote URL encoded email
    decoded_email = urllib.parse.unquote(contact_email)
    db.delete_super_wichtig_contact(email, decoded_email)
    db.add_log(email, f"Kontakt aus 'Super Wichtig' gelöscht: {decoded_email}", "info")
    return {"status": "success"}

# --- Logs API ---

@app.get("/api/logs")
async def get_logs(request: Request, limit: int = 50):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return db.get_logs(email, limit)

# --- Force Sync API ---

def run_sync_background(user_email):
    """Utility function to perform a manual run of the Gmail worker tasks."""
    user = db.get_user(user_email)
    if not user:
        return
        
    service = gmail_worker.get_gmail_service(user)
    if not service:
        db.add_log(user_email, "Sync fehlgeschlagen: Google OAuth token konnte nicht geladen werden.", "error")
        return
        
    db.add_log(user_email, "Manueller Sync gestartet...", "info")
    # Scan sent for contacts
    gmail_worker.process_sent_messages(service, user_email)
    # Process inbox rules
    gmail_worker.process_inbox_messages(service, user)
    db.add_log(user_email, "Manueller Sync abgeschlossen.", "success")

@app.post("/api/trigger-sync")
async def trigger_sync(request: Request, background_tasks: BackgroundTasks):
    email = get_current_user_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    background_tasks.add_task(run_sync_background, email)
    return {"status": "success", "message": "Sync triggered in background"}
