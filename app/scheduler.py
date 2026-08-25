"""Фоновые задачи.

Важно: смена челленджа в понедельник 00:00 МСК от планировщика НЕ зависит —
текущий челлендж выбирается запросом по week_start. Здесь только пересчёт
числовых результатов и подведение итогов прошедшей недели.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from . import create_app
from .domain import challenges as ch
from .domain.time_utils import MSK
from .extensions import db

log = logging.getLogger("chitkod.scheduler")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app()
    scheduler = BlockingScheduler(timezone=MSK)

    @scheduler.scheduled_job("cron", minute=5, id="recompute")
    def recompute_current():
        with app.app_context():
            done = ch.recompute(db.session)
            db.session.commit()
            if done:
                log.info("Челлендж недели засчитан участникам: %s", done)

    @scheduler.scheduled_job("cron", day_of_week="mon", hour=0, minute=10, id="close-week")
    def close_previous_week():
        with app.app_context():
            winners = ch.close_out_previous_week(db.session)
            db.session.commit()
            log.info("Итоги прошедшей недели подведены, победителей: %s", winners)

    log.info("Планировщик запущен, часовой пояс Europe/Moscow")
    scheduler.start()


if __name__ == "__main__":
    main()
