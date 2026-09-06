from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.app_user import AppUser as User
from models.managebac import ManageBacConnection, ManageBacSyncRun
from schemas.managebac import (
    ManageBacConnectResponse,
    ManageBacConnectionSettings,
    ManageBacConnectionStatus,
    ManageBacDisconnectResponse,
    ManageBacFeedRequest,
    ManageBacSyncRunsResponse,
    ManageBacSyncSummary,
    ManageBacValidationResponse,
)
from services.auth import get_current_user
from services.managebac_security import (
    ManageBacConfigurationError,
    ManageBacFetchError,
    ManageBacIntegrationError,
    ManageBacURLValidationError,
)
from services.managebac_ical import ManageBacCalendarParseError
from services.managebac_sync import (
    connect_managebac_feed,
    connection_status_payload,
    disconnect_managebac,
    sync_managebac_connection,
    utc_now_naive,
    validate_managebac_feed,
    validation_payload,
)


router = APIRouter(prefix="/api/integrations/managebac", tags=["managebac"])


def _raise_integration_error(error: ManageBacIntegrationError):
    if isinstance(error, ManageBacConfigurationError):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, (ManageBacURLValidationError, ManageBacCalendarParseError)):
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, ManageBacFetchError) and error.http_status == 429:
        http_status = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        http_status = status.HTTP_502_BAD_GATEWAY
    raise HTTPException(
        status_code=http_status,
        detail={"code": error.code, "message": error.safe_detail},
    ) from error


@router.get("/status", response_model=ManageBacConnectionStatus)
def get_managebac_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.user_id == current_user.id
    ).first()
    return connection_status_payload(connection)


@router.post("/validate", response_model=ManageBacValidationResponse)
async def validate_managebac_connection(
    data: ManageBacFeedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validated = await validate_managebac_feed(db, current_user.id, data.feed_url)
    except ManageBacIntegrationError as error:
        _raise_integration_error(error)
    return validation_payload(validated)


@router.post("/connect", response_model=ManageBacConnectResponse)
async def connect_managebac(
    data: ManageBacFeedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        connection, validated, summary = await connect_managebac_feed(
            db,
            current_user.id,
            data.feed_url,
        )
    except ManageBacIntegrationError as error:
        db.rollback()
        _raise_integration_error(error)
    return {
        "connection": connection_status_payload(connection),
        "validation": validation_payload(validated),
        "sync": summary,
    }


@router.post("/sync", response_model=ManageBacSyncSummary)
async def sync_managebac_now(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.user_id == current_user.id
    ).first()
    if connection is None:
        raise HTTPException(status_code=404, detail="尚未连接 ManageBac")
    now = utc_now_naive()
    if (
        connection.last_sync_started_at
        and connection.last_sync_started_at > now - timedelta(seconds=30)
    ):
        raise HTTPException(
            status_code=429,
            detail={"code": "sync_rate_limited", "message": "同步请求过于频繁，请稍后再试"},
        )

    lease_owner = f"manual-{uuid4().hex[:20]}"
    claimed = db.query(ManageBacConnection).filter(
        ManageBacConnection.id == connection.id,
        or_(
            ManageBacConnection.lease_expires_at.is_(None),
            ManageBacConnection.lease_expires_at < now,
        ),
    ).update(
        {
            ManageBacConnection.lease_owner: lease_owner,
            ManageBacConnection.lease_expires_at: now + timedelta(minutes=5),
        },
        synchronize_session=False,
    )
    db.commit()
    if not claimed:
        raise HTTPException(
            status_code=429,
            detail={"code": "sync_in_progress", "message": "已有同步正在进行，请稍后再试"},
        )
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.id == connection.id
    ).one()
    try:
        return await sync_managebac_connection(db, connection, trigger="manual")
    finally:
        db.rollback()
        current = db.query(ManageBacConnection).filter(
            ManageBacConnection.id == connection.id
        ).first()
        if current and current.lease_owner == lease_owner:
            current.lease_owner = None
            current.lease_expires_at = None
            db.commit()


@router.patch("/settings", response_model=ManageBacConnectionStatus)
def update_managebac_settings(
    data: ManageBacConnectionSettings,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.user_id == current_user.id
    ).first()
    if connection is None:
        raise HTTPException(status_code=404, detail="尚未连接 ManageBac")
    if data.enabled and connection.status == "reconnect_required":
        raise HTTPException(status_code=409, detail="订阅地址已经失效，请重新连接")
    connection.enabled = data.enabled
    connection.status = "active" if data.enabled else "paused"
    connection.next_sync_at = utc_now_naive() if data.enabled else None
    connection.last_error_code = None if data.enabled else connection.last_error_code
    connection.last_error_detail = None if data.enabled else connection.last_error_detail
    db.commit()
    db.refresh(connection)
    return connection_status_payload(connection)


@router.get("/runs", response_model=ManageBacSyncRunsResponse)
def list_managebac_runs(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.user_id == current_user.id
    ).first()
    if connection is None:
        return {"items": []}
    rows = db.query(ManageBacSyncRun).filter(
        ManageBacSyncRun.connection_id == connection.id
    ).order_by(ManageBacSyncRun.started_at.desc(), ManageBacSyncRun.id.desc()).limit(limit).all()
    return {"items": rows}


@router.delete("/disconnect", response_model=ManageBacDisconnectResponse)
def disconnect_managebac_connection(
    delete_imported_tasks: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = disconnect_managebac(
        db,
        current_user.id,
        delete_imported_tasks=delete_imported_tasks,
    )
    if deleted:
        try:
            from services.schedule_triggers import analyze_after_mutation

            analyze_after_mutation(db, current_user.id, "managebac_disconnect")
        except Exception:
            db.rollback()
    return {"disconnected": True, "deleted_tasks": deleted}
