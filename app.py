import streamlit as st
import google.generativeai as genai
import datetime
import requests

# --- НАСТРОЙКА СТРАНИЦЫ И ИНТЕРФЕЙСА ---
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

# --- ФУНКЦИИ СБОРА ДАННЫХ ---
def collect_crm_data():
    try:
        hostname = st.secrets["ALFACRM_HOSTNAME"]
        email = st.secrets["ALFACRM_EMAIL"]
        api_key_crm = st.secrets["ALFACRM_API_KEY"]
        
        # ИСПРАВЛЕНИЕ 1: Убрали дефис из v2api
        base_url = f"https://{hostname}.s20.online/v2api"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Шаг 1: Авторизация
        auth_payload = {"email": email, "api_key": api_key_crm}
        auth_req = requests.post(f"{base_url}/auth/login", json=auth_payload, headers=headers)
        
        if auth_req.status_code != 200:
            return f"❌ Ошибка входа (Код {auth_req.status_code}). Ответ сервера: {auth_req.text[:200]}"
            
        auth_res = auth_req.json()
        token = auth_res.get("token")
        
        if not token:
            return f"❌ Авторизация не удалась. CRM ответила: {auth_res}"
            
        # Шаг 2: Запрос данных
        headers["X-ALFACRM-TOKEN"] = token
        payload_debtors = {"is_study": 1, "balance_to": -1} 
        
        # ИСПРАВЛЕНИЕ 2: Добавили /1/ (ID филиала) перед customer
        customers_req = requests.post(f"{base_url}/1/customer/index", headers=headers, json=payload_debtors)
        
        if customers_req.status_code != 200:
            return f"❌ Ошибка загрузки базы (Код {customers_req.status_code}). Ответ: {customers_req.text[:200]}"
            
        customers_res = customers_req.json()
        items = customers_res.get("items", [])
        
        total_debtors = len(items)
        total_debt_amount = sum(abs(item.get("balance", 0)) for item in items)
        
        debtors_list = ", ".join([f"{c.get('name')} ({c.get('balance')} ₽)" for c in items])
        if not debtors_list:
            debtors_list = "Должников нет! Все молодцы."
            
        return f"""
        --- 🏫 ALPHA CRM СЛЕПОК ({datetime.datetime.now().strftime("%d.%m.%Y %H:%M")}) ---
        Активных должников: {total_debtors}.
        Общая сумма долга: -{total_debt_amount} ₽.
        Детализация: {debtors_list}.
        """
    except Exception as e:
        return f"❌ Системная ошибка: {e}"
def collect_finance_data():
    # Пока оставляем заглушку для финансов
    return f"--- 🏦 ФИНАНСЫ ---\nДанные банка пока не подключены."

def generate_rich_context():
    crm = collect_crm_data()
    fin = collect_finance_data()
    system_instruction = """
    Ты - операционный директор частной школы Arzamas. Отвечай на вопрос пользователя 
    на основе актуальных данных бизнеса ниже. Будь краток и предлагай решения.
    """
    return f"{system_instruction}\n\n### ДАННЫЕ БИЗНЕСА ###\n{crm}\n{fin}"

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

if prompt := st.chat_input("Спросите о бизнесе..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Собираю данные из CRM..."):
        rich_context = generate_rich_context()
        st.session_state.messages.append({"role": "system_context", "content": rich_context})
        
        combined_prompt = f"### АКТУАЛЬНЫЙ КОНТЕКСТ ###\n{rich_context}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{prompt}"
        
        try:
            chat_session = model.start_chat(history=[])
            response = chat_session.send_message(combined_prompt)
            
            with st.chat_message("assistant"):
                st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"Ошибка ИИ: {e}")
