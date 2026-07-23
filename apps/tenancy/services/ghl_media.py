"""GoHighLevel media library helpers (folders + file upload).

Mirrors Snapshot JobTracker: folders live in GHL; we store folder ids locally
and upload bytes to ``POST /medias/upload-file`` with ``parentId``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from django.conf import settings

from apps.common.exceptions import IntegrationError, ValidationError
from apps.tenancy.models import Location, LocationMediaFolder

logger = logging.getLogger("apps.tenancy.ghl_media")

# Prefer GHL media API version used by JobTracker for folder/upload endpoints.
MEDIA_API_VERSION = "2021-07-28"

# Folders created on location onboard.
ONBOARD_MEDIA_FOLDERS: tuple[str, ...] = (
    LocationMediaFolder.FOLDER_SUPPORT_MEDIA,
)


def _api_base() -> str:
    return settings.GHL["API_BASE_URL"].rstrip("/")


def _json_headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Version": MEDIA_API_VERSION,
        "Authorization": f"Bearer {access_token}",
    }


def _upload_headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Version": MEDIA_API_VERSION,
        "Authorization": f"Bearer {access_token}",
    }


def resolve_location_access_token(location: Location) -> Optional[str]:
    access = (location.access_token or "").strip()
    if access:
        return access
    agency = getattr(location, "agency", None)
    if agency is not None:
        return (agency.access_token or "").strip() or None
    return None


def refresh_location_access_token(location: Location) -> Optional[str]:
    """Mint a fresh location token (agency exchange or location refresh)."""
    from apps.authentication.services.oauth import GHLOAuthService
    from apps.tenancy.services.provisioning import ProvisioningService

    location = (
        Location.objects.select_related("agency").filter(pk=location.pk).first()
        or location
    )
    service = GHLOAuthService()
    agency = getattr(location, "agency", None)

    if agency is not None and (agency.refresh_token or "").strip():
        try:
            agency_payload = service.refresh_token(agency.refresh_token.strip())
            company_token = (agency_payload.get("access_token") or "").strip()
            if not company_token:
                return None
            ProvisioningService.upsert_agency(
                company_id=agency.ghl_company_id, tokens=agency_payload
            )
            loc_tokens = service.exchange_location_token(
                company_id=agency.ghl_company_id,
                company_token=company_token,
                location_id=location.ghl_location_id,
            )
            ProvisioningService.upsert_location(
                location_id=location.ghl_location_id,
                agency=agency,
                tokens=loc_tokens,
            )
            location.refresh_from_db()
            return (location.access_token or "").strip() or None
        except Exception:
            logger.exception(
                "Failed refreshing location token via agency location=%s",
                location.ghl_location_id,
            )

    refresh = (location.refresh_token or "").strip()
    if refresh:
        try:
            payload = service.refresh_token(refresh)
            ProvisioningService.upsert_location(
                location_id=location.ghl_location_id, tokens=payload
            )
            location.refresh_from_db()
            return (location.access_token or "").strip() or None
        except Exception:
            logger.exception(
                "Failed refreshing location token location=%s",
                location.ghl_location_id,
            )
    return None


def ensure_location_access_token(
    location: Location, *, force_refresh: bool = False
) -> str:
    """Return a usable location token; refresh when missing or force_refresh."""
    token = None if force_refresh else resolve_location_access_token(location)
    if not token or force_refresh:
        token = refresh_location_access_token(location) or token
    if not token:
        raise IntegrationError(
            "No GHL access token available for media operations.",
            code="missing_ghl_token",
        )
    return token


def extract_media_folder_id(payload: Any) -> Optional[str]:
    if not payload:
        return None
    if isinstance(payload, str):
        return payload.strip() or None
    if not isinstance(payload, dict):
        return None
    for key in ("id", "_id", "fileId", "folderId"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    for nested_key in ("file", "folder", "data", "medias"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            found = extract_media_folder_id(nested)
            if found:
                return found
        if isinstance(nested, list):
            for item in nested:
                found = extract_media_folder_id(item)
                if found:
                    return found
    return None


def _normalize_media_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("files", "medias", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _normalize_media_items(value)
            if nested:
                return nested
    return [payload]


def fetch_ghl_media_items(
    access_token: str,
    location_id: str,
    *,
    parent_id: Optional[str] = None,
    media_type: str = "folder",
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "altType": "location",
        "altId": location_id,
        "type": media_type,
        "fetchAll": "true",
    }
    if parent_id:
        params["parentId"] = parent_id
    try:
        resp = requests.get(
            f"{_api_base()}/medias/files",
            headers=_json_headers(access_token),
            params=params,
            timeout=60,
        )
    except requests.RequestException as exc:
        logger.warning("GHL media list failed location=%s err=%s", location_id, exc)
        return []
    if resp.status_code >= 400:
        logger.warning(
            "GHL media list error location=%s status=%s body=%s",
            location_id,
            resp.status_code,
            (resp.text or "")[:400],
        )
        return []
    try:
        return _normalize_media_items(resp.json())
    except ValueError:
        return []


def find_ghl_media_folder_id_by_name(
    access_token: str, location_id: str, folder_name: str
) -> Optional[str]:
    target = folder_name.strip().lower()
    if not target:
        return None
    for item in fetch_ghl_media_items(access_token, location_id):
        item_name = (item.get("name") or "").strip().lower()
        if item_name != target:
            continue
        item_type = (item.get("type") or "folder").lower()
        if item_type not in ("folder", ""):
            continue
        folder_id = extract_media_folder_id(item)
        if folder_id:
            return folder_id
    return None


def create_ghl_media_folder(
    access_token: str,
    location_id: str,
    name: str,
    *,
    parent_id: Optional[str] = None,
) -> str:
    payload: dict[str, Any] = {
        "altId": location_id,
        "altType": "location",
        "name": name,
    }
    if parent_id:
        payload["parentId"] = parent_id
    try:
        resp = requests.post(
            f"{_api_base()}/medias/folder",
            headers=_json_headers(access_token),
            json=payload,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise IntegrationError(
            "Failed to reach GoHighLevel media API.",
            code="ghl_network_error",
            details={"error": str(exc)},
        ) from exc

    if resp.status_code >= 400:
        raise IntegrationError(
            "GoHighLevel could not create the media folder.",
            code="ghl_media_folder_error",
            details={"status": resp.status_code, "body": (resp.text or "")[:500]},
        )

    try:
        folder_id = extract_media_folder_id(resp.json())
    except ValueError:
        folder_id = None
    if not folder_id:
        # Race: folder may already exist.
        folder_id = find_ghl_media_folder_id_by_name(access_token, location_id, name)
    if not folder_id:
        raise IntegrationError(
            "GHL created a folder but did not return an id.",
            code="ghl_media_folder_missing_id",
        )
    return folder_id


def ensure_location_media_folder(
    location: Location,
    folder_name: str,
    *,
    access_token: Optional[str] = None,
) -> LocationMediaFolder:
    """Resolve or create a named GHL folder and persist its id."""
    existing = (
        LocationMediaFolder.objects.filter(
            location=location, name=folder_name, is_active=True
        )
        .exclude(ghl_folder_id="")
        .first()
    )
    if existing is not None:
        return existing

    token = (access_token or "").strip()
    if not token:
        # Prefer a freshly minted location token — stored JWTs expire ~24h.
        token = ensure_location_access_token(location, force_refresh=True)

    ghl_location_id = location.ghl_location_id
    folder_id = find_ghl_media_folder_id_by_name(token, ghl_location_id, folder_name)
    if not folder_id:
        try:
            folder_id = create_ghl_media_folder(token, ghl_location_id, folder_name)
        except IntegrationError as exc:
            details = getattr(exc, "details", None) or {}
            if details.get("status") in (401, 403):
                token = ensure_location_access_token(location, force_refresh=True)
                folder_id = find_ghl_media_folder_id_by_name(
                    token, ghl_location_id, folder_name
                ) or create_ghl_media_folder(token, ghl_location_id, folder_name)
            else:
                raise

    obj, _ = LocationMediaFolder.objects.update_or_create(
        location=location,
        name=folder_name,
        defaults={"ghl_folder_id": folder_id, "is_active": True},
    )
    logger.info(
        "Ensured media folder location=%s name=%s ghl_id=%s",
        ghl_location_id,
        folder_name,
        folder_id,
    )
    return obj


def ensure_location_onboard_media_folders(
    location: Location,
    *,
    access_token: Optional[str] = None,
) -> dict[str, str]:
    """Create standard media folders after a location is onboarded."""
    out: dict[str, str] = {}
    errors: list[str] = []
    for name in ONBOARD_MEDIA_FOLDERS:
        try:
            folder = ensure_location_media_folder(
                location, name, access_token=access_token
            )
            out[name] = folder.ghl_folder_id
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.exception(
                "Failed ensuring media folder location=%s name=%s",
                location.ghl_location_id,
                name,
            )
    if errors and not out:
        raise IntegrationError(
            "Could not create GHL media folders for this location.",
            code="ghl_media_folder_ensure_failed",
            details={"errors": errors},
        )
    return out


def upload_file_to_ghl_media(
    *,
    access_token: str,
    parent_id: str,
    name: str,
    file_obj,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict[str, Any]:
    """Upload a file into a GHL media folder. Returns GHL JSON (fileId, url, …)."""
    fname = filename or getattr(file_obj, "name", None) or "file"
    ct = content_type or getattr(file_obj, "content_type", None) or "application/octet-stream"
    if hasattr(file_obj, "seek"):
        try:
            file_obj.seek(0)
        except Exception:
            pass

    url = f"{_api_base()}/medias/upload-file"
    files = {"file": (fname, file_obj, ct)}
    data = {"parentId": parent_id, "name": name or fname}

    try:
        resp = requests.post(
            url,
            headers=_upload_headers(access_token),
            data=data,
            files=files,
            timeout=120,
        )
    except requests.RequestException as exc:
        raise IntegrationError(
            "Failed to reach GoHighLevel media upload API.",
            code="ghl_network_error",
            details={"error": str(exc)},
        ) from exc

    if resp.status_code not in (200, 201):
        msg = (resp.text or "")[:300]
        try:
            err = resp.json()
            msg = str(err.get("message") or err.get("error") or msg)
        except ValueError:
            pass
        if resp.status_code == 413:
            raise ValidationError("File is too large for GoHighLevel media.")
        raise IntegrationError(
            msg or "GoHighLevel media upload failed.",
            code="ghl_media_upload_error",
            details={"status": resp.status_code},
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise IntegrationError(
            "GoHighLevel returned a non-JSON upload response.",
            code="ghl_invalid_json",
        ) from exc

    if not isinstance(payload, dict):
        raise IntegrationError(
            "Unexpected GoHighLevel upload response.",
            code="ghl_invalid_upload_response",
        )
    return payload


def upload_to_location_folder(
    location: Location,
    *,
    folder_name: str,
    file_obj,
    display_name: str,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict[str, Any]:
    """Ensure folder exists, upload file, return normalized attachment metadata."""
    token = ensure_location_access_token(location, force_refresh=True)
    folder = ensure_location_media_folder(location, folder_name, access_token=token)
    try:
        result = upload_file_to_ghl_media(
            access_token=token,
            parent_id=folder.ghl_folder_id,
            name=display_name,
            file_obj=file_obj,
            content_type=content_type,
            filename=filename,
        )
    except IntegrationError as exc:
        details = getattr(exc, "details", None) or {}
        if details.get("status") in (401, 403):
            token = ensure_location_access_token(location, force_refresh=True)
            result = upload_file_to_ghl_media(
                access_token=token,
                parent_id=folder.ghl_folder_id,
                name=display_name,
                file_obj=file_obj,
                content_type=content_type,
                filename=filename,
            )
        else:
            raise
    file_id = (
        str(result.get("fileId") or result.get("id") or result.get("_id") or "").strip()
    )
    file_url = str(result.get("url") or result.get("fileUrl") or "").strip()
    if not file_url:
        raise IntegrationError(
            "GoHighLevel upload succeeded but returned no file URL.",
            code="ghl_media_missing_url",
            details={"result": {k: result.get(k) for k in ("fileId", "id", "url")}},
        )
    return {
        "ghl_file_id": file_id,
        "url": file_url,
        "name": display_name or filename or "file",
        "content_type": content_type or "",
        "raw": result,
    }
