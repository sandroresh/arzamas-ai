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
        payload.update(filters)
        
        url = f"{base_url}/{branch_id}/{entity}/index"
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 429:
            time.sleep(2)
            continue
        if response.status_code != 200:
            break
            
        data = response.json()
        items = data.get("items", [])
        
        if not items:
            break
            
        all_items.extend(items)
        page += 1
        time.sleep(0.2) 
        
    return all_items

def collect_crm_data():
    try:
        hostname = st.secrets["ALFACRM_HOSTNAME"]
        email = st.secrets["ALFACRM_EMAIL"]
        api_key_crm = st.secrets["ALFACRM_API_KEY"]
        base_url = f"https://{hostname}.s20.online/v2api"
        
        # Авторизация
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
        
        now = datetime.datetime.now()
        first_day = now.strftime("01.%m.%Y")
        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")

        # Железобетонный фильтр новеньких
        new_customers = []
        for c in customers:
            date_add = str(c.get("date_add", "")) 
            if f"{current_year}-{current_month}" in date_add or f".{current_month}.{current_year}" in date_add:
                new_customers.append(c)
                
        st.toast("Выкачиваем Платежи за этот месяц...", icon="⏳")
        payments = fetch_all_pages(base_url, token, "pay", document_date_from=first_day)

        # Обработка данных
        total_debt = sum(abs(float(c.get("balance") or 0)) for c in customers if float(c.get("balance") or 0) < 0)
        debtors_count = sum(1 for c in customers if float(c.get("balance") or 0) < 0)
        total_income = sum(float(p.get("income") or 0) for p in payments)
        
        lead_names = ", ".join([l.get("name") for l in leads[-20:]])
        teacher_names = ", ".join([t.get("name") for t in teachers])
        new_customer_names = ", ".join([c.get("name") for c in new_customers]) if new_customers else "В этом месяце новых договоров пока нет."

        return f"""
        --- 🏫 ALPHA CRM ПОЛНЫЙ СЛЕПОК ({now.strftime("%d.%m.%Y %H:%M")}) ---
        
        📊 ВОРОНКА И КЛИЕНТЫ:
        - Активных учеников всего: {len(customers)}
        - Должников: {debtors_count} (Сумма долга: -{total_debt} ₽)
        - Потенциальных клиентов (Лидов): {len(leads)}. Последние: {lead_names}
        
        📈 НОВЫЕ ДОГОВОРА (за {current_month}.{current_year}):
        - Новых резидентов за месяц: {len(new_customers)}
        - Кто именно пришел: {new_customer_names}
        
        👩‍🏫 КОМАНДА:
        - Преподаватели ({len(teachers)} чел.): {teacher_names}
        
        💰 ФИНАНСЫ (с начала месяца):
        - Зафиксировано платежей на сумму: {total_income} ₽
        """
    except Exception as e:
        return f"❌ Системная ошибка: {e}"

# --- ИНТЕРФЕЙС И УМНАЯ ПАМЯТЬ ---
if "messages" not in st.session_state:
    st.session_state.messages = []
    
if "business_snapshot" not in st.session_state:
    st.session_state.business_snapshot = None 

with st.sidebar:
    st.markdown("### Управление")
    if st.button("🔄 Обновить данные бизнеса", use_container_width=True):
        with st.spinner("Собираю свежие данные (CRM, Банк, Налоги)..."):
            st.session_state.business_snapshot = collect_crm_data()
        st.success(f"Данные обновлены: {datetime.datetime.now().strftime('%H:%M')}")
        
    st.markdown("---")
    if st.button("Новый чат ➕", use_container_width=True):
        st.session_state.messages = []
        st.success("История диалога очищена.")

# Первичная фоновая загрузка
if st.session_state.business_snapshot is None:
    with st.spinner("Первичная загрузка данных бизнеса..."):
        st.session_state.business_snapshot = collect_crm_data()

# Отрисовка чата
for message in st.session_state.messages:
    if message.get("role") != "system_context":
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# Обработка вопроса
if prompt := st.chat_input("Спросите о бизнесе (например: кто пришел в этом месяце?)..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    system_instruction = "Ты - операционный директор частной школы Arzamas. Отвечай кратко и по делу на основе предоставленных данных."
    rich_context = f"{system_instruction}\n\n### АКТУАЛЬНЫЕ ДАННЫЕ БИЗНЕСА ###\n{st.session_state.business_snapshot}"
    combined_prompt = f"{rich_context}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{prompt}"
    
    try:
        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(combined_prompt)
        
        with st.chat_message("assistant"):
            st.markdown(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})
    except Exception as e:
        st.error(f"Ошибка ИИ: {e}")
