"""Streamlit-интерфейс VetAssistant (T-025).

Запуск::

    streamlit run app/ui.py

Требует запущенный FastAPI-сервер (по умолчанию ``http://127.0.0.1:8000``).
"""

from __future__ import annotations

import requests
import streamlit as st

from app.ui_client import DEFAULT_API_URL, DEFAULT_MODEL_ID, stream_chat

ERROR_API_DOWN = "Сервер ветеринара спит, включите uvicorn"


def _init_session() -> None:
    """Создать историю чата в session_state (переживает перерисовки)."""
    if "messages" not in st.session_state:
        st.session_state.messages = []


def main() -> None:
    """Отрисовать страницу и обработать ввод пользователя."""
    st.set_page_config(page_title="VetAssistant", page_icon="🐾", layout="centered")
    _init_session()

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
        st.divider()
        st.caption(f"API: `{DEFAULT_API_URL}`")
        st.caption(f"Модель: `{DEFAULT_MODEL_ID}`")

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
        try:
            for token in stream_chat(
                st.session_state.messages,
                temperature=temperature,
            ):
                chunks.append(token)
                placeholder.markdown("".join(chunks) + "▌")
        except requests.RequestException:
            placeholder.error(ERROR_API_DOWN)
            return
        except Exception as exc:
            placeholder.error(f"Ошибка при обращении к серверу: {exc}")
            return

        answer = "".join(chunks).strip()
        if not answer:
            placeholder.warning("Модель вернула пустой ответ. Попробуйте ещё раз.")
            return

        placeholder.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})


main()
