"""Команды обслуживания: flask init-db, flask seed, flask create-member и т. д."""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

import click
import sqlalchemy as sa
from flask import Flask

from . import auth
from .domain import challenges as ch
from .domain import events
from .domain.levels import ensure_levels
from .domain.time_utils import MSK, current_week_start, msk_today
from .extensions import db
from .models import Book, Challenge, ChallengeResult, ClubEvent, Member, Quote, ReadingEntry


def register(app: Flask) -> None:
    app.cli.add_command(init_db)
    app.cli.add_command(seed)
    app.cli.add_command(create_member)
    app.cli.add_command(recompute_cmd)
    app.cli.add_command(close_week_cmd)


@click.command("init-db")
def init_db():
    """Создать таблицы и уровни (для локального запуска без миграций)."""
    db.create_all()
    ensure_levels(db.session)
    db.session.commit()
    click.echo("База готова, уровни заполнены.")


@click.command("create-member")
@click.argument("full_name")
@click.option("--admin", is_flag=True, help="Сделать администратором клуба")
def create_member(full_name: str, admin: bool):
    """Завести участника и напечатать его персональную ссылку."""
    ensure_levels(db.session)
    raw, prefix, digest = auth.issue_token()
    member = Member(
        full_name=full_name,
        role="admin" if admin else "member",
        token_prefix=prefix,
        token_hash=digest,
        joined_at=msk_today(),
    )
    db.session.add(member)
    db.session.flush()
    events.record(db.session, "joined", member.id, {"full_name": full_name})
    db.session.commit()
    click.echo(f"{full_name}: {auth.member_link(raw)}")


@click.command("recompute")
def recompute_cmd():
    """Пересчитать числовой челлендж текущей недели."""
    done = ch.recompute(db.session)
    db.session.commit()
    click.echo(f"Засчитано впервые: {len(done)}")


@click.command("close-week")
def close_week_cmd():
    """Подвести итоги прошедшей недели."""
    winners = ch.close_out_previous_week(db.session)
    db.session.commit()
    click.echo(f"Победителей прошлой недели: {winners}")


# --- тестовые данные --------------------------------------------------------------

def _stamp(day: date, hour: int = 20, minute: int = 0) -> datetime:
    """Момент создания записи: вечер указанного дня по Москве, в UTC."""
    return datetime.combine(day, time(hour, minute), tzinfo=MSK).astimezone(timezone.utc)


def _chunks(total: int, size: int = 250) -> list[int]:
    out = []
    left = total
    while left > 0:
        piece = min(size, left)
        out.append(piece)
        left -= piece
    return out


@click.command("seed")
@click.option("--reset", is_flag=True, help="Стереть текущие данные перед наполнением")
def seed(reset: bool):
    """Наполнить базу демо-данными: 7 участников и записи за три недели.

    Набор подобран так, чтобы сразу проверялись сортировка, тай-брейк, уровни
    ровно на границах и все случаи недельной динамики.
    """
    db.create_all()

    if reset:
        for model in (ChallengeResult, Challenge, ClubEvent, Quote, ReadingEntry, Book, Member):
            db.session.execute(sa.delete(model))
        db.session.commit()
        click.echo("Прежние данные удалены.")

    ensure_levels(db.session)

    w0 = current_week_start()
    w1, w2 = w0 - timedelta(days=7), w0 - timedelta(days=14)
    today = msk_today()

    # (ФИО, страницы за w2, за w1, за w0, «раньше», книга, дочитанных книг)
    plan = [
        ("Пётр Смирнов", [250, 250, 200], [300, 250, 250], [420, 180, 200], 2700,
         ("Умберто Эко", "Имя розы", 620), 3),
        ("Илья Рогачёв", [300, 250], [280, 270], [300, 300], 300,
         ("Станислав Лем", "Солярис", 288), 2),
        ("Дмитрий Ветров", [100], [150], [], 850,
         ("Виктор Пелевин", "Чапаев и Пустота", 400), 1),
        # Анна и Софья набирают ровно по 1000 страниц — это и граница уровня,
        # и проверка тай-брейка: Анна вносит записи раньше по времени, значит выше
        ("Анна Ковалёва", [120, 90], [100, 100], [130, 130], 330,
         ("Донна Тартт", "Щегол", 830), 2),
        ("Софья Ильина", [110, 100], [90, 110], [140, 110], 340,
         ("Ольга Токарчук", "Бегуны", 416), 1),
        ("Мария Логинова", [80], [], [45, 60], 200,
         ("Фредрик Бакман", "Вторая жизнь Уве", 320), 0),
        ("Ольга Северцева", [60, 60], [], [], 0,
         ("Евгений Водолазкин", "Лавр", 440), 0),
    ]

    admin_link = None
    links: list[tuple[str, str]] = []

    raw, prefix, digest = auth.issue_token()
    admin = Member(full_name="Администратор клуба", role="admin", token_prefix=prefix,
                   token_hash=digest, joined_at=today - timedelta(days=40))
    db.session.add(admin)
    admin_link = auth.member_link(raw)

    rnd = random.Random(20260825)

    for order, (name, week2, week1, week0, older, book_info, finished_count) in enumerate(plan):
        raw, prefix, digest = auth.issue_token()
        member = Member(full_name=name, token_prefix=prefix, token_hash=digest,
                        joined_at=today - timedelta(days=35))
        db.session.add(member)
        db.session.flush()
        links.append((name, auth.member_link(raw)))

        author, title, volume = book_info
        book = Book(member_id=member.id, author=author, title=title, total_pages=volume,
                    fmt="ebook" if order % 3 == 2 else "paper", status="reading",
                    started_at=w2 - timedelta(days=3))
        db.session.add(book)

        for n in range(finished_count):
            done_day = today - timedelta(days=20 + n * 9)
            db.session.add(
                Book(member_id=member.id, author="", title=f"Прочитано ранее №{n + 1}",
                     status="finished", started_at=done_day - timedelta(days=14),
                     finished_at=done_day)
            )
        db.session.flush()

        # «Раньше» — недели с третьей по седьмую назад, заодно получается стрик
        for i, piece in enumerate(_chunks(older)):
            day = w2 - timedelta(days=7 * (1 + i % 5) + rnd.randint(0, 4))
            db.session.add(
                ReadingEntry(member_id=member.id, book_id=None, pages=piece, input_kind="pages",
                             input_value=piece, entry_date=day, created_at=_stamp(day),
                             updated_at=_stamp(day))
            )

        for week, pages_list in ((w2, week2), (w1, week1), (w0, week0)):
            for i, value in enumerate(pages_list):
                day = min(week + timedelta(days=i * 2), today)
                flagged = value > 300
                # Софья вносит вечером — при равенстве сумм она ниже Анны
                hour = 22 if name.startswith("Софья") else 20
                db.session.add(
                    ReadingEntry(
                        member_id=member.id, book_id=book.id, pages=value, input_kind="pages",
                        input_value=value, entry_date=day, created_at=_stamp(day, hour),
                        updated_at=_stamp(day, hour),
                        note="перечитывал вслух" if i == 0 and order == 0 else None,
                        is_flagged=flagged,
                        flag_reason="Больше 300 страниц за одну запись — нужна проверка администратора"
                        if flagged else None,
                    )
                )

        if order < 5:
            db.session.add(
                Quote(
                    member_id=member.id, book_id=book.id, book_label=f"{author} — {title}",
                    text=SEED_QUOTES[order], page=rnd.randint(24, 300),
                    created_at=_stamp(w1 + timedelta(days=order)),
                    updated_at=_stamp(w1 + timedelta(days=order)),
                )
            )

    db.session.flush()

    challenges = [
        Challenge(week_start=w2, title="Прочитать 400 страниц за неделю", kind="pages_total",
                  target_value=400,
                  description="Разгоняемся после перерыва. Считаем по журналу автоматически."),
        Challenge(week_start=w1, title="Читать пять дней подряд", kind="days_streak",
                  target_value=5,
                  description="Не количество, а привычка: пять дней с записями."),
        Challenge(week_start=w0, title="Прочитать 500 страниц за неделю", kind="pages_total",
                  target_value=500,
                  description="Главный забег недели. Засчитывается само."),
        Challenge(week_start=w0 + timedelta(days=7), title="Дочитать книгу", kind="finish_book",
                  target_value=1, description="Ту самую, что лежит с закладкой на середине."),
        Challenge(week_start=w0 + timedelta(days=14),
                  title="Прочитать что-нибудь из жанра «научпоп»", kind="genre",
                  genre="научпоп",
                  description="Мягкий челлендж: отмечаете сами, администратор подтверждает."),
    ]
    for challenge in challenges:
        db.session.add(challenge)
    db.session.flush()

    for challenge in challenges:
        if challenge.is_auto and challenge.week_start <= w0:
            ch.recompute(db.session, challenge)

    db.session.commit()

    click.echo("\nГотово. Персональные ссылки участников:\n")
    click.echo(f"  Администратор клуба → {admin_link}")
    for name, link in links:
        click.echo(f"  {name} → {link}")
    click.echo(
        "\nPIN каждый задаёт сам при первом переходе по ссылке."
        "\nСсылки больше нигде не показываются — сохраните их сейчас.\n"
    )


SEED_QUOTES = [
    "Книги пишутся не для того, чтобы в них верили, а для того, чтобы их обдумывали.",
    "Мы отправляемся в космос, готовые ко всему, то есть к одиночеству и борьбе.",
    "Всякая вещь есть форма проявления беспредельного разнообразия.",
    "Красота ужасна. Она и есть то, чего мы боимся больше всего.",
    "Описывая, мы делаем вещи своими — как будто присваиваем их.",
]
