def collect_crm_data():
    # 1. Достаем ключи из вашего цифрового сейфа
    hostname = st.secrets["ALFACRM_HOSTNAME"]
    email = st.secrets["ALFACRM_EMAIL"]
    api_key = st.secrets["ALFACRM_API_KEY"]
    
    base_url = f"https://{hostname}.alfacrm.pro/v2-api"
    
    # 2. Стучимся в CRM и получаем временный пропуск (токен)
    auth_payload = {"email": email, "api_key": api_key}
    try:
        auth_res = requests.post(f"{base_url}/auth/login", json=auth_payload).json()
        token = auth_res.get("token")
        if not token:
            return "❌ Ошибка авторизации в Alpha CRM. Проверьте логин и API-ключ в Secrets."
    except Exception as e:
        return f"❌ Ошибка связи с сервером Alpha CRM: {e}"
        
    headers = {"X-ALFACRM-TOKEN": token}
    
    # 3. Запрашиваем активных учеников с отрицательным балансом (должников)
    try:
        # is_study: 1 означает, что ученик активен. balance_to: -1 означает баланс меньше нуля.
        payload_debtors = {"is_study": 1, "balance_to": -1} 
        customers_res = requests.post(f"{base_url}/customer/index", headers=headers, json=payload_debtors).json()
        
        items = customers_res.get("items", [])
        total_debtors = len(items)
        
        # Считаем общую сумму долга
        total_debt_amount = sum(abs(item.get("balance", 0)) for item in items)
        
        # Собираем имена для нейросети (чтобы она знала, о ком речь)
        debtors_list = ", ".join([f"{c.get('name')} ({c.get('balance')} ₽)" for c in items])
        if not debtors_list:
            debtors_list = "Должников нет! Все молодцы."
        
        now = datetime.datetime.now()
        crm_snapshot = f"""
        --- 🏫 ALPHA CRM СЛЕПОК ({now.strftime("%d.%m.%Y %H:%M")}) ---
        Активных должников в базе: {total_debtors}.
        Общая сумма долга: -{total_debt_amount} ₽.
        Детализация по ученикам: {debtors_list}.
        """
        return crm_snapshot
        
    except Exception as e:
        return f"❌ Ошибка при выгрузке списка учеников: {e}"
