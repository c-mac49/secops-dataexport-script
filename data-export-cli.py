import os
import time
import datetime
import json
import argparse
from dotenv import load_dotenv
import requests as requests_lib
from google.oauth2 import service_account
from google.auth.transport import requests

# Load environment variables from .env file immediately
load_dotenv()

class Config:
    """Holds static configuration from .env file."""
    # Auth
    SERVICE_ACCOUNT_FILE = os.getenv("SECOPS_ACCOUNT_JSON")
    SCOPES = [os.getenv("SECOPS_SCOPES")]

    # Infrastructure
    PROJECT_ID = os.getenv("CHRONICLE_PROJECT_ID")
    LOCATION = os.getenv("CHRONICLE_LOCATION")
    INSTANCE_ID = os.getenv("CHRONICLE_INSTANCE_ID")
    GCS_BUCKET = os.getenv("CHRONICLE_DATA_BUCKET")

    # API
    API_BASE_URL = os.getenv("SECOPS_API_BASE_URL", f"https://chronicle.{LOCATION}.googleapis.com")
    TIMEOUT = int(os.getenv("SECOPS_REQUEST_TIMEOUT", 60))

    # Base Path for this specific instance's API calls
    INSTANCE_BASE_PATH = (
        f"v1alpha/projects/{PROJECT_ID}/locations/{LOCATION}/instances/{INSTANCE_ID}"
    )

def get_authorized_session():
    """Authenticates using .env credentials and returns a requests.AuthorizedSession."""
    try:
        if not Config.SERVICE_ACCOUNT_FILE:
            raise ValueError("SECOPS_ACCOUNT_JSON not found in .env")
            
        credentials = service_account.Credentials.from_service_account_file(
            Config.SERVICE_ACCOUNT_FILE, scopes=Config.SCOPES
        )
        return requests.AuthorizedSession(credentials)
    except Exception as e:
        print(f"Authentication Error: {e}")
        raise

def _normalize_id(export_id):
    """Helper to ensure we have the full resource path with version for an export ID."""
    # Case 1: Short ID passed (e.g., "f0015a77...")
    if "projects/" not in export_id:
            return f"{Config.INSTANCE_BASE_PATH}/dataExports/{export_id}"
    
    # Case 2: Long ID passed by API, missing the version prefix
    if export_id.startswith("projects/"):
            return f"v1alpha/{export_id}"
            
    return export_id

# --- API FUNCTIONS ---

def fetch_service_account(session):
    """
    Fetches the Chronicle Service Account that must have permissions on the GCS bucket.
    """
    url = f"{Config.API_BASE_URL}/{Config.INSTANCE_BASE_PATH}/dataExports:fetchServiceAccountForDataExport"
    print(f"\n[Action] Fetching Chronicle Service Account...")
    
    resp = session.get(url, timeout=Config.TIMEOUT)
    resp.raise_for_status()
    
    data = resp.json()
    sa_email = data.get("serviceAccountEmail") or data.get("email")
    print(f"Chronicle Service Account: {sa_email}")
    print(f"-> INSTRUCTION: Grant '{sa_email}' the 'Storage Object Admin' role on your target bucket.")
    return sa_email

def list_data_exports(session):
    """
    Lists recent Data Export jobs for this instance.
    """
    url = f"{Config.API_BASE_URL}/{Config.INSTANCE_BASE_PATH}/dataExports"
    print(f"\n[Action] Listing Data Exports...")

    resp = session.get(url, timeout=Config.TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    exports = data.get("dataExports", [])

    if not exports:
        print("No data exports found.")
        return

    print(f"Found {len(exports)} export(s):\n")
    for export in exports:
        name = export.get("name", "UNKNOWN").split("/")[-1] # Show short ID for readability
        stage = export.get("dataExportStatus", {}).get("stage", "UNKNOWN")
        create_time = export.get("createTime", "")
        print(f"ID: {name:<38} | Stage: {stage:<20} | Created: {create_time}")

def cancel_data_export(session, export_id):
    """
    Cancels an in-progress Data Export job.
    """
    full_path = _normalize_id(export_id)
    url = f"{Config.API_BASE_URL}/{full_path}:cancel"
    print(f"\n[Action] Cancelling Data Export job: {export_id}...")

    resp = session.post(url, timeout=Config.TIMEOUT)
    resp.raise_for_status()

    print("Cancel request issued successfully.")
    # Optionally fetch standard status to confirm
    get_data_export_status(session, export_id)

def create_data_export(session, days_back, log_types=None):
    """
    Initiates a new Data Export job.
    """
    url = f"{Config.API_BASE_URL}/{Config.INSTANCE_BASE_PATH}/dataExports"
    
    end_time_dt = datetime.datetime.now(datetime.timezone.utc)
    start_time_dt = end_time_dt - datetime.timedelta(days=days_back)
    time_format = "%Y-%m-%dT%H:%M:%SZ"

    payload = {
        "startTime": start_time_dt.strftime(time_format),
        "endTime": end_time_dt.strftime(time_format),
        "gcsBucket": Config.GCS_BUCKET
    }

    if log_types:
        payload["includeLogTypes"] = [
            f"projects/{Config.PROJECT_ID}/locations/{Config.LOCATION}/instances/{Config.INSTANCE_ID}/logTypes/{lt}"
            for lt in log_types
        ]

    print(f"\n[Action] Creating Data Export Job...")
    print(f"Target: {Config.GCS_BUCKET} | Range: Last {days_back} days")
    if log_types:
        print(f"Log Types: {log_types}")
    
    resp = session.post(url, json=payload, timeout=Config.TIMEOUT)
    resp.raise_for_status()

    export_data = resp.json()
    export_id = export_data.get("name")
    print(f"Success. Job Created: {export_id}")
    return export_id

def get_data_export_status(session, export_id):
    """
    Fetches the current status of a specific Data Export job.
    """
    full_path = _normalize_id(export_id)
    url = f"{Config.API_BASE_URL}/{full_path}"
    resp = session.get(url, timeout=Config.TIMEOUT)
    resp.raise_for_status()
    
    return resp.json()

def track_export_until_completion(session, export_id):
    """Polls the export job status until it is done."""
    print(f"\n[Tracker] Tracking status for: {export_id}")
    print("Press Ctrl+C to stop tracking (job will continue running in background).")
    
    try:
        while True:
            status_data = get_data_export_status(session, export_id)
            state = status_data.get("dataExportStatus", {}).get("stage", "UNKNOWN")
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            print(f"[{timestamp}] Status: {state}")

            if state == "FINISHED_SUCCESS":
                print("\n--- Export COMPLETED SUCCESSFULLY ---")
                break
            elif state in ["FINISHED_FAILURE", "CANCELLED"]:
                print(f"\n--- Export {state} ---")
                print(json.dumps(status_data, indent=2))
                break
            elif state in ["IN_QUEUE", "PROCESSING", "PENDING"]:
                time.sleep(30)
            else:
                print(f"Unknown state '{state}'. Stopping tracker.")
                print(json.dumps(status_data, indent=2))
                break
    except KeyboardInterrupt:
        print("\nTracking stopped by user. Job continues in Chronicle.")

# --- MAIN ---

def main():
    parser = argparse.ArgumentParser(description="Chronicle Enhanced Data Export Tool")

    # Primary Action Group (Mutually Exclusive)
    action_group = parser.add_mutually_exclusive_group()
    
    action_group.add_argument("--create", action="store_true", help="Create a new data export job (Default action if none specified).")
    action_group.add_argument("--track", metavar="EXPORT_ID", help="Track an existing export job.")
    action_group.add_argument("--fetch-sa", action="store_true", help="Fetch the Chronicle Service Account email.")
    action_group.add_argument("--list", action="store_true", help="List recent data export jobs.")
    action_group.add_argument("--cancel", metavar="EXPORT_ID", help="Cancel an in-progress export job.")

    # Creation Options
    parser.add_argument("--days", type=int, default=1, help="[Create] Number of days back to export (default: 1).")
    parser.add_argument("--log-types", nargs='+', help="[Create] Space-separated list of Log Types (e.g. OKTA WINEVTLOG).")

    args = parser.parse_args()

    if not all([Config.PROJECT_ID, Config.INSTANCE_ID, Config.GCS_BUCKET]):
         print("Error: Missing critical .env configuration.")
         return

    try:
        session = get_authorized_session()

        # Determine Action
        if args.fetch_sa:
            fetch_service_account(session)
        elif args.list:
            list_data_exports(session)
        elif args.cancel:
            cancel_data_export(session, args.cancel)
        elif args.track:
            track_export_until_completion(session, args.track)
        else:
            # Default action: Create
            new_id = create_data_export(session, args.days, args.log_types)
            track_export_until_completion(session, new_id)

    except requests_lib.exceptions.HTTPError as e:
        print(f"\nAPI Error: {e}")
        if e.response is not None:
             # Try to print standard Google JSON error if available, else raw text
             try:
                 err_json = e.response.json()
                 print(f"Details: {json.dumps(err_json, indent=2)}")
             except:
                 print(f"API Response: {e.response.text}")

    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
