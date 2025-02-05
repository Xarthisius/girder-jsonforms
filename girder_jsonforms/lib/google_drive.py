import os
import pickle
import logging

from google.auth.transport.requests import Request

# from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger("google_drive")
logprint = logger
# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_credentials():
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.pickle")

    if os.path.exists(path):
        with open(path, "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise ValueError("No valid credentials found")
            # flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(path, "wb") as token:
            pickle.dump(creds, token)
    return creds


def authenticate_gdrive():
    # Load credentials from a file or any other secure source
    # Replace 'path_to_credentials.json' with the actual path to your credentials file
    credentials = get_credentials()
    return build("drive", "v3", credentials=credentials)


def create_folders(service, folder_id, path):
    if service is None:
        logger.exception("Service not initialized. Failed to create folder.")
        return
    current_folder_id = folder_id
    folders = path.split("/")
    for folder in folders:
        if folder:
            # Check if folder already exists
            query = f"'{current_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{folder}' and trashed=false"
            response = (
                service.files()
                .list(
                    q=query,
                    fields="files(id)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                )
                .execute()
            )
            existing_folders = response.get("files", [])
            if existing_folders:
                logprint.error(f"Folder '{folder}' already exists")
                logprint.error(response)
                current_folder_id = existing_folders[0]["id"]
            else:
                logprint.error(f"Creating folder '{folder}'")
                file_metadata = {
                    "name": folder,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [current_folder_id],
                }
                folder_result = (
                    service.files()
                    .create(body=file_metadata, fields="id", supportsAllDrives=True)
                    .execute()
                )
                logprint.error(
                    f"Folder '{folder}' created with ID: {folder_result['id']}"
                )
                current_folder_id = folder_result["id"]

    return current_folder_id


def upload_file_to_gdrive(service, folder_id, path, file_handle, mimetype="text/plain"):
    if service is None:
        logger.exception("Service not initialized. Failed to upload file.")
        return
    file_path, file_name = os.path.split(path)
    folder_id = create_folders(service, folder_id, file_path)
    logprint.error(f"Uploading file '{file_name}' to folder '{folder_id}'")

    # Check if file already exists in the folder
    query = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
    response = (
        service.files()
        .list(
            q=query,
            fields="files(id)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        .execute()
    )
    existing_files = response.get("files", [])
    media = MediaIoBaseUpload(file_handle, mimetype=mimetype)
    if existing_files:
        file_id = existing_files[0]["id"]
        file_result = (
            service.files()
            .update(fileId=file_id, media_body=media, supportsAllDrives=True)
            .execute()
        )
        logprint.error(f'File {file_name} updated with ID: {file_result["id"]}')
    else:
        file_metadata = {"name": file_name, "parents": [folder_id]}
        file_result = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        logprint.error(
            f'File {file_metadata["name"]} uploaded with ID: {file_result["id"]}'
        )
    return file_result["id"]


# Example usage
if __name__ == "__main__":
    # folder_id = "1WgY3HJ0bxzQc-IA_dBdiwb9Hvq6ho3HS"  # Replace with the actual folder ID
    folder_id = "13u4Citrr09FETrPDn2gJmBHWeaO0ylji"
    path = "subfolder/subfolder2/subfolder4/file.txt"
    file_handle = open("file.txt", "rb")  # Replace 'file.txt' with the actual file path
    service = authenticate_gdrive()
    file_id = upload_file_to_gdrive(service, folder_id, path, file_handle)
