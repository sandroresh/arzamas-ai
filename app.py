import streamlit as st
import google.generativeai as genai
import datetime
import requests
import aiohttp
import asyncio

# --- НАСТРОЙКА СТРАНИЦЫ ---
st.set_page_config(page_title="Alpha Fem Panel", page_icon="👩‍💼")
st.title("Управление школой 'Arzamas'")

# --- ПОДКЛЮЧЕНИЕ ИИ ---
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.0-pro') 
except Exception as e:
    st.error("Ошибка API Ключа Google. Проверьте 'Secrets'.")
    st.stop()

# --- АСИНХРОННЫЙ КЛИЕНТ (Пылесос) ---
async def fetch_page(session, url, token, payload, semaphore):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-ALFACRM-TOKEN": token
    }
    async with semaphore:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 429:
                await asyncio.sleep(2) 
                return await fetch_page(session, url, token, payload, semaphore)
            if response.status == 200:
                return await response.json()
            return None

async def fetch_all_pages_async(base_url, token, entity, branch_id=1, **filters):
    # Если мы запрашиваем лидов, в AlphaCRM это таблица customer с is_study=0
    endpoint_entity = "customer" if entity == "lead" else entity
    url = f"{base_url}/{branch_id}/{endpoint_entity}/index"
    
    all_items = []
    semaphore = asyncio.Semaphore(3) 
    
    async with aiohttp.ClientSession() as session:
        payload = {"page": 0, "pageSize": 100}
        payload.update(filters)
        first_page = await fetch_page(session, url, token, payload, semaphore)
        
        if not first_page or not first_page.get("items"):
            return []
            
        all_items.extend(first_page["items"])
        total_count = int(first_page.get("total", 0))
        
        if total_count <= 100:
            return all_items
            
        total_pages = (total_count + 99) // 100
        tasks = []
        for page in range(1, total_pages):
            page_payload = {"page": page, "pageSize": 100}
            page_payload.update(filters)
            tasks.append(fetch_page(session, url, token, page_payload, semaphore))
            
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res and res.get("items"):
                all_items.extend(res["items"])
                
    return all_items

# --- КЭШИРОВАНИЕ АБСОЛЮТНО ВСЕЙ БАЗЫ В ПАМЯТИ ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_cached_crm_data(hostname, email, api_key_crm):
    base_url = f"https://{hostname}.s20.online/v2api"
    
    auth_payload = {"email": email, "api_key": api_key_crm}
    auth_req = requests.post(f"{base_url}/auth/login", json=auth_payload)
    token = auth_req.json().get("token")
    if not token:
        raise Exception("Ошибка авторизации в CRM")

    async def run_sync():
        # ВЫКАЧИВАЕМ АБСОЛЮТНО ВСЁ ПО СТАТУСАМ
        task_leads = fetch_all_pages_async(base_url, token, "customer", is_study=0)   # Лиды
        task_active = fetch_all_pages_async(base_url, token, "customer", is_study=1)  # Активные
        task_archive = fetch_all_pages_async(base_url, token, "customer", is_study=2) # Архив
        
        task_teachers = fetch_all_pages_async(base_url, token, "teacher")
        task_lessons = fetch_all_pages_async(base_url, token, "lesson")
        task_pays = fetch_all_pages_async(base_url, token, "pay")
        task_groups = fetch_all_pages_async(base_url, token, "group") 
        
        return await asyncio.gather(
            task_leads, task_active, task_archive, 
            task_teachers, task_lessons, task_pays, task_groups
        )

    leads, active_customers, archived_customers, teachers, lessons, pays, groups = asyncio.run(run_sync())
    
    return {
        "leads": leads,
        "active_customers": active_customers,
        "archived_customers": archived_customers,
        "teachers": teachers,
        "lessons": lessons,
        "pays": pays,
        "groups": groups,
        "timestamp": datetime.datetime.now()
    }

# --- ПРОЦЕССОР (Фильтр данных) ---
def process_data_for_ai(raw_data, user_prompt):
    leads = raw_data["leads"]
    active_customers = raw_data["active_customers"]
    archived_customers = raw_data["archived_customers"]
    teachers = raw_data["teachers"]
    all_lessons = raw_data["lessons"] 
    all_pays = raw_data["pays"]       
    groups = raw_data["groups"]
    
    now = raw_data["timestamp"]
    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")

    start_of_week = (now - datetime.timedelta(days=now.weekday())).date()
    end_of_week = start_of_week + datetime.timedelta(days=6)

    # 1. СЧИТАЕМ ИСТОРИЮ (Новенькие в этом месяце)
    new_customers = [c for c in active_customers if f"{current_year}-{current_month}" in str(c.get("date_add", "")) or f".{current_month}.{current_year}" in str(c.get("date_add", ""))]
    current_month_pays = [p for p in all_pays if f"{current_year}-{current_month}" in str(p.get("document_date", "")) or f".{current_month}.{current_year}" in str(p.get("document_date", ""))]
    current_month_lessons = [l for l in all_lessons if f"{current_year}-{current_month}" in str(l.get("date", ""))]

    # 2. ФИНАНСЫ И ДОЛГИ
    total_debt = sum(abs(float(c.get("balance") or 0)) for c in active_customers if float(c.get("balance") or 0) < 0)
    debtors_count = sum(1 for c in active_customers if float(c.get("balance") or 0) < 0)
    total_income = sum(float(p.get("income") or 0) for p in current_month_pays) 
    
    # 3. ПОСЕЩАЕМОСТЬ И УРОКИ
    attendances, absences = 0, 0
    for lesson in current_month_lessons: 
        if isinstance(lesson.get("details"), list):
            for student in lesson["details"]:
                status = student.get("is_attend")
                if status == 1: attendances += 1
                elif status in (0, 2): absences += 1

    current_week_lessons_count = 0
    for l in all_lessons:
        lesson_date_str = str(l.get("date", ""))[:10]
        try:
            l_date = datetime.datetime.strptime(lesson_date_str, "%Y-%m-%d").date()
            if start_of_week <= l_date <= end_of_week:
                current_week_lessons_count += 1
        except Exception:
            pass

    # 4. ФОРМИРУЕМ ОТЧЕТ ДЛЯ ИИ
    report = f"""
    --- 🏫 ALPHA CRM ПОЛНАЯ СВОДКА ({now.strftime("%d.%m.%Y %H:%M")}) ---
    📊 ОБЩАЯ БАЗА КЛИЕНТОВ (ЗА ВСЕ ВРЕМЯ):
       - Активных резидентов сейчас: {len(active_customers)}
       - Учеников в архиве (ушли): {len(archived_customers)}
       - Лидов в базе: {len(leads)}
       - Должников (из активных): {debtors_count} чел. на сумму -{total_debt} ₽.
       
    📈 ДИНАМИКА (ТЕКУЩИЙ МЕСЯЦ):
       - Новых договоров заключено: {len(new_customers)} чел.
       - Зафиксировано платежей на сумму: {total_income} ₽.
       
    📚 АКАДЕМИЧЕСКАЯ СВОДКА: 
       - Учебных групп всего: {len(groups)}. 
       - Занятий проведено за всю историю: {len(all_lessons)}.
       - Занятий за текущий месяц: {len(current_month_lessons)} (Из них на этой неделе: {current_week_lessons_count}).
       - Посещений за месяц: {attendances}. Пропусков: {absences}.
    """

    # 5. УМНЫЙ ФИЛЬТР ИМЕН И ГРУПП (Включается по ключевым словам)
    prompt_lower = user_prompt.lower()
    trigger_words = ['кто', 'имя', 'имена', 'список', 'кого', 'фамилии', 'ученики', 'преподаватели', 'резиденты', 'групп', 'какие', 'сколько', 'архив']
    
    if any(word in prompt_lower for word in trigger_words):
        lead_names = ", ".join([l.get("name") for l in leads[-15:]]) if leads else "Нет данных"
        teacher_names = ", ".join([t.get("name") for t in teachers]) if teachers else "Нет данных"
        new_customer_names = ", ".join([c.get("name") for c in new_customers]) if new_customers else "Нет новых"
        
        # Подсчет учеников по группам
        group_counts = {g.get("id"): 0 for g in groups if g.get("id")}
        for c in active_customers:
            c_groups = c.get("group_ids") or []
            if isinstance(c_groups, list):
                for gid in c_groups:
                    if gid in group_counts:
                        group_counts[gid] += 1
                        
        group_details_list = []
        for g in groups:
            g_name = g.get("name", "Без названия")
            students_count = group_counts.get(g.get("id"), 0)
            group_details_list.append(f"{g_name} (учеников: {students_count})")
            
        groups_formatted = ", ".join(group_details_list) if group_details_list else "Групп не найдено"

        report += f"""
        \nДЕТАЛИЗАЦИЯ (ИМЕНА И ГРУППЫ):
        - Распределение по группам: {groups_formatted}
        - Новенькие в этом месяце: {new_customer_names}
        - Последние 15 лидов: {lead_names}
        - Преподаватели: {teacher_names}
        """
        
    return report

# --- ИНТЕРФЕЙС ЧАТА ---
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.markdown("### Управление")
    if st.button("🔄 Скачать всю базу (Сброс кэша)", use_container_width=True):
        get_cached_crm_data.clear() 
        st.success("Кэш очищен. Полная база будет выкачана при следующем вопросе.")
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
        with st.spinner("Выкачиваю абсолютно ВСЮ базу данных (займет 30-60 секунд)..."):
            raw_data = get_cached_crm_data(
                st.secrets["ALFACRM_HOSTNAME"], 
                st.secrets["ALFACRM_EMAIL"], 
                st.secrets["ALFACRM_API_KEY"]
            )
        
        business_snapshot = process_data_for_ai(raw_data, prompt)
        
        system_instruction = "Ты - операционный директор частной школы Arzamas. Отвечай кратко, профессионально и только на основе предоставленных данных."
        combined_prompt = f"{system_instruction}\n\n### ДАННЫЕ ###\n{business_snapshot}\n\nВОПРОС:\n{prompt}"
        
        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(combined_prompt)
        
        with st.chat_message("assistant"):
            st.markdown(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})
        
    except Exception as e:
        st.error(f"Системная ошибка: {e}")
