"""Streamlit-интерфейс VetAssistant (T-025).

Запуск::

    streamlit run app/ui.py

Требует запущенный FastAPI-сервер (по умолчанию ``http://127.0.0.1:8000``).
"""

from __future__ import annotations

from typing import Any

import requests
import streamlit as st

from app.settings import UISettings, get_ui_settings
from app.tools import AVAILABLE_TOOLS, ToolCall
from app.ui_client import (
    fetch_appointments,
    fetch_reminders,
    login,
    register,
    stream_chat_events,
)

ERROR_API_DOWN = "Сервер ветеринара спит, включите uvicorn"


def _short_date(value: str) -> str:
    """Показать ISO-дату как ДД.ММ, иначе вернуть как есть."""
    parts = value.split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}"
    return value


def _init_session() -> None:
    """Создать историю чата и поля авторизации в session_state."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "token" not in st.session_state:
        st.session_state.token = None
    if "auth_email" not in st.session_state:
        st.session_state.auth_email = ""


def _auth_token() -> str | None:
    """Вернуть JWT текущей Streamlit-сессии."""
    token = st.session_state.get("token")
    return token if isinstance(token, str) and token else None


def _complete_auth(data: dict[str, Any], fallback_email: str) -> None:
    """Сохранить токен и перерисовать страницу."""
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        st.error("Сервер не вернул токен авторизации.")
        return

    user = data.get("user")
    email = user.get("email") if isinstance(user, dict) else None
    st.session_state.token = token
    st.session_state.auth_email = (
        email if isinstance(email, str) else fallback_email
    )
    st.rerun()


def _login_form(settings: UISettings) -> None:
    """Показать формы входа и регистрации."""
    st.info(
        "Войдите или создайте аккаунт — записи, напоминания и история "
        "будут доступны только вам."
    )
    login_tab, register_tab = st.tabs(["Вход", "Регистрация"])

    with login_tab, st.form("login_form"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input(
            "Пароль",
            type="password",
            key="login_password",
        )
        submitted = st.form_submit_button("Войти", use_container_width=True)
        if submitted:
            try:
                data = login(
                    settings.api_url,
                    email=email.strip(),
                    password=password,
                    timeout=settings.timeout_s,
                )
            except (requests.RequestException, ValueError) as exc:
                st.error(f"Не удалось войти: {exc}")
            else:
                _complete_auth(data, email.strip())

    with register_tab, st.form("register_form"):
        new_email = st.text_input("Email", key="register_email")
        new_password = st.text_input(
            "Пароль (минимум 8 символов)",
            type="password",
            key="register_password",
        )
        registered = st.form_submit_button(
            "Создать аккаунт",
            use_container_width=True,
        )
        if registered:
            if len(new_password) < 8:
                st.error("Пароль должен содержать минимум 8 символов.")
            else:
                try:
                    data = register(
                        settings.api_url,
                        email=new_email.strip(),
                        password=new_password,
                        timeout=settings.timeout_s,
                    )
                except (requests.RequestException, ValueError) as exc:
                    st.error(f"Не удалось зарегистрироваться: {exc}")
                else:
                    _complete_auth(data, new_email.strip())


def main() -> None:
    """Отрисовать страницу и обработать ввод пользователя."""
    st.set_page_config(page_title="VetAssistant", page_icon="🐾", layout="centered")
    _init_session()
    settings = get_ui_settings()

    st.title("🐾 VetAssistant - AI Ветеринар")
    st.caption("Локальный ветеринарный ассистент. Не заменяет очный осмотр врача.")

    token = _auth_token()
    if token is None:
        _login_form(settings)
        return

    with st.sidebar:
        st.header("Аккаунт")
        st.caption(f"👤 {st.session_state.auth_email}")
        if st.button("Выйти", use_container_width=True):
            st.session_state.token = None
            st.session_state.auth_email = ""
            st.session_state.messages = []
            st.rerun()
        st.divider()
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
                    token=token,
                )
                reminders = fetch_reminders(
                    settings.api_url,
                    timeout=settings.timeout_s,
                    token=token,
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
                token=token,
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
