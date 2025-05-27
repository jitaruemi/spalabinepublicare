import os
import json
import requests
from io import BytesIO
from docx import Document
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from datetime import datetime

# ============ CONFIG ===============
GOOGLE_SERVICE_ACCOUNT = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
DRIVE_FOLDER_ID = os.environ["GOOGLE_DRIVE_FOLDER_ID"]
PUBLISHED_FILE_ID = os.environ["PUBLISHED_FILE_ID"]  # ID-ul fișierului published.json de pe Drive
WP_URL = os.environ["WP_URL"]
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
WP_CATEGORY_ID = int(os.environ["WP_CATEGORY_ID"])

# ============ GOOGLE DRIVE SETUP ===============
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        GOOGLE_SERVICE_ACCOUNT,
        scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

# ============ PUBLISHED.JSON SYNC ===============
def load_published(service):
    try:
        request = service.files().get_media(fileId=PUBLISHED_FILE_ID)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        data = json.load(fh)

        # Dacă JSON-ul este listă, o convertim în dict conform așteptărilor
        if isinstance(data, list):
            return {"published_ids": data, "last_published_date": ""}
        elif isinstance(data, dict):
            return data
        else:
            # alt tip neașteptat, inițializare default
            return {"published_ids": [], "last_published_date": ""}
    except Exception as e:
        print(f"⚠️ Eroare la citirea published.json: {e}")
        return {"published_ids": [], "last_published_date": ""}

def save_published(service, published_data):
    try:
        data = json.dumps(published_data, indent=2).encode('utf-8')
        media_body = MediaIoBaseUpload(BytesIO(data), mimetype='application/json')
        service.files().update(fileId=PUBLISHED_FILE_ID, media_body=media_body).execute()
    except Exception as e:
        print(f"⚠️ Eroare la salvarea published.json: {e}")

# ============ LIST FILES ===============
def list_docx_files(service):
    results = service.files().list(
        q=f"'{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'",
        fields="files(id, name)"
    ).execute()
    return results.get('files', [])

# ============ DOWNLOAD FILE ===============
def download_file(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()

# ============ DOCX TO HTML ===============
def docx_to_html(content_bytes):
    doc = Document(BytesIO(content_bytes))
    html = ""
    for para in doc.paragraphs:
        if para.text.strip():
            html += f"<p>{para.text}</p>\n"
    return html

# ============ PUBLISH TO WP ===============
def publish_to_wp(title, content_html):
    data = {
        "title": title,
        "content": content_html,
        "status": "publish",
        "categories": [WP_CATEGORY_ID]
    }
    response = requests.post(
        WP_URL,
        auth=(WP_USER, WP_PASS),
        json=data
    )
    if response.status_code == 201:
        print(f"✔️ Publicat: {title}")
        return True
    else:
        print(f"❌ Eroare: {response.status_code} - {response.text}")
        return False

# ============ MAIN LOGIC ===============
def main():
    service = get_drive_service()
    published_data = load_published(service)
    published_ids = published_data.get("published_ids", [])
    last_date = published_data.get("last_published_date", "")

    today = datetime.now().strftime("%Y-%m-%d")
    if today == last_date:
        print("🛑 Astăzi deja s-a publicat un articol. Oprire.")
        return

    files = list_docx_files(service)

    for file in files:
        if file['id'] in published_ids:
            continue

        print(f"⏳ Procesare: {file['name']}")
        content_bytes = download_file(service, file['id'])
        html_content = docx_to_html(content_bytes)
        title = os.path.splitext(file['name'])[0]

        if publish_to_wp(title, html_content):
            published_ids.append(file['id'])
            published_data["published_ids"] = published_ids
            published_data["last_published_date"] = today
            save_published(service, published_data)
            break  # publică doar un articol per rulare

if __name__ == "__main__":
    main()
