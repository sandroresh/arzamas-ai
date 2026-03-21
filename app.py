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
    model = genai.GenerativeModel('gemini-2.0-flash') 
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
        
        # УБРАЛИ фильтры date_from и document_date_from. Теперь качается ВСЯ ИСТОРИЯ!
        task_leads = fetch_all_pages_async(base_url, token, "lead", is_study=0)
        task_customers = fetch_all_pages_async(base_url, token, "customer", is_study=1)
        task_teachers = fetch_all_pages_async(base_url, token, "teacher")
        task_lessons = fetch_all_pages_async(base_url, token, "lesson") # Качаем все уроки
        task_pays = fetch_all_pages_async(base_url, token, "pay")       # Качаем все платежи
        
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
def process_data_for_ai(raw_data, user_prompt):
    customers = raw_data["customers"]
    leads = raw_data["leads"]
    teachers = raw_data["teachers"]
    all_lessons = raw_data["lessons"] # Теперь тут вся история
    all_pays = raw_data["pays"]       # Теперь тут вся история
    
    now = raw_data["timestamp"]
    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")

    # 1. ФИЛЬТРУЕМ ИСТОРИЮ (Оставляем только текущий месяц для базовой сводки)
    new_customers = [c for c in customers if f"{current_year}-{current_month}" in str(c.get("date_add", "")) or f".{current_month}.{current_year}" in str(c.get("date_add", ""))]
    
    current_month_pays = [p for p in all_pays if f"{current_year}-{current_month}" in str(p.get("document_date", "")) or f".{current_month}.{current_year}" in str(p.get("document_date", ""))]
    
    current_month_lessons = [l for l in all_lessons if f"{current_year}-{current_month}" in str(l.get("date", ""))]

    # 2. СЧИТАЕМ ЦИФРЫ
    total_debt = sum(abs(float(c.get("balance") or 0)) for c in customers if float(c.get("balance") or 0) < 0)
    total_income = sum(float(p.get("income") or 0) for p in current_month_pays) # Выручка только за этот месяц
    
    attendances, absences = 0, 0
    for lesson in current_month_lessons: # Уроки только за этот месяц
        if isinstance(lesson.get("details"), list):
            for student in lesson["details"]:
                status = student.get("is_attend")
                if status == 1: attendances += 1
                elif status in (0, 2): absences += 1

    # 3. ФОРМИРУЕМ ЛЕГКИЙ ОТЧЕТ ДЛЯ ИИ
    report = f"""
    --- 🏫 ALPHA CRM СВОДКА ({now.strftime("%d.%m.%Y %H:%M")}) ---
    📊 КЛИЕНТЫ: Активных: {len(customers)}. Должников: {sum(1 for c in customers if float(c.get("balance") or 0) < 0)} (Сумма: -{total_debt} ₽). Лидов в базе: {len(leads)}.
    📈 НОВЫЕ ДОГОВОРА (текущий месяц): Пришло {len(new_customers)} чел.
    📚 АКАДЕМИЧЕСКАЯ СВОДКА (месяц): Занятий: {len(current_month_lessons)}. Посещений: {attendances}. Пропусков: {absences}.
    💰 ФИНАНСЫ (месяц): Зафиксировано платежей на сумму: {total_income} ₽.
    """

    # 4. УМНЫЙ ФИЛЬТР ДЛЯ ИМЕН
    prompt_lower = user_prompt.lower()
    trigger_words = ['кто', 'имя', 'имена', 'список', 'кого', 'фамилии', 'ученики', 'преподаватели']
    
    if any(word in prompt_lower for word in trigger_words):
        lead_names = ", ".join([l.get("name") for l in leads[-15:]])
        teacher_names = ", ".join([t.get("name") for t in teachers])
        new_customer_names = ", ".join([c.get("name") for c in new_customers]) if new_customers else "Нет новых"
        
        report += f"""
        \nДЕТАЛИЗАЦИЯ (ИМЕНА):
        - Новенькие в этом месяце: {new_customer_names}
        - Последние 15 лидов: {lead_names}
        - Преподаватели: {teacher_names}
        """
        
    return report
    except Exception as e:
        st.error(f"Системная ошибка: {e}")
