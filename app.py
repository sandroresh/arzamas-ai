import streamlit as st
import google.generativeai as genai
import datetime
import requests
import time

# --- НАСТРОЙКА СТРАНИЦЫ ---
st.set_page_config(page_title="Alpha Fem Panel", page_icon="👩‍💼")
st.title("Управление школой 'Arzamas'")

# --- ПОДКЛЮЧЕНИЕ ИИ ---
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash') 
except Exception as e:
    st.error("Ошибка API Ключа Google. Проверьте 'Secrets'.")
    st.stop()

# --- УНИВЕРСАЛЬНЫЙ ПЫЛЕСОС ALPHA CRM ---
def fetch_all_pages(base_url, token, entity, branch_id=1, **filters):
    """Умная функция, которая листает страницы и выкачивает сущность целиком"""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-ALFACRM-TOKEN": token
    }
    
    all_items = []
    page = 0
    page_size = 100
    
    while True:
        payload = {"page": page, "pageSize": page_size}
        payload.update(filters) # Добавляем любые фильтры (например, дату)
        
        url = f"{base_url}/{branch_id}/{entity}/index"
        response = requests.post(url, headers=headers, json=payload)
        
        # Защита от блокировки (если слишком часто спрашиваем)
        if response.status_code == 429:
            time.sleep(2)
            continue
            
        if response.status_code != 200:
            break
            
        data = response.json()
        items = data.get("items", [])
        
        if not items: # Если пришел пустой список — значит дошли до конца
            break
            
        all_items.extend(items)
        page += 1
        
        # Небольшая пауза, чтобы не злить сервер Alpha CRM
        time.sleep(0.2) 
        
    return all_items

def collect_crm_data():
    try:
        hostname = st.secrets["ALFACRM_HOSTNAME"]
        email = st.secrets["ALFACRM_EMAIL"]
        api_key_crm = st.secrets["ALFACRM_API_KEY"]
        base_url = f"https://{hostname}.s20.online/v2api"
        
        # 1. Авторизация
        auth_payload = {"email": email, "api_key": api_key_crm}
        auth_req = requests.post(f"{base_url}/auth/login", json=auth_payload)
        token = auth_req.json().get("token")
        
        if not token:
            return "❌ Ошибка авторизации в CRM."

        st.toast("Выкачиваем Лиды...", icon="⏳")
        leads = fetch_all_pages(base_url, token, "lead", is_study=0)
        
        st.toast("Выкачиваем Учеников...", icon="⏳")
        customers = fetch_all_pages(base_url, token, "customer", is_study=1)
        
        st.toast("Выкачиваем Преподавателей...", icon="⏳")
        teachers = fetch_all_pages(base_url, token, "teacher")
        
        st.toast("Выкачиваем Платежи за этот месяц...", icon="⏳")
        now = datetime.datetime.now()
        first_day = now.strftime("01.%m.%Y")
        payments = fetch_all_pages(base_url, token, "pay", document_date_from=first_day)

        # 2. Обработка данных для ИИ
        # Считаем долги
        total_debt = sum(abs(float(c.get("balance") or 0)) for c in customers if float(c.get("balance") or 0) < 0)
        debtors_count = sum(1 for c in customers if float(c.get("balance") or 0) < 0)
        
        # Считаем доходы за месяц
        total_income = sum(float(p.get("income") or 0) for p in payments)
        
        # Формируем списки
        lead_names = ", ".join([l.get("name") for l in leads[-20:]]) # Берем 20 последних лидов, чтобы не перегружать текст
        teacher_names = ", ".join([t.get("name") for t in teachers])

        # 3. Собираем Мега-Слепок
        return f"""
        --- 🏫 ALPHA CRM ПОЛНЫЙ СЛЕПОК ({now.strftime("%d.%m.%Y %H:%M")}) ---
        
        📊 ВОРОНКА И КЛИЕНТЫ:
        - Активных учеников: {len(customers)}
        - Должников: {debtors_count} (Сумма долга: -{total_debt} ₽)
        - Потенциальных клиентов (Лидов) в базе: {len(leads)}. Последние: {lead_names}
        
        👩‍🏫 КОМАНДА:
        - Преподаватели ({len(teachers)} чел.): {teacher_names}
        
        💰 ФИНАНСЫ (с начала месяца):
        - Зафиксировано платежей на сумму: {total_income} ₽
        """
    except Exception as e:
        return f"❌ Системная ошибка: {e}"

def generate_rich_context():
    crm = collect_crm_data()
    system_instruction = """
    Ты - операционный директор частной школы Arzamas. Отвечай на вопрос пользователя 
    на основе актуальных данных бизнеса ниже.
    """
    return f"{system_instruction}\n\n### ДАННЫЕ БИЗНЕСА ###\n{crm}"

# --- ИНТЕРФЕЙС ЧАТА ---
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    if st.button("Новый чат ➕"):
        st.session_state.messages = []
        st.success("История очищена.")

for message in st.session_state.messages:
    if message.get("role") != "system_context":
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

if prompt := st.chat_input("Спросите о бизнесе (например: какая выручка за месяц?)..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Пылесос собирает данные со всех разделов CRM..."):
        rich_context = generate_rich_context()
        st.session_state.messages.append({"role": "system_context", "content": rich_context})
        
        combined_prompt = f"{rich_context}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{prompt}"
        
        try:
            chat_session = model.start_chat(history=[])
            response = chat_session.send_message(combined_prompt)
            
            with st.chat_message("assistant"):
                st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"Ошибка ИИ: {e}")
