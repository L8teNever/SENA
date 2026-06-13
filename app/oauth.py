import os
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import app.database as db

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.modify"
]

def get_google_client_config(redirect_uri=None):
    """Retrieves Google client config from Environment or Database settings."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or db.get_setting("google_client_id")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or db.get_setting("google_client_secret")
    
    if not client_id or not client_secret:
        return None

    # Try to extract redirect URI
    env_redirect = os.environ.get("REDIRECT_URI") or db.get_setting("google_redirect_uri")
    r_uri = redirect_uri or env_redirect or "http://localhost:8000/oauth2callback"

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [r_uri]
        }
    }

def get_auth_url(redirect_uri):
    """Generates the authorization URL to redirect the user to Google login."""
    client_config = get_google_client_config(redirect_uri)
    if not client_config:
        return None, "Google Client ID and Client Secret are not configured.", None

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    # Enable offline access to obtain refresh token
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent", # Force consent screen to guarantee refresh token is returned
        include_granted_scopes="true"
    )
    return authorization_url, state, flow.code_verifier

def handle_oauth_callback(authorization_response, state, redirect_uri, code_verifier=None):
    """Handles callback response from Google, exchanges authorization code for tokens,
    retrieves user email, and stores them in the database."""
    client_config = get_google_client_config(redirect_uri)
    if not client_config:
        raise ValueError("Google Client configuration is missing.")

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=state,
        code_verifier=code_verifier
    )
    
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials

    # Call Userinfo API to get the user's email
    userinfo_service = build("oauth2", "v2", credentials=credentials)
    userinfo = userinfo_service.userinfo().get().execute()
    email = userinfo.get("email")

    if not email:
        raise ValueError("Failed to retrieve user email from Google account.")

    # Save credentials to database
    db.save_user(
        email=email,
        access_token=credentials.token,
        refresh_token=credentials.refresh_token, # Might be None if user did not re-consent, but we forced prompt='consent'
        token_uri=credentials.token_uri,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        scopes=json.dumps(credentials.scopes),
        expiry=credentials.expiry.isoformat() if credentials.expiry else ""
    )

    return email

def get_refreshed_credentials(user_dict):
    """Constructs Credentials object from database values and refreshes if expired."""
    scopes_list = json.loads(user_dict["scopes"]) if user_dict["scopes"] else SCOPES
    
    # Reconstruct google Credentials object
    credentials = Credentials(
        token=user_dict["access_token"],
        refresh_token=user_dict["refresh_token"],
        token_uri=user_dict["token_uri"],
        client_id=user_dict["client_id"],
        client_secret=user_dict["client_secret"],
        scopes=scopes_list
    )

    # Check if we need to refresh
    if credentials.expired or (credentials.expiry and credentials.valid is False):
        try:
            credentials.refresh(Request())
            # Save the updated credentials to db
            db.save_user(
                email=user_dict["email"],
                access_token=credentials.token,
                refresh_token=credentials.refresh_token,
                token_uri=credentials.token_uri,
                client_id=credentials.client_id,
                client_secret=credentials.client_secret,
                scopes=json.dumps(credentials.scopes),
                expiry=credentials.expiry.isoformat() if credentials.expiry else ""
            )
        except Exception as e:
            db.add_log(user_dict["email"], f"Failed to refresh Google token: {str(e)}", "error")
            return None

    return credentials
