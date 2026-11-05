"""Общий limiter slowapi для API (T-134).

Вынесен из ``app.main`` в отдельный модуль, чтобы роутеры (например,
``app.telegram_link``) использовали тот же экземпляр и то же хранилище
счётчиков, не создавая циклический импорт с ``app.main``.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

#: Единый лимитер: лимиты задаются декораторами в эндпоинтах.
limiter: Limiter = Limiter(key_func=get_remote_address)
