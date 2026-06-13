import time
import threading
import email.utils
from datetime import datetime
import app.database as db
import app.oauth as oauth
from googleapiclient.discovery import build

worker_thread = None
worker_should_run = True

# Standard verification keywords in German and English
VERIFICATION_KEYWORDS = [
    "verifizierungscode",
    "bestätige deine e-mail",
    "einmal-passwort",
    "verification code",
    "one-time password",
    "otp",
    "verification link",
    "verify your email",
    "activation code",
    "einmal-code",
    "bestätigungscode",
    "sicherheitscode",
    "passwort zurücksetzen",
    "password reset"
]

def get_gmail_service(user_dict):
    """Refreshes credentials and returns a Gmail API service client."""
    credentials = oauth.get_refreshed_credentials(user_dict)
    if not credentials:
        return None
    return build("gmail", "v1", credentials=credentials)

def get_or_create_label_id(service, label_name):
    """Finds the ID of a label by name, or creates it if it doesn't exist."""
    try:
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        
        # Check if label exists (case-insensitive check)
        for label in labels:
            if label["name"].lower() == label_name.lower():
                return label["id"]
        
        # Create label
        label_body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show"
        }
        new_label = service.users().labels().create(userId="me", body=label_body).execute()
        return new_label["id"]
    except Exception as e:
        print(f"Error getting/creating label {label_name}: {e}")
        return None

def extract_email_address(header_value):
    """Extracts a clean lowercase email address from a header value (e.g. From/To)."""
    if not header_value:
        return ""
    name, addr = email.utils.parseaddr(header_value)
    return addr.lower().strip()

def match_email(email_addr: str, pattern: str) -> bool:
    """Checks if an email matches a pattern. Matches full email, substring, or '@domain.de' (endswith)."""
    email_addr = email_addr.lower().strip()
    pattern = pattern.lower().strip()
    if not pattern:
        return False
    if pattern.startswith("@"):
        return email_addr.endswith(pattern)
    return pattern in email_addr

def process_sent_messages(service, user_email):
    """Scans recently sent emails to auto-detect 'Super Wichtig' contacts."""
    try:
        # Search for messages sent by the user (max 50 to keep it fast)
        results = service.users().messages().list(userId="me", q="from:me", maxResults=50).execute()
        messages = results.get("messages", [])
        
        new_contacts_count = 0
        
        for msg in messages:
            msg_id = msg["id"]
            # Fetch To header
            msg_data = service.users().messages().get(
                userId="me", id=msg_id, format="metadata", metadataHeaders=["To"]
            ).execute()
            
            headers = msg_data.get("payload", {}).get("headers", [])
            to_header = ""
            for h in headers:
                if h["name"].lower() == "to":
                    to_header = h["value"]
                    break
            
            if to_header:
                # To header can contain multiple emails separated by commas
                parts = to_header.split(",")
                for part in parts:
                    email_addr = extract_email_address(part)
                    if email_addr and email_addr != user_email:
                        # Check if already exists in DB
                        existing = db.get_super_wichtig_contacts(user_email)
                        existing_emails = {c["contact_email"] for c in existing}
                        if email_addr not in existing_emails:
                            if not db.is_deleted_super_wichtig_contact(user_email, email_addr):
                                db.add_super_wichtig_contact(user_email, email_addr, source="auto")
                                db.add_log(user_email, f"Kontakt automatisch als 'Super Wichtig' markiert (gesendete Mail): {email_addr}", "info")
                                new_contacts_count += 1
                            
    except Exception as e:
        print(f"Error processing sent messages for {user_email}: {e}")

def process_inbox_messages(service, user_dict):
    """Processes messages currently in the Inbox according to configured rules."""
    user_email = user_dict["email"]
    try:
        # Get active rules for this user
        rules = [r for r in db.get_rules(user_email) if r["active"]]
        super_wichtig_contacts = {c["contact_email"] for c in db.get_super_wichtig_contacts(user_email)}
        
        # Check if verification clean-up is active (default to enabled, saved in settings)
        verification_cleanup_enabled = db.get_setting("verification_cleanup_enabled", "true") == "true"
        
        # We query messages in the inbox or important section
        results = service.users().messages().list(
            userId="me", q="is:inbox OR is:important", maxResults=100
        ).execute()
        messages = results.get("messages", [])
        
        if not messages:
            return

        now_ms = time.time() * 1000

        for msg in messages:
            msg_id = msg["id"]
            
            # Fetch message headers and labels
            msg_data = service.users().messages().get(
                userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"]
            ).execute()
            
            current_labels = msg_data.get("labelIds", [])
            internal_date = int(msg_data.get("internalDate", 0))
            
            headers = msg_data.get("payload", {}).get("headers", [])
            msg_from = ""
            msg_to = ""
            msg_subject = ""
            
            for h in headers:
                name_lower = h["name"].lower()
                if name_lower == "from":
                    msg_from = h["value"]
                elif name_lower == "to":
                    msg_to = h["value"]
                elif name_lower == "subject":
                    msg_subject = h["value"]

            from_email = extract_email_address(msg_from)
            to_email = extract_email_address(msg_to)
            subject_lower = msg_subject.lower()

            # --- Rule Matching ---
            matched_rule = None
            for rule in rules:
                is_match = False
                
                if rule["rule_type"] == "from":
                    # Check if sender email matches any of the comma-separated senders
                    cond_sender = rule["condition_sender"].lower().strip() if rule["condition_sender"] else ""
                    if cond_sender:
                        senders = [s.strip() for s in cond_sender.split(",") if s.strip()]
                        if any(match_email(from_email, s) for s in senders):
                            is_match = True
                
                elif rule["rule_type"] == "to":
                    # Check if recipient email matches any of the comma-separated recipients
                    cond_recipient = rule["condition_recipient"].lower().strip() if rule["condition_recipient"] else ""
                    if cond_recipient:
                        recipients = [r.strip() for r in cond_recipient.split(",") if r.strip()]
                        if any(match_email(to_email, r) for r in recipients):
                            is_match = True
                
                elif rule["rule_type"] == "from_subject":
                    # Check sender (any from list) and subject
                    cond_sender = rule["condition_sender"].lower().strip() if rule["condition_sender"] else ""
                    cond_subject = rule["condition_subject"].lower().strip() if rule["condition_subject"] else ""
                    if cond_sender and cond_subject:
                        senders = [s.strip() for s in cond_sender.split(",") if s.strip()]
                        if any(match_email(from_email, s) for s in senders) and cond_subject in subject_lower:
                            is_match = True
                
                elif rule["rule_type"] == "subject_keywords":
                    # Check list of keywords (comma separated)
                    keywords = [k.strip().lower() for k in rule["condition_subject"].split(",") if k.strip()]
                    if any(kw in subject_lower for kw in keywords):
                        is_match = True

                if is_match:
                    matched_rule = rule
                    break

            # 1. Custom Rule Action
            if matched_rule:
                target_label = matched_rule["target_label"]
                label_id = get_or_create_label_id(service, target_label)
                
                if label_id:
                    add_labels = []
                    remove_labels = []
                    
                    if label_id not in current_labels:
                        add_labels.append(label_id)
                        
                    if matched_rule["remove_from_inbox"] and "INBOX" in current_labels:
                        remove_labels.append("INBOX")
                        
                    if matched_rule["remove_from_important"] and "IMPORTANT" in current_labels:
                        remove_labels.append("IMPORTANT")
                        
                    if add_labels or remove_labels:
                        modify_body = {}
                        if add_labels:
                            modify_body["addLabelIds"] = add_labels
                        if remove_labels:
                            modify_body["removeLabelIds"] = remove_labels
                            
                        service.users().messages().modify(userId="me", id=msg_id, body=modify_body).execute()
                        
                        log_msg = f"Regel '{matched_rule['name']}' angewendet auf E-Mail von '{from_email}': "
                        if add_labels:
                            log_msg += f"Label '{target_label}' hinzugefügt. "
                        if "INBOX" in remove_labels:
                            log_msg += "Aus Posteingang archiviert. "
                        db.add_log(user_email, log_msg, "success")
                        # Skip other checks since this email is now routed by a custom rule
                        continue

            # 2. Super Wichtig check
            if from_email in super_wichtig_contacts:
                sw_label_name = "Super Wichtig"
                sw_label_id = get_or_create_label_id(service, sw_label_name)
                if sw_label_id and sw_label_id not in current_labels:
                    modify_body = {"addLabelIds": [sw_label_id]}
                    service.users().messages().modify(userId="me", id=msg_id, body=modify_body).execute()
                    db.add_log(user_email, f"E-Mail von 'Super Wichtig' Kontakt '{from_email}' erhalten. Label 'Super Wichtig' hinzugefügt.", "success")
                    # We do not archive auto super-wichtig mails unless a custom rule says so

            # 3. Verification Code Auto-Cleaner
            if verification_cleanup_enabled:
                # Check if subject contains verification words
                if any(kw in subject_lower for kw in VERIFICATION_KEYWORDS):
                    # Check age (> 24 hours)
                    age_seconds = (now_ms - internal_date) / 1000
                    if age_seconds > 86400: # 24 hours
                        v_label_name = "SENA/Verifizierungen"
                        v_label_id = get_or_create_label_id(service, v_label_name)
                        
                        if v_label_id:
                            add_labels = []
                            remove_labels = []
                            
                            if v_label_id not in current_labels:
                                add_labels.append(v_label_id)
                            if "INBOX" in current_labels:
                                remove_labels.append("INBOX")
                            if "IMPORTANT" in current_labels:
                                remove_labels.append("IMPORTANT")
                                
                            if add_labels or remove_labels:
                                modify_body = {}
                                if add_labels:
                                    modify_body["addLabelIds"] = add_labels
                                if remove_labels:
                                    modify_body["removeLabelIds"] = remove_labels
                                    
                                service.users().messages().modify(userId="me", id=msg_id, body=modify_body).execute()
                                db.add_log(user_email, f"Verifizierungscode-E-Mail archiviert (>24h alt): '{msg_subject}' von '{from_email}'", "success")

    except Exception as e:
        db.add_log(user_email, f"Fehler bei der E-Mail-Verarbeitung: {str(e)}", "error")
        print(f"Error processing inbox for {user_email}: {e}")

def process_historical_messages(service, user_dict, since_date):
    """Processes historical messages since the given date (format: YYYY-MM-DD) according to active rules."""
    user_email = user_dict["email"]
    try:
        # Get active rules for this user
        rules = [r for r in db.get_rules(user_email) if r["active"]]
        
        # Build query: search for messages received after the since_date
        query = f"after:{since_date}"
        
        db.add_log(user_email, f"Suche historische E-Mails ab {since_date} mit Query '{query}'...", "info")
        
        results = service.users().messages().list(
            userId="me", q=query, maxResults=500  # Scan up to 500 messages
        ).execute()
        messages = results.get("messages", [])
        
        if not messages:
            db.add_log(user_email, f"Keine historischen E-Mails ab {since_date} gefunden.", "info")
            return
            
        db.add_log(user_email, f"{len(messages)} historische E-Mails ab {since_date} gefunden. Verarbeite...", "info")
        
        processed_count = 0
        matched_count = 0

        for msg in messages:
            msg_id = msg["id"]
            
            # Fetch message headers and labels
            msg_data = service.users().messages().get(
                userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"]
            ).execute()
            
            current_labels = msg_data.get("labelIds", [])
            
            headers = msg_data.get("payload", {}).get("headers", [])
            msg_from = ""
            msg_to = ""
            msg_subject = ""
            
            for h in headers:
                name_lower = h["name"].lower()
                if name_lower == "from":
                    msg_from = h["value"]
                elif name_lower == "to":
                    msg_to = h["value"]
                elif name_lower == "subject":
                    msg_subject = h["value"]

            from_email = extract_email_address(msg_from)
            to_email = extract_email_address(msg_to)
            subject_lower = msg_subject.lower()

            # --- Rule Matching ---
            matched_rule = None
            for rule in rules:
                is_match = False
                
                if rule["rule_type"] == "from":
                    cond_sender = rule["condition_sender"].lower().strip() if rule["condition_sender"] else ""
                    if cond_sender:
                        senders = [s.strip() for s in cond_sender.split(",") if s.strip()]
                        if any(match_email(from_email, s) for s in senders):
                            is_match = True
                
                elif rule["rule_type"] == "to":
                    cond_recipient = rule["condition_recipient"].lower().strip() if rule["condition_recipient"] else ""
                    if cond_recipient:
                        recipients = [r.strip() for r in cond_recipient.split(",") if r.strip()]
                        if any(match_email(to_email, r) for r in recipients):
                            is_match = True
                
                elif rule["rule_type"] == "from_subject":
                    cond_sender = rule["condition_sender"].lower().strip() if rule["condition_sender"] else ""
                    cond_subject = rule["condition_subject"].lower().strip() if rule["condition_subject"] else ""
                    if cond_sender and cond_subject:
                        senders = [s.strip() for s in cond_sender.split(",") if s.strip()]
                        if any(match_email(from_email, s) for s in senders) and cond_subject in subject_lower:
                            is_match = True
                
                elif rule["rule_type"] == "subject_keywords":
                    keywords = [k.strip().lower() for k in rule["condition_subject"].split(",") if k.strip()]
                    if any(kw in subject_lower for kw in keywords):
                        is_match = True

                if is_match:
                    matched_rule = rule
                    break

            if matched_rule:
                target_label = matched_rule["target_label"]
                label_id = get_or_create_label_id(service, target_label)
                
                if label_id:
                    add_labels = []
                    remove_labels = []
                    
                    if label_id not in current_labels:
                        add_labels.append(label_id)
                        
                    if matched_rule["remove_from_inbox"] and "INBOX" in current_labels:
                        remove_labels.append("INBOX")
                        
                    if matched_rule["remove_from_important"] and "IMPORTANT" in current_labels:
                        remove_labels.append("IMPORTANT")
                        
                    if add_labels or remove_labels:
                        modify_body = {}
                        if add_labels:
                            modify_body["addLabelIds"] = add_labels
                        if remove_labels:
                            modify_body["removeLabelIds"] = remove_labels
                            
                        service.users().messages().modify(userId="me", id=msg_id, body=modify_body).execute()
                        matched_count += 1
            
            processed_count += 1
            if processed_count % 50 == 0:
                db.add_log(user_email, f"Historischer Sync: {processed_count} von {len(messages)} Mails analysiert...", "info")

        db.add_log(user_email, f"Historischer Sync abgeschlossen. {processed_count} Mails analysiert, Regeln auf {matched_count} Mails angewendet.", "success")

    except Exception as e:
        db.add_log(user_email, f"Fehler bei historischem Sync: {str(e)}", "error")
        print(f"Error processing historical sync for {user_email}: {e}")

def run_worker_loop():
    """Main background loop processing email accounts."""
    global worker_should_run
    print("SENA Background Gmail Worker started.")
    
    while worker_should_run:
        try:
            users = db.get_all_users()
            for user in users:
                user_email = user["email"]
                # Get Gmail client
                service = get_gmail_service(user)
                if not service:
                    print(f"Skipping background execution for {user_email}: OAuth client credentials invalid or expired.")
                    continue
                
                # Run background tasks
                process_sent_messages(service, user_email)
                process_inbox_messages(service, user)
                
        except Exception as e:
            print(f"Global error in Gmail worker loop: {e}")
            
        # Check every 5 minutes (300 seconds), sleep in increments of 1 second to allow graceful shutdown
        for _ in range(300):
            if not worker_should_run:
                break
            time.sleep(1)
            
    print("SENA Background Gmail Worker stopped.")

def start_worker():
    """Starts the background worker thread."""
    global worker_thread, worker_should_run
    worker_should_run = True
    worker_thread = threading.Thread(target=run_worker_loop, daemon=True)
    worker_thread.start()

def stop_worker():
    """Stops the background worker thread."""
    global worker_should_run
    worker_should_run = False
    if worker_thread:
        worker_thread.join(timeout=5)
