import streamlit as st
import google.generativeai as genai
import datetime
import aiohttp
import asyncio

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

# --- АСИНХРОННЫЙ КЛИЕНТ (Аналог вашего async_client_alfacrm.py) ---
async def fetch_page(session, url, token, payload, semaphore):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-ALFACRM-TOKEN": token
    }
    async with semaphore:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 429:
                await asyncio.sleep(2) # Защита от спама
                return await fetch_page(session, url, token, payload, semaphore)
            if response.status == 200:
                return await response.json()
            return None

async def fetch_all_pages_async(base_url, token, entity, branch_id=1, **filters):
    url = f"{base_url}/{branch_id}/{entity}/index"
    all_items = []
    
    # Ограничиваем до 3 одновременных запросов, как в вашем коде
    semaphore = asyncio.Semaphore(3) 
    
    async with aiohttp.ClientSession() as session:
        # 1. Запрашиваем первую страницу, чтобы узнать общее количество (total)
        payload = {"page": 0, "pageSize": 100}
        payload.update(filters)
        first_page = await fetch_page(session, url, token, payload, semaphore)
        
        if not first_page or not first_page.get("items"):
            return []
            
        all_items.extend(first_page["items"])
        total_count = int(first_page.get("total", 0))
        
        if total_count <= 100:
            return all_items
            
        # 2. Если записей больше 100, генерируем асинхронные задачи для остальных страниц
        total_pages = (total_count + 99) // 100
        tasks = []
        for page in range(1, total_pages):
            page_payload = {"page": page, "pageSize": 100}
            page_payload.update(filters)
            tasks.append(fetch_page(session, url, token, page_payload, semaphore))
            
        # 3. Запускаем все запросы параллельно!
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res and res.get("items"):
                all_items.extend(res["items"])
                
    return all_items

# --- КЭШИРОВАНИЕ (Аналог вашего database_manager.py) ---
# Эта функция скачает данные один раз и "заморозит" их в памяти Streamlit
@st.cache_data(ttl=3600, show_spinner=False) # Кэш живет 1 час
def get_cached_crm_data(hostname, email, api_key_crm):
    base_url = f"https://{hostname}.s20.online/v2api"
    
    # Синхронная авторизация для получения токена
    import requests
    auth_payload = {"email": email, "api_key": api_key_crm}
    auth_req = requests.post(f"{base_url}/auth/login", json=auth_payload)
    token = auth_req.json().get("token")
    if not token:
        raise Exception("Ошибка авторизации в CRM")

    # Функция-обертка для запуска асинхронного кода
    async def run_sync():
        now = datetime.datetime.now()
        first_day = now.strftime("01.%m.%Y")
        
        # Запускаем выкачивание ВСЕХ сущностей параллельно (молниеносно)
        task_leads = fetch_all_pages_async(base_url, token, "lead", is_study=0)
        task_customers = fetch_all_pages_async(base_url, token, "customer", is_study=1)
        task_teachers = fetch_all_pages_async(base_url, token, "teacher")
        task_lessons = fetch_all_pages_async(base_url, token, "lesson", date_from=first_day)
        task_pays = fetch_all_pages_async(base_url, token, "pay", document_date_from=first_day)
        
        return await asyncio.gather(task_leads, task_customers, task_teachers, task_lessons, task_pays)

    # Выполняем асинхронный цикл
    leads, customers, teachers, lessons, pays = asyncio.run(run_sync())
    
    return {
        "leads": leads,
        "customers": customers,
        "teachers": teachers,
        "lessons": lessons,
        "pays": pays,
        "timestamp": datetime.datetime.now()
    }

# --- ПРОЦЕССОР (Аналог вашего processor.py) ---
def process_data_for_ai(raw_data):
    customers = raw_data["customers"]
    leads = raw_data["leads"]
    teachers = raw_data["teachers"]
    lessons = raw_data["lessons"]
    pays = raw_data["pays"]
    
    now = raw_data["timestamp"]
    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")

    # Считаем новеньких
    new_customers = [c for c in customers if f"{current_year}-{current_month}" in str(c.get("date_add", "")) or f".{current_month}.{current_year}" in str(c.get("date_add", ""))]
    
    # Финансы
    total_debt = sum(abs(float(c.get("balance") or 0)) for c in customers if float(c.get("balance") or 0) < 0)
    total_income = sum(float(p.get("income") or 0) for p in pays)
    
    # Посещаемость
    attendances, absences = 0, 0
    for lesson in lessons:
        if isinstance(lesson.get("details"), list):
            for student in lesson["details"]:
                status = student.get("is_attend")
                if status == 1: attendances += 1
                elif status in (0, 2): absences += 1
                
    # Формируем отчет
    lead_names = ", ".join([l.get("name") for l in leads[-10:]])
    teacher_names = ", ".join([t.get("name") for t in teachers])
    new_customer_names = ", ".join([c.get("name") for c in new_customers]) if new_customers else "Нет новых договоров."

    return f"""
    --- 🏫 ALPHA CRM СЛЕПОК ({now.strftime("%d.%m.%Y %H:%M")}) ---
    📊 ВОРОНКА И КЛИЕНТЫ:
    - Активных учеников: {len(customers)}
    - Должников: {sum(1 for c in customers if float(c.get("balance") or 0) < 0)} (Долг: -{total_debt} ₽)
    - Лидов в базе: {len(leads)}. Последние 10: {lead_names}
    📈 НОВЫЕ ДОГОВОРА (за этот месяц):
    - Пришло: {len(new_customers)}. Имена: {new_customer_names}
    📚 АКАДЕМИЧЕСКАЯ СВОДКА (за этот месяц):
    - Проведено занятий: {len(lessons)}
    - Посещений: {attendances} | Пропусков: {absences}
    👩‍🏫 КОМАНДА ({len(teachers)} чел.): {teacher_names}
    💰 ФИНАНСЫ (с начала месяца):
    - Зафиксировано платежей на сумму: {total_income} ₽
    """

# --- ИНТЕРФЕЙС ЧАТА ---
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.markdown("### Управление")
    if st.button("🔄 Скачать свежие данные (Сброс кэша)", use_container_width=True):
        get_cached_crm_data.clear() # Жестко чистим "базу данных"
        st.success("Кэш очищен. Данные будут скачаны заново при следующем вопросе.")
    st.markdown("---")
    if st.button("Новый чат ➕", use_container_width=True):
        st.session_state.messages = []

for message in st.session_state.messages:
    if message.get("role") != "system_context":
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

if prompt := st.chat_input("Спросите о бизнесе..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        # 1. Берем данные из кэша (или скачиваем асинхронно, если кэш пуст)
        with st.spinner("Проверяю базу данных..."):
            raw_data = get_cached_crm_data(
                st.secrets["ALFACRM_HOSTNAME"], 
                st.secrets["ALFACRM_EMAIL"], 
                st.secrets["ALFACRM_API_KEY"]
            )
        
        # 2. Процессор собирает текст для ИИ
        business_snapshot = process_data_for_ai(raw_data)
        
        # 3. Отправляем в нейросеть
        system_instruction = "Ты - операционный директор частной школы Arzamas. Отвечай кратко на основе данных."
        combined_prompt = f"{system_instruction}\n\n### ДАННЫЕ ###\n{business_snapshot}\n\nВОПРОС:\n{prompt}"
        
        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(combined_prompt)
        
        with st.chat_message("assistant"):
            st.markdown(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})
        
    except Exception as e:
        st.error(f"Системная ошибка: {e}")
