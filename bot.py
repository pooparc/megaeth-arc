import time
import json
import os
import requests
import telebot
import threading
from telebot import types  # для кнопок

# ================================
# 🔑 НАСТРОЙКИ – ВСТАВЬ СВОЁ
# ================================

# 1) ТВОЙ TELEGRAM BOT TOKEN от @BotFather
TELEGRAM_BOT_TOKEN = "8320353908:AAEQjUBz9WeJA8vhqb3_0q59NVSq-1QYQ4M"

# 2) ТВОЙ ETHERSCAN API KEY (V2)
ETHERSCAN_API_KEY = "32UHPSNU9Z73CBRUUSFWIGBNJA4BEQBK8Y"  # замени, если у тебя другой

# 3) ДЕФОЛТНЫЙ ПОРОГ, ЕСЛИ ЮЗЕР НИЧЕГО НЕ ЗАДАЛ
DEFAULT_THRESHOLD = 1000.0  # USDC

# 4) ФАЙЛ, ГДЕ БУДЕМ ХРАНИТЬ НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ
SUBSCRIBERS_FILE = "subscribers.json"

# Адреса контрактов
USDC_CONTRACT_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
MEGAETH_DEPOSIT_ADDRESS = "0x46D6Eba3AECD215a3e703cdA963820d4520b45D6"

# Интервал проверки пула
CHECK_INTERVAL_SECONDS = 60  # раз в минуту

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Последний известный баланс пула
last_balance: float | None = None

# Подписчики: chat_id -> threshold (в USDC)
subscribers: dict[int, float] = {}


# ================================
# 💾 Загрузка / сохранение подписчиков
# ================================
def load_subscribers():
    global subscribers
    if not os.path.exists(SUBSCRIBERS_FILE):
        subscribers = {}
        return
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # ключи были строками, конвертим обратно в int
        subscribers = {int(k): float(v) for k, v in data.items()}
        print(f"Загружено подписчиков: {len(subscribers)}")
    except Exception as e:
        print(f"Не удалось загрузить {SUBSCRIBERS_FILE}: {e}")
        subscribers = {}


def save_subscribers():
    try:
        # в JSON ключи должны быть строками
        data = {str(k): float(v) for k, v in subscribers.items()}
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # print("Подписчики сохранены")  # можно раскомментить для дебага
    except Exception as e:
        print(f"Не удалось сохранить {SUBSCRIBERS_FILE}: {e}")


# ================================
# 📌 Баланс через Etherscan V2
# ================================
def get_usdc_balance() -> float:
    """
    Получаем баланс USDC на MegaETH адресе через Etherscan API V2.
    Возвращаем число в USDC.
    """
    url = (
        "https://api.etherscan.io/v2/api"
        "?module=account"
        "&chainid=1"
        "&action=tokenbalance"
        f"&contractaddress={USDC_CONTRACT_ADDRESS}"
        f"&address={MEGAETH_DEPOSIT_ADDRESS}"
        f"&apikey={ETHERSCAN_API_KEY}"
    )

    resp = requests.get(url, timeout=10)
    data = resp.json()

    if data.get("status") != "1":
        raise RuntimeError(f"Ошибка Etherscan V2: {data}")

    raw = int(data.get("result", "0"))
    return raw / 10**6  # у USDC 6 decimals


# ================================
# 🔥 Фоновый мониторинг пула
# ================================
def get_user_threshold(chat_id: int) -> float:
    """Текущий порог юзера или дефолтный, если ещё не задан."""
    return subscribers.get(chat_id, DEFAULT_THRESHOLD)


def monitor_pool():
    global last_balance

    time.sleep(5)  # маленькая пауза после старта

    while True:
        try:
            current = get_usdc_balance()

            if last_balance is None:
                last_balance = current
            else:
                diff = last_balance - current  # > 0 значит был вывод

                if diff > 0 and subscribers:
                    for chat_id, threshold in list(subscribers.items()):
                        try:
                            if diff >= threshold:
                                text = (
                                    "💸 MegaETH predeposit — вывод средств\n\n"
                                    f"Сумма вывода: *{diff:,.2f} USDC*\n"
                                    f"Текущий баланс: *{current:,.2f} USDC*\n\n"
                                    f"Твой порог алерта: *{threshold:,.2f} USDC*.\n"
                                    "💡 Освободились слоты — можно залетать, как только откроют окно."
                                )
                                bot.send_message(chat_id, text, parse_mode="Markdown")
                        except Exception as e:
                            print(f"Не удалось отправить алерт в чат {chat_id}: {e}")

                last_balance = current

        except Exception as e:
            print("❌ Ошибка мониторинга:", e)

        time.sleep(CHECK_INTERVAL_SECONDS)


# ================================
# 🧷 Клавиатура с кнопками порогов
# ================================
def build_threshold_keyboard(current_threshold: float) -> types.InlineKeyboardMarkup:
    """
    Клавиатура с популярными порогами:
    1, 10, 100, 1000, 10000, 100000
    """
    markup = types.InlineKeyboardMarkup(row_width=3)

    presets = [1, 10, 100, 1000, 10000, 100000]
    buttons = []

    for value in presets:
        label = f"{value}$"
        # помечаем текущий порог галочкой
        if abs(current_threshold - value) < 1e-9:
            label = f"✅ {label}"
        btn = types.InlineKeyboardButton(
            text=label,
            callback_data=f"th_{value}"
        )
        buttons.append(btn)

    markup.add(*buttons[:3])
    markup.add(*buttons[3:])

    custom_btn = types.InlineKeyboardButton(
        text="✏ Custom (/setthreshold)",
        callback_data="th_custom_hint"
    )
    markup.add(custom_btn)

    return markup


# ================================
# 🤖 Telegram-команды
# ================================

@bot.message_handler(commands=["start", "help"])
def start(message):
    chat_id = message.chat.id

    # если юзер впервые пишет — подписываем и сохраняем
    if chat_id not in subscribers:
        subscribers[chat_id] = DEFAULT_THRESHOLD
        save_subscribers()

    user_threshold = get_user_threshold(chat_id)

    text = (
        "Привет, это бот по отслеживанию пула в MegaETH.\n"
        "Мы сделали его для удобства отслеживания, чтобы вы могли закинуть свои средства, "
        "как только освободится место.\n\n"
        "Бот пингует по выводу от выбранной тобой суммы, в дальнейшем будет обновление.\n\n"
        "Буду рад подписке на канал в виде поддержки — @wegocrypto8\n\n"
        f"Текущий порог алерта для тебя: *{user_threshold:,.2f} USDC*.\n\n"
        "Команды:\n"
        "• /status — текущий баланс пула\n"
        "• /setthreshold N — установить ЛЮБОЙ порог алерта (в USDC)\n"
        "• /testalert — тестовое уведомление (для проверки бота)\n\n"
        "⬇ Ниже можешь быстро выбрать популярный порог:"
    )

    markup = build_threshold_keyboard(user_threshold)
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(commands=["status"])
def status(message):
    chat_id = message.chat.id
    if chat_id not in subscribers:
        subscribers[chat_id] = DEFAULT_THRESHOLD
        save_subscribers()

    try:
        balance = get_usdc_balance()
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при получении данных:\n`{e}`", parse_mode="Markdown")
        return

    user_threshold = get_user_threshold(chat_id)

    text = (
        "💰 Баланс MegaETH пула:\n"
        f"*{balance:,.2f} USDC*\n\n"
        f"Твой текущий порог алерта: *{user_threshold:,.2f} USDC*.\n\n"
        "Хочешь поменять порог — нажми кнопку ниже или используй `/setthreshold N`."
    )
    markup = build_threshold_keyboard(user_threshold)
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(commands=["setthreshold"])
def setthreshold(message):
    chat_id = message.chat.id
    parts = message.text.strip().split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(
            message,
            "Укажи порог после команды.\nНапример:\n`/setthreshold 2500`",
            parse_mode="Markdown",
        )
        return

    value_str = parts[1].replace(",", ".")  # поддержка 1,5 и 1.5

    try:
        value = float(value_str)
    except ValueError:
        bot.reply_to(message, "Порог должен быть числом (например: 1, 10, 1500, 2500.5).")
        return

    if value <= 0:
        bot.reply_to(message, "Порог должен быть больше 0.")
        return

    subscribers[chat_id] = value
    save_subscribers()

    text = (
        f"✅ Порог алерта установлен на *{value:,.2f} USDC*.\n"
        "Бот будет слать уведомления только при выводах ⩾ этой суммы."
    )
    markup = build_threshold_keyboard(value)
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(commands=["testalert"])
def testalert(message):
    """
    Ручной тест: фейковый вывод чуть выше твоего порога.
    """
    chat_id = message.chat.id
    if chat_id not in subscribers:
        subscribers[chat_id] = DEFAULT_THRESHOLD
        save_subscribers()

    user_threshold = get_user_threshold(chat_id)
    fake_diff = user_threshold + 1.0  # типа вывели на 1 USDC больше порога

    try:
        current = get_usdc_balance()
    except Exception as e:
        bot.reply_to(message, f"❌ Не удалось получить баланс для теста:\n`{e}`", parse_mode="Markdown")
        return

    text = (
        "🧪 ТЕСТОВЫЙ АЛЕРТ MegaETH predeposit\n\n"
        f"Сумма вывода (симуляция): *{fake_diff:,.2f} USDC*\n"
        f"Текущий баланс: *{current:,.2f} USDC*\n\n"
        f"Твой порог алерта: *{user_threshold:,.2f} USDC*.\n"
        "Если ты видишь это сообщение — значит реальные уведомления о выводах тоже придут 👍"
    )

    try:
        bot.send_message(chat_id, text, parse_mode="Markdown")
    except Exception as e:
        print(f"Не удалось отправить testalert в чат {chat_id}: {e}")


# ================================
# 🎛 Обработка нажатия на кнопки
# ================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("th_"))
def callback_set_threshold(call: types.CallbackQuery):
    chat_id = call.message.chat.id

    # подсказка по кастомному порогу
    if call.data == "th_custom_hint":
        bot.answer_callback_query(
            call.id,
            text="Введи свой порог командой: /setthreshold <число>",
            show_alert=True
        )
        return

    # формат th_1000
    _, value_str = call.data.split("_", maxsplit=1)
    try:
        value = float(value_str)
    except ValueError:
        bot.answer_callback_query(call.id, text="Ошибка значения порога.")
        return

    subscribers[chat_id] = value
    save_subscribers()

    bot.answer_callback_query(call.id, text=f"Порог алерта: {value:,.0f} USDC")

    user_threshold = value
    text = (
        f"✅ Порог алерта обновлён: *{user_threshold:,.0f} USDC*.\n\n"
        "Бот будет слать уведомления только при выводах ⩾ этой суммы."
    )
    markup = build_threshold_keyboard(user_threshold)

    try:
        bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
    except Exception:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


# ================================
# 🚀 Запуск
# ================================
if __name__ == "__main__":
    print("Бот запускается...")

    # 1) Загружаем сохранённых подписчиков (если файл есть)
    load_subscribers()

    print(f"Подписчиков загружено: {len(subscribers)}")
    print("Бот запущен с мониторингом MegaETH...")

    # 2) Запускаем фоновой мониторинг в отдельном потоке
    t = threading.Thread(target=monitor_pool, daemon=True)
    t.start()

    # 3) Запускаем polling
    bot.infinity_polling()
