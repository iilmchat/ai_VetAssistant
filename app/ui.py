"""Streamlit-интерфейс VetAssistant (T-025).

Запуск::

    streamlit run app/ui.py

Требует запущенный FastAPI-сервер (по умолчанию ``http://127.0.0.1:8000``).
"""

from __future__ import annotations

import requests
import streamlit as st

from app.settings import get_ui_settings
from app.tools import AVAILABLE_TOOLS, ToolCall
from app.ui_client import fetch_appointments, fetch_reminders, stream_chat_events

ERROR_API_DOWN = "Сервер ветеринара спит, включите uvicorn"


def _short_date(value: str) -> str:
    """Показать ISO-дату как ДД.ММ, иначе вернуть как есть."""
    parts = value.split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}"
    return value


def _init_session() -> None:
    """Создать историю чата в session_state (переживает перерисовки)."""
    if "messages" not in st.session_state:
        st.session_state.messages = []


def main() -> None:
    """Отрисовать страницу и обработать ввод пользователя."""
    st.set_page_config(page_title="VetAssistant", page_icon="🐾", layout="centered")
    _init_session()
    settings = get_ui_settings()

    st.title("🐾 VetAssistant - AI Ветеринар")
    st.caption("Локальный ветеринарный ассистент. Не заменяет очный осмотр врача.")

    with st.sidebar:
        st.header("Настройки")
        temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.05,
            help="Выше — разнообразнее ответы, ниже — стабильнее.",
        )
        if st.button("Очистить историю чата", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        use_rag = st.checkbox("Использовать базу знаний (RAG)", value=True)
        use_tools = st.checkbox(
            "Разрешить модели использовать инструменты (Function Calling)",
            value=False,
            help="Запись на приём и создание напоминаний через tool_calls.",
        )
        with st.expander("Мои записи", expanded=False):
            if st.button("Обновить", key="refresh_records", use_container_width=True):
                st.rerun()
            try:
                appointments = fetch_appointments(
                    settings.api_url,
                    timeout=settings.timeout_s,
                )
                reminders = fetch_reminders(
                    settings.api_url,
                    timeout=settings.timeout_s,
                )
            except (requests.RequestException, ValueError):
                st.caption("Не удалось загрузить записи: API недоступен.")
            else:
                if not appointments and not reminders:
                    st.caption("Пока нет записей и напоминаний.")
                for appointment in appointments:
                    pet_name = str(appointment.get("pet_name", "—"))
                    date = _short_date(str(appointment.get("date", "—")))
                    time = str(appointment.get("time", "—"))
                    with st.container(border=True):
                        st.markdown(f"🐾 **{pet_name}** — {date} в {time}")
                for reminder in reminders:
                    text = str(reminder.get("text", "—"))
                    time = str(reminder.get("time", "—"))
                    with st.container(border=True):
                        st.markdown(f"⏰ **{text}** — {time}")
        st.divider()
        st.caption(f"API: `{settings.api_url}`")
        st.caption(f"Модель: `{settings.model_id}`")

    for message in st.session_state.messages:
        with st.chat_message(str(message["role"])):
            st.markdown(str(message["content"]))

    prompt = st.chat_input("Опишите, что беспокоит питомца...")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        try:
            for event in stream_chat_events(
                st.session_state.messages,
                temperature=temperature,
                use_rag=use_rag,
                tools=AVAILABLE_TOOLS if use_tools else None,
                api_url=settings.api_url,
                model_id=settings.model_id,
                timeout=settings.timeout_s,
            ):
                if event.content is not None:
                    chunks.append(event.content)
                    placeholder.markdown("".join(chunks) + "▌")
                if event.tool_calls:
                    tool_calls.extend(event.tool_calls)
        except requests.RequestException:
            placeholder.error(ERROR_API_DOWN)
            return
        except Exception as exc:
            placeholder.error(f"Ошибка при обращении к серверу: {exc}")
            return

        answer = "".join(chunks).strip()
        if not answer and not tool_calls:
            placeholder.warning("Модель вернула пустой ответ. Попробуйте ещё раз.")
            return

        if answer:
            placeholder.markdown(answer)

        tool_summary: list[str] = []
        for tool_call in tool_calls:
            name = tool_call.function.name
            arguments = tool_call.function.arguments
            st.success(f"🛠️ Вызван инструмент: **{name}**\n\nПараметры: `{arguments}`")
            tool_summary.append(f"{name} ({arguments})")

        history_content = answer
        if not history_content and tool_summary:
            history_content = "🛠️ Вызван инструмент: " + "; ".join(tool_summary)
        st.session_state.messages.append({"role": "assistant", "content": history_content})


main()
