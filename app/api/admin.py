"""Админка: участники, ссылки, модерация, челленджи, экспорт."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import sqlalchemy as sa
from flask import Response, jsonify, request

from .. import auth
from ..auth import current_member, require_admin
from ..domain import challenges as ch
from ..domain import events
from ..domain.errors import DomainError, NotFound
from ..domain.time_utils import current_week_start, msk_today, week_start
from ..extensions import db
from ..models import (
    Book,
    Challenge,
    ChallengeResult,
    ClubEvent,
    Member,
    Quote,
    ReadingEntry,
    utcnow,
)
from . import api_bp, as_date, as_int, body


# --- участники -------------------------------------------------------------------

@api_bp.get("/admin/members")
@require_admin
def admin_members():
    members = db.session.execute(sa.select(Member).order_by(Member.full_name)).scalars().all()
    return jsonify(
        {
            "members": [
                {
                    "id": m.id,
                    "full_name": m.full_name,
                    "role": m.role,
                    "is_active": m.is_active,
                    "pin_is_set": m.pin_is_set,
                    "joined_at": m.joined_at.isoformat(),
                }
                for m in members
            ]
        }
    )


@api_bp.post("/admin/members")
@require_admin
def admin_create_member():
    """Завести участника и сразу получить его персональную ссылку."""
    data = body()
    name = str(data.get("full_name", "")).strip()
    if not name:
        raise DomainError("Укажите ФИО участника", code="name_required")

    raw, prefix, digest = auth.issue_token()
    member = Member(
        full_name=name,
        role="admin" if data.get("role") == "admin" else "member",
        token_prefix=prefix,
        token_hash=digest,
        joined_at=msk_today(),
    )
    db.session.add(member)
    db.session.flush()
    events.record(db.session, "joined", member.id, {"full_name": member.full_name})
    db.session.commit()

    return (
        jsonify({"member_id": member.id, "full_name": member.full_name,
                 "link": auth.member_link(raw)}),
        201,
    )


@api_bp.post("/admin/members/<int:member_id>/link")
@require_admin
def admin_reissue_link(member_id: int):
    """Перевыпустить ссылку: старая перестаёт работать, PIN сбрасывается."""
    member = db.session.get(Member, member_id)
    if member is None:
        raise NotFound("Участник не найден")
    raw, prefix, digest = auth.issue_token()
    member.token_prefix = prefix
    member.token_hash = digest
    member.pin_hash = None
    member.pin_set_at = None
    member.failed_attempts = 0
    member.locked_until = None
    member.auth_version += 1  # мгновенно разлогинивает все устройства
    db.session.commit()
    return jsonify({"member_id": member.id, "link": auth.member_link(raw)})


@api_bp.patch("/admin/members/<int:member_id>")
@require_admin
def admin_patch_member(member_id: int):
    member = db.session.get(Member, member_id)
    if member is None:
        raise NotFound("Участник не найден")
    data = body()
    if "full_name" in data:
        name = str(data["full_name"]).strip()
        if not name:
            raise DomainError("ФИО не может быть пустым", code="name_required")
        member.full_name = name
    if "is_active" in data:
        member.is_active = str(data["is_active"]).lower() in {"1", "true", "yes", "on"}
        if not member.is_active:
            member.auth_version += 1
    if "role" in data and data["role"] in {"member", "admin"}:
        member.role = data["role"]
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.delete("/admin/members/<int:member_id>")
@require_admin
def admin_delete_member(member_id: int):
    """Удаление вместе с историей. Обычно достаточно is_active=false."""
    member = db.session.get(Member, member_id)
    if member is None:
        raise NotFound("Участник не найден")
    if member.id == current_member().id:
        raise DomainError("Нельзя удалить самого себя", code="self_delete")
    db.session.delete(member)
    db.session.commit()
    return jsonify({"ok": True})


# --- модерация журнала -----------------------------------------------------------

@api_bp.get("/admin/entries/flagged")
@require_admin
def admin_flagged():
    rows = (
        db.session.execute(
            sa.select(ReadingEntry)
            .where(ReadingEntry.is_flagged.is_(True), ReadingEntry.deleted_at.is_(None))
            .order_by(ReadingEntry.created_at.desc())
        )
        .scalars()
        .all()
    )
    return jsonify(
        {
            "entries": [
                {**e.to_dict(), "member_name": e.member.full_name if e.member else None}
                for e in rows
            ]
        }
    )


@api_bp.post("/admin/entries/<int:entry_id>/approve")
@require_admin
def admin_approve_entry(entry_id: int):
    entry = db.session.get(ReadingEntry, entry_id)
    if entry is None:
        raise NotFound("Запись не найдена")
    entry.is_flagged = False
    entry.flag_reason = None
    entry.moderated_by = current_member().id
    entry.moderated_at = utcnow()
    db.session.commit()
    return jsonify({"ok": True})


# --- челленджи -------------------------------------------------------------------

@api_bp.get("/admin/challenges")
@require_admin
def admin_challenges():
    rows = (
        db.session.execute(sa.select(Challenge).order_by(Challenge.week_start.desc()))
        .scalars()
        .all()
    )
    return jsonify(
        {
            "challenges": [ch.with_results(db.session, c) for c in rows],
            "pending": ch.pending_moderation(db.session),
            "current_week": current_week_start().isoformat(),
        }
    )


@api_bp.post("/admin/challenges")
@require_admin
def admin_create_challenge():
    """Челленджи заводятся очередью на недели вперёд."""
    data = body()
    kind = str(data.get("type", ""))
    if kind not in ch.TYPE_LABELS:
        raise DomainError(
            "Тип челленджа: pages_total, finish_book, days_streak или genre", code="bad_type"
        )
    title = str(data.get("title", "")).strip()
    if not title:
        raise DomainError("У челленджа должно быть название", code="title_required")

    raw_week = as_date(data.get("week_start"), "неделя") or current_week_start()
    week = week_start(raw_week)  # выравниваем на понедельник, что бы ни ввёл админ

    if ch.challenge_for_week(db.session, week) is not None:
        raise DomainError(
            f"На неделю с {week.strftime('%d.%m.%Y')} челлендж уже назначен", code="week_taken"
        )

    challenge = Challenge(
        week_start=week,
        title=title,
        description=str(data.get("description", "")).strip(),
        kind=kind,
        target_value=as_int(data.get("target_value"), "цель", required=False),
        genre=(str(data.get("genre", "")).strip() or None),
        is_published=True,
    )
    db.session.add(challenge)
    db.session.commit()
    return jsonify({"challenge": challenge.to_dict()}), 201


@api_bp.patch("/admin/challenges/<int:challenge_id>")
@require_admin
def admin_patch_challenge(challenge_id: int):
    challenge = db.session.get(Challenge, challenge_id)
    if challenge is None:
        raise NotFound("Челлендж не найден")
    data = body()
    if "title" in data:
        challenge.title = str(data["title"]).strip()
    if "description" in data:
        challenge.description = str(data["description"]).strip()
    if "target_value" in data:
        challenge.target_value = as_int(data["target_value"], "цель", required=False)
    if "genre" in data:
        challenge.genre = str(data["genre"]).strip() or None
    if "is_published" in data:
        challenge.is_published = str(data["is_published"]).lower() in {"1", "true", "yes", "on"}
    db.session.commit()
    ch.recompute(db.session, challenge)
    db.session.commit()
    return jsonify({"challenge": challenge.to_dict()})


@api_bp.delete("/admin/challenges/<int:challenge_id>")
@require_admin
def admin_delete_challenge(challenge_id: int):
    challenge = db.session.get(Challenge, challenge_id)
    if challenge is None:
        raise NotFound("Челлендж не найден")
    db.session.delete(challenge)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.post("/admin/challenge-results/<int:result_id>/confirm")
@require_admin
def admin_confirm_result(result_id: int):
    approve = str(body().get("approve", "1")).lower() in {"1", "true", "yes", "on"}
    row = ch.moderate(db.session, result_id, current_member(), approve)
    db.session.commit()
    return jsonify({"result": row.to_dict()})


@api_bp.post("/admin/recompute")
@require_admin
def admin_recompute():
    """Ручной пересчёт числовых челленджей — на случай правки задним числом."""
    week = as_date(request.args.get("week"), "week")
    challenge = (
        ch.challenge_for_week(db.session, week_start(week)) if week else ch.current_challenge(db.session)
    )
    done = ch.recompute(db.session, challenge)
    db.session.commit()
    return jsonify({"newly_completed": done})


# --- экспорт ---------------------------------------------------------------------

def _csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM — чтобы Excel открыл кириллицу без плясок с кодировками
    return "﻿".encode("utf-8") + buffer.getvalue().encode("utf-8")


@api_bp.get("/admin/export.zip")
@require_admin
def admin_export():
    """Все данные клуба: архив из CSV-файлов по одной таблице на файл."""
    members = db.session.execute(sa.select(Member).order_by(Member.id)).scalars().all()
    books = db.session.execute(sa.select(Book).order_by(Book.id)).scalars().all()
    entries = db.session.execute(sa.select(ReadingEntry).order_by(ReadingEntry.id)).scalars().all()
    quotes = db.session.execute(sa.select(Quote).order_by(Quote.id)).scalars().all()
    challenges = db.session.execute(sa.select(Challenge).order_by(Challenge.id)).scalars().all()
    results = db.session.execute(sa.select(ChallengeResult).order_by(ChallengeResult.id)).scalars().all()
    club_events = db.session.execute(sa.select(ClubEvent).order_by(ClubEvent.id)).scalars().all()

    names = {m.id: m.full_name for m in members}

    files = {
        "members.csv": _csv_bytes(
            ["id", "ФИО", "роль", "активен", "PIN задан", "вступил"],
            [[m.id, m.full_name, m.role, int(m.is_active), int(m.pin_is_set),
              m.joined_at.isoformat()] for m in members],
        ),
        "books.csv": _csv_bytes(
            ["id", "участник", "автор", "название", "объём", "формат", "статус", "начата", "дочитана"],
            [[b.id, names.get(b.member_id, ""), b.author, b.title, b.total_pages or "", b.fmt,
              b.status, b.started_at or "", b.finished_at or ""] for b in books],
        ),
        "reading_entries.csv": _csv_bytes(
            ["id", "участник", "книга", "страниц", "ввод", "значение", "дата чтения",
             "комментарий", "помечена", "удалена", "создана"],
            [[e.id, names.get(e.member_id, ""), e.book.label if e.book else "", e.pages,
              e.input_kind, e.input_value, e.entry_date.isoformat(), e.note or "",
              int(e.is_flagged), e.deleted_at.isoformat() if e.deleted_at else "",
              e.created_at.isoformat()] for e in entries],
        ),
        "quotes.csv": _csv_bytes(
            ["id", "участник", "книга", "страница", "цитата", "создана"],
            [[q.id, names.get(q.member_id, ""), q.book_label, q.page or "", q.text,
              q.created_at.isoformat()] for q in quotes],
        ),
        "challenges.csv": _csv_bytes(
            ["id", "неделя", "название", "тип", "цель", "жанр", "описание"],
            [[c.id, c.week_start.isoformat(), c.title, c.kind, c.target_value or "",
              c.genre or "", c.description] for c in challenges],
        ),
        "challenge_results.csv": _csv_bytes(
            ["id", "челлендж", "участник", "статус", "прогресс"],
            [[r.id, r.challenge_id, names.get(r.member_id, ""), r.status, r.progress_value]
             for r in results],
        ),
        "club_events.csv": _csv_bytes(
            ["id", "тип", "участник", "данные", "когда"],
            [[e.id, e.kind, names.get(e.member_id or 0, ""), str(e.payload),
              e.created_at.isoformat()] for e in club_events],
        ),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    buffer.seek(0)

    stamp = date.today().isoformat()
    return Response(
        buffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="chitkod-export-{stamp}.zip"'},
    )
