import streamlit as st
import google.generativeai as genai
import requests # Понадобится вам для реальных API-запросов

# Настройка страницы
st.set_page_config(page_title="Ассистент Директора", page_icon="🏫")

# --- 1. ФУНКЦИИ ДЛЯ СБОРА ДАННЫХ (ЗАГЛУШКИ) ---
# Замените логику в этих функциях на реальные запросы к API согласно документации сервисов.

def get_alpha_crm_data():
    # Пример реального запроса:
    # response = requests.post("https://your-school.s20.online/v2api/auth/login", ...)
    # data = requests.get("https://your-school.s20.online/v2api/customer/index", headers=...)
    return """
    - Должники: Иванов И. (5000 руб), Петров А. (3200 руб). Общая сумма долга: 8200 руб.
    - Начисления тьюторов (к выплате): Смирнова Е. (15000 руб), Волков Д. (12500 руб). Общая сумма выплат: 27500 руб.
    """

def get_tochka_bank_data():
    # Пример реального запроса:
    # response = requests.get("https://enter.tochka.com/uapi/open-banking/v1.0/accounts/...", headers=...)
    return """
    - Текущий остаток на счете: 345 000 руб.
    - Последние приходы за 3 дня: 45 000 руб (Оплата обучения), 12 000 руб (Эквайринг).
    """

def get_elba_data():
    # Пример реального запроса:
    # response = requests.get("https://openapi.elba.kontur.ru/v1/taxes/...", headers=...)
    return """
    - Ближайшие налоги: УСН за 1 квартал (до 25 апреля) - 42 000 руб, Страховые взносы - 11 500 руб.
    """

def build_business_context():
    """Объединяет все данные в единый слепок бизнеса."""
    alpha_data = get_alpha_crm_data()
    tochka_data = get_tochka_bank_data()
    elba_data = get_elba_data()

    context = f"""
    СЛЕПОК БИЗНЕСА НА ТЕКУЩИЙ МОМЕНТ:

    1. Данные CRM (Alpha CRM):
    {alpha_data}

    2. Финансы (Точка Банк):
    {tochka_data}

    3. Налоги и бухгалтерия (Контур.Эльба):
    {elba_data}
    """
    return context

# --- 2. НАСТРОЙКА GEMINI API ---
# Безопасное получение ключа из секретов Streamlit
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.warning("⚠️ Пожалуйста, добавьте GEMINI_API_KEY в файл .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=api_key)
# Используем модель Gemini 1.5 Flash (быстрая и отлично подходит для текстовых задач)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 3. ИНТЕРФЕЙС STREAMLIT ---
st.title("🏫 ИИ-Ассистент владельца школы")
st.markdown("Задайте вопрос на основе текущих финансовых показателей и данных CRM.")

# Получаем свежий слепок бизнеса
business_context = build_business_context()

# Показываем слепок в боковой панели (удобно для контроля)
with st.sidebar:
    st.header("📊 Текущий слепок бизнеса")
    st.info(business_context)
    st.caption("Эти данные автоматически добавляются к вашему запросу как контекст.")

# Инициализация истории чата в сессии Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = []

# Отображение истории чата
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Обработка нового ввода от пользователя
if prompt := st.chat_input("Например: Хватит ли мне сейчас денег на выплату тьюторам и налоги?"):
    
    # Сохраняем и отображаем вопрос пользователя
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Системный промпт: Инструктируем модель использовать контекст
    full_prompt = f"""
    Ты бизнес-ассистент владельца образовательной школы.
    Опирайся СТРОГО на следующие данные о бизнесе при ответе на вопрос:
    
    {business_context}

    Вопрос владельца: {prompt}
    
    Отвечай четко, по делу, при необходимости делай математические расчеты.
    """

    # Отправляем запрос в Gemini и выводим ответ
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        try:
            with st.spinner('Анализирую данные...'):
                response = model.generate_content(full_prompt)
            
            full_response = response.text
            message_placeholder.markdown(full_response)
            
            # Сохраняем ответ ИИ в историю
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"Произошла ошибка при обращении к API Gemini: {e}")
