import logging
import sys
import google.auth
import google.auth.impersonated_credentials
import google.auth.transport.requests
from googleapiclient.discovery import build

# Configure logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

def test_iap():
    project = "i4g-dev"
    impersonate_sa = "sa-app@i4g-dev.iam.gserviceaccount.com"
    audience = "544936845045-a87u04lgc7go7asc4nhed36ka50iqh0h.apps.googleusercontent.com"

    source_creds, _ = google.auth.default()
    request = google.auth.transport.requests.Request()

    print("Creating impersonated credentials...")
    compute_creds = google.auth.impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=impersonate_sa,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600
    )
    
    print("Creating IDTokenCredentials...")
    id_token_creds = google.auth.impersonated_credentials.IDTokenCredentials(
        target_credentials=compute_creds,
        target_audience=audience,
        include_email=True
    )
    
    print("Refreshing token...")
    id_token_creds.refresh(request)
    print(f"Token: {id_token_creds.token[:10]}...")

if __name__ == "__main__":
    try:
        test_iap()
    except Exception as e:
        print(f"Error: {e}")
