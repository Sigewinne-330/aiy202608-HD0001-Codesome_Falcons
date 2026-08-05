from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.reminder import (
    ReminderDelivery,
    ReminderDigest,
    ReminderPreference,
    ReminderRoleCard,
)
from models.user import User
from schemas.reminder import (
    DeliveryHistoryItem,
    DemoReminderChannelOutcome,
    DemoReminderResponse,
    ManualReminderRunRequest,
    ReminderHistoryItem,
    ReminderHistoryResponse,
    ReminderPreferenceResponse,
    ReminderPreferenceUpdate,
    ReminderRunResponse,
    RoleCardCreate,
    RoleCardDetail,
    RoleCardImportRequest,
    RoleCardSummary,
    RoleCardUpdate,
)
from services.auth import get_current_admin, get_current_user
from services.reminder_orchestrator import ReminderOrchestrator
from services.reminder_preferences import (
    get_default_role_card,
    list_active_role_cards,
    role_card_visible_to_user,
    resolve_preferences,
    update_preferences,
)
from services.role_card_import import (
    generate_private_role_card_slug,
    normalize_imported_role_card,
)


router = APIRouter(tags=["reminders"])


def get_reminder_orchestrator() -> ReminderOrchestrator:
    return ReminderOrchestrator()


def _preference_response(db: Session, user_id: int) -> ReminderPreferenceResponse:
    preferences = resolve_preferences(db, user_id)
    return ReminderPreferenceResponse(
        enabled=preferences.enabled,
        language=preferences.language,
        timezone=preferences.timezone,
        cadence_offsets=list(preferences.cadence_offsets),
        daily_dispatch_time=preferences.daily_dispatch_time,
        default_task_reminder_offsets_minutes=list(
            preferences.default_task_reminder_offsets_minutes
        ),
        email_enabled=preferences.email_enabled,
        chat_enabled=preferences.chat_enabled,
        role_card=(
            RoleCardSummary.model_validate(preferences.role_card)
            if preferences.role_card
            else None
        ),
    )


@router.get("/api/reminders/preferences", response_model=ReminderPreferenceResponse)
def get_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _preference_response(db, current_user.id)


@router.put("/api/reminders/preferences", response_model=ReminderPreferenceResponse)
def put_preferences(
    data: ReminderPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    values = data.model_dump(exclude_unset=True)
    try:
        update_preferences(
            db,
            current_user.id,
            enabled=values.get("enabled"),
            language=values.get("language"),
            timezone=values.get("timezone"),
            cadence_offsets=values.get("cadence_offsets"),
            daily_dispatch_time=values.get("daily_dispatch_time"),
            default_task_reminder_offsets_minutes=values.get(
                "default_task_reminder_offsets_minutes"
            ),
            email_enabled=values.get("email_enabled"),
            chat_enabled=values.get("chat_enabled"),
            role_card_id=values.get("role_card_id"),
            role_card_supplied="role_card_id" in data.model_fields_set,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _preference_response(db, current_user.id)


@router.get("/api/reminder-role-cards", response_model=list[RoleCardSummary])
def list_role_cards(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        RoleCardSummary.model_validate(card)
        for card in list_active_role_cards(db, current_user.id)
    ]


@router.get("/api/reminder-role-cards/{card_id}", response_model=RoleCardDetail)
def get_role_card(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.id == card_id,
            ReminderRoleCard.is_active.is_(True),
            role_card_visible_to_user(current_user.id),
        )
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    return RoleCardDetail.model_validate(card)


@router.post(
    "/api/reminder-role-cards/import",
    response_model=RoleCardDetail,
    status_code=status.HTTP_201_CREATED,
)
def import_private_role_card(
    data: RoleCardImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        normalized = normalize_imported_role_card(data.card)
        card = ReminderRoleCard(
            **normalized.model_dump(exclude={"slug", "is_active"}),
            slug=generate_private_role_card_slug(db, normalized.slug),
            scope="private",
            owner_user_id=current_user.id,
            created_by_user_id=current_user.id,
            is_active=True,
            is_builtin=False,
        )
        db.add(card)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="角色卡导入冲突，请重试") from exc
    db.refresh(card)
    return RoleCardDetail.model_validate(card)


@router.patch(
    "/api/reminder-role-cards/{card_id}", response_model=RoleCardDetail
)
def update_private_role_card(
    card_id: int,
    data: RoleCardUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.id == card_id,
            ReminderRoleCard.scope == "private",
            ReminderRoleCard.owner_user_id == current_user.id,
        )
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(card, key, value)
    card.created_by_user_id = current_user.id
    db.commit()
    db.refresh(card)
    return RoleCardDetail.model_validate(card)


@router.delete("/api/reminder-role-cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_private_role_card(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.id == card_id,
            ReminderRoleCard.scope == "private",
            ReminderRoleCard.owner_user_id == current_user.id,
        )
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    card.is_active = False
    preference = (
        db.query(ReminderPreference)
        .filter(
            ReminderPreference.user_id == current_user.id,
            ReminderPreference.role_card_id == card.id,
        )
        .first()
    )
    if preference:
        fallback = get_default_role_card(db)
        preference.role_card_id = fallback.id if fallback else None
        preference.version = int(preference.version or 0) + 1
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/reminders/history", response_model=ReminderHistoryResponse)
def reminder_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    digests = (
        db.query(ReminderDigest)
        .filter(ReminderDigest.user_id == current_user.id)
        .order_by(ReminderDigest.created_at.desc(), ReminderDigest.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = []
    for digest in digests:
        deliveries = (
            db.query(ReminderDelivery)
            .filter(ReminderDelivery.digest_id == digest.id)
            .order_by(ReminderDelivery.id.asc())
            .all()
        )
        items.append(
            ReminderHistoryItem(
                id=digest.id,
                local_date=digest.local_date,
                subject=digest.subject,
                body_text=digest.body_text,
                generation_mode=(
                    digest.generation_mode.value if digest.generation_mode else None
                ),
                role_card_id=digest.role_card_id,
                item_snapshot=digest.item_snapshot or [],
                created_at=digest.created_at,
                deliveries=[
                    DeliveryHistoryItem(
                        channel=row.channel,
                        status=row.status.value,
                        attempt_count=row.attempt_count,
                        last_error_code=row.last_error_code,
                        delivered_at=row.delivered_at,
                    )
                    for row in deliveries
                ],
            )
        )
    return ReminderHistoryResponse(items=items, limit=limit, offset=offset)


@router.post("/api/reminders/demo-send", response_model=DemoReminderResponse)
async def send_demo_reminder(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    orchestrator: ReminderOrchestrator = Depends(get_reminder_orchestrator),
):
    if not settings.DEMO_REMINDER_ENABLED:
        raise HTTPException(status_code=404, detail="演示提醒功能未启用")
    try:
        result = await orchestrator.send_demo(db, user=current_user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="演示提醒生成失败，请稍后重试") from exc
    outcomes = result["outcomes"]
    return DemoReminderResponse(
        message="演示提醒已处理",
        subject=str(result["subject"]),
        chat=DemoReminderChannelOutcome(
            status=outcomes["chat"].status,
            error_code=outcomes["chat"].error_code,
        ),
        email=DemoReminderChannelOutcome(
            status=outcomes["email"].status,
            error_code=outcomes["email"].error_code,
        ),
    )


@router.post(
    "/api/admin/reminder-role-cards",
    response_model=RoleCardDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_role_card(
    data: RoleCardCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    card = ReminderRoleCard(
        **data.model_dump(),
        scope="global",
        owner_user_id=None,
        created_by_user_id=admin.id,
        is_builtin=False,
    )
    db.add(card)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="角色卡 slug 已存在") from exc
    db.refresh(card)
    return RoleCardDetail.model_validate(card)


@router.patch(
    "/api/admin/reminder-role-cards/{card_id}", response_model=RoleCardDetail
)
def update_role_card(
    card_id: int,
    data: RoleCardUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    card = db.query(ReminderRoleCard).filter(ReminderRoleCard.id == card_id).first()
    if not card or card.scope != "global" or card.owner_user_id is not None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(card, key, value)
    card.created_by_user_id = admin.id
    db.commit()
    db.refresh(card)
    return RoleCardDetail.model_validate(card)


@router.post("/api/admin/reminders/run", response_model=ReminderRunResponse)
async def run_reminders(
    data: ManualReminderRunRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
    orchestrator: ReminderOrchestrator = Depends(get_reminder_orchestrator),
):
    now = data.evaluation_time or datetime.now(timezone.utc)
    summary = await orchestrator.run(
        db,
        now_utc=now,
        only_user_id=data.user_id,
        deliver=data.deliver,
    )
    return ReminderRunResponse(**summary.__dict__)
