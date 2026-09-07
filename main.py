# -*- coding: utf-8 -*-
import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import datetime
import enum
import os
from dotenv import load_dotenv

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден в файле .env!")
    exit()

DATABASE_URL = "sqlite:///database.db"
logging.basicConfig(level=logging.INFO)

# ========== БАЗА ДАННЫХ ==========
engine = create_engine(DATABASE_URL)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class UserClass(enum.Enum):
    RYTSAR = "Рыцарь"
    TEMNYI_STRAZH = "Тёмный Страж"
    VARVAR = "Варвар"
    VOLSHEBNIK = "Волшебник"
    INZHENER = "Инженер"
    BARD = "Бард"
    TEN = "Тень"
    SLEDOPYT = "Следопыт"
    ZHRETS = "Жрец"
    DRUID = "Друид"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(64), unique=True, nullable=False)
    class_name = Column(Enum(UserClass), nullable=False)
    level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    age = Column(Integer, nullable=True)
    city = Column(String(100), nullable=True)
    status = Column(String(20), default="idle")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)

class UserTag(Base):
    __tablename__ = "user_tags"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    category = Column(String(50), nullable=False)
    tag = Column(String(50), nullable=False)

Base.metadata.create_all(engine)

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Моя анкета", callback_data="profile")],
        [InlineKeyboardButton(text="⚔️ Искать напарника", callback_data="find_match")],
        [InlineKeyboardButton(text="📝 Редактировать анкету", callback_data="edit_profile")]
    ])

def class_choice():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать квиз! 🎯", callback_data="class_start")]
    ])

def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def tag_choice_kb():
    tags = {
        "Развлечения": ["Видеоигры", "Фильмы", "Книги", "Музыка", "Рисование", "Настольные игры"],
        "Активности": ["Спорт", "Походы", "Велоспорт", "Плавание", "Йога", "Танцы"],
        "Путешествия": ["Путешествия", "Кемпинг", "Пляж", "Горы", "Города", "Природа"],
        "Интеллект": ["Наука", "IT/Технологии", "Психология", "История", "Языки", "Философия"],
        "Еда": ["Кулинария", "Кофе", "Вино", "Фастфуд", "Суши", "ЗОЖ"],
        "Личность": ["Лидер", "Наблюдатель", "Эмпат", "Домосед", "Тусовщик", "Дипломат"]
    }
    keyboard = []
    for category, tag_list in tags.items():
        row = [InlineKeyboardButton(text=tag, callback_data=f"tag_{category}_{tag}") for tag in tag_list]
        keyboard.append(row)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== ТЕКСТЫ ==========
WELCOME = """
🏰 Добро пожаловать в **Резонанс**!

Ты — искатель приключений в мире, где знакомства становятся частью RPG-приключения.

Нажми **"Начать квиз!"**, чтобы узнать свой класс.
"""

PROFILE_TEMPLATE = """
📜 **Твоя анкета**

👤 **Имя:** {username}
⚔️ **Класс:** {class_name}
📈 **Уровень:** {level}
🎂 **Возраст:** {age}
🏙️ **Город:** {city}
🏷️ **Теги:**
{tags}
📊 **Статус:** {status}
"""

CLASS_DESCRIPTIONS = {
    "Рыцарь": "Ты — Рыцарь. Честь и защита слабых — твой путь.",
    "Тёмный Страж": "Ты — Тёмный Страж. Ты несешь суровую справедливость.",
    "Варвар": "Ты — Варвар. Сила и интуиция ведут тебя.",
    "Волшебник": "Ты — Волшебник. Знание — твоя сила.",
    "Инженер": "Ты — Инженер. Ты чинишь всё, что сломано.",
    "Бард": "Ты — Бард. Харизма и юмор — твоё оружие.",
    "Тень": "Ты — Тень. Ты наблюдаешь и действуешь скрытно.",
    "Следопыт": "Ты — Следопыт. Ты видишь то, что ускользает от других.",
    "Жрец": "Ты — Жрец. Ты исцеляешь и даришь свет.",
    "Друид": "Ты — Друид. Ты часть природы и её хранитель."
}

# ========== СОСТОЯНИЯ ==========
class RegForm(StatesGroup):
    username = State()
    age = State()
    city = State()
    tags = State()

# ========== КВИЗ (7 ВОПРОСОВ) ==========
QUESTIONS = [
    {
        "text": "Ты заходишь в переполненную комнату. Твои действия?",
        "options": {
            "Быстро найду знакомых или создам свою компанию.": {"Бард": 2},
            "Встану у стены и буду наблюдать.": {"Тень": 2},
            "Подойду к тому, кто выглядит потерянным, и помогу освоиться.": {"Жрец": 2},
            "Пройду к центру и заявлю о себе.": {"Рыцарь": 2}
        }
    },
    {
        "text": "Ты нашёл старую карту сокровищ. Что сделаешь?",
        "options": {
            "Сразу отправлюсь на поиски, не раздумывая.": {"Варвар": 2},
            "Изучу карту, проверю её подлинность.": {"Волшебник": 2},
            "Попытаюсь продать или обменять.": {"Бард": 2},
            "Позову друзей, чтобы идти вместе.": {"Рыцарь": 1, "Жрец": 1}
        }
    },
    {
        "text": "Твой друг совершил ошибку, которая тебя подвела. Твоя реакция?",
        "options": {
            "Прощу, ведь все ошибаются.": {"Жрец": 2},
            "Устрою разговор, чтобы выяснить причины.": {"Волшебник": 2},
            "Обижусь, но не покажу виду, буду действовать сам.": {"Тень": 2},
            "Скажу прямо, что так нельзя, и потребую исправить.": {"Рыцарь": 2},
            "Запомню этот урок и буду осторожнее в будущем.": {"Тёмный Страж": 2}
        }
    },
    {
        "text": "Какой стиль отдыха тебе ближе?",
        "options": {
            "Активный отдых на природе с палаткой и костром.": {"Следопыт": 2, "Варвар": 1},
            "Тихий вечер с книгой или музыкой.": {"Волшебник": 2, "Жрец": 1},
            "Вечеринка с друзьями в шумной компании.": {"Бард": 2},
            "Прогулка по городу, изучение новых мест.": {"Инженер": 2, "Бард": 1}
        }
    },
    {
        "text": "Ты оказался в опасной ситуации. Кто может тебе помочь?",
        "options": {
            "Моя интуиция и быстрая реакция.": {"Варвар": 2},
            "Разум и холодный расчёт.": {"Волшебник": 2},
            "Надёжный друг, которому я доверяю.": {"Рыцарь": 2, "Жрец": 1},
            "Мои скрытые таланты и ловкость.": {"Бард": 2, "Тень": 1},
            "Моя выдержка и умение ждать.": {"Тёмный Страж": 2}
        }
    },
    {
        "text": "Как ты относишься к правилам?",
        "options": {
            "Правила созданы, чтобы их уважать и следовать им.": {"Рыцарь": 2, "Жрец": 1},
            "Правила — это ограничения, которые можно обойти.": {"Бард": 2},
            "Правила интересно изучать, чтобы понять их суть.": {"Волшебник": 2, "Инженер": 1},
            "Правила пишутся под ситуацию, я действую по обстоятельствам.": {"Варвар": 2, "Следопыт": 1},
            "Я следую своему кодексу, даже если он противоречит общим правилам.": {"Тёмный Страж": 2}
        }
    },
    {
        "text": "Какое качество ты ценишь в людях больше всего?",
        "options": {
            "Честность.": {"Рыцарь": 2, "Тёмный Страж": 1},
            "Ум.": {"Волшебник": 2, "Инженер": 1},
            "Доброту.": {"Жрец": 2, "Друид": 1},
            "Чувство юмора.": {"Бард": 2},
            "Свободу и независимость.": {"Следопыт": 2, "Варвар": 1}
        }
    }
]

# ========== АВТОМАТИЧЕСКИЙ ПОДБОР ПРОКСИ ==========
PROXY_LIST = [
    "http://91.107.242.226:8080",
    "http://45.155.68.129:8080",
    "http://195.206.226.226:8080",
    "socks5://91.107.242.226:1080",
    "socks5://45.155.68.129:1080",
]

async def create_bot_with_proxy():
    for proxy in PROXY_LIST:
        try:
            session = AiohttpSession(proxy=proxy)
            bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties())
            await bot.get_me()
            print(f"✅ Прокси работает: {proxy}")
            return bot
        except Exception as e:
            print(f"❌ Прокси {proxy} не работает: {e}")
            continue
    print("⚠️ Все прокси отвалились, пробую без прокси...")
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
    try:
        await bot.get_me()
        print("✅ Работает без прокси!")
        return bot
    except Exception as e:
        print(f"❌ И без прокси не работает: {e}")
        return None

# ========== БОТ ==========
dp = Dispatcher()

@dp.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
    if user:
        await msg.answer(f"С возвращением, {user.username}! 🎮", reply_markup=main_menu())
    else:
        await msg.answer(WELCOME, reply_markup=class_choice())

@dp.callback_query(F.data == "class_start")
async def start_quiz(call: CallbackQuery, state: FSMContext):
    await state.update_data(quiz_step=0, scores={})
    await ask_question(call.message, state, 0)
    await call.answer()

async def ask_question(message, state, step):
    if step >= len(QUESTIONS):
        await finish_quiz(message, state)
        return
    q = QUESTIONS[step]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=f"q_{step}_{i}")] for i, t in enumerate(q["options"].keys())
    ])
    await message.edit_text(f"📜 Вопрос {step+1} из {len(QUESTIONS)}:\n\n{q['text']}", reply_markup=kb)

@dp.callback_query(F.data.startswith("q_"))
async def answer_quiz(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = int(call.data.split("_")[1])
    idx = int(call.data.split("_")[2])
    q = QUESTIONS[step]
    opt_text = list(q["options"].keys())[idx]
    scores = data.get("scores", {})
    for cls, pts in q["options"][opt_text].items():
        scores[cls] = scores.get(cls, 0) + pts
    await state.update_data(scores=scores)
    await ask_question(call.message, state, step + 1)
    await call.answer()

async def finish_quiz(message, state):
    data = await state.get_data()
    scores = data.get("scores", {})
    if not scores:
        await message.edit_text("❌ Ошибка. Попробуй /start заново.")
        return
    class_name = max(scores, key=scores.get)
    class_map = {
        "Рыцарь": UserClass.RYTSAR, "Тёмный Страж": UserClass.TEMNYI_STRAZH,
        "Варвар": UserClass.VARVAR, "Волшебник": UserClass.VOLSHEBNIK,
        "Инженер": UserClass.INZHENER, "Бард": UserClass.BARD,
        "Тень": UserClass.TEN, "Следопыт": UserClass.SLEDOPYT,
        "Жрец": UserClass.ZHRETS, "Друид": UserClass.DRUID
    }
    user_class = class_map.get(class_name, UserClass.RYTSAR)
    await state.update_data(class_name=user_class)
    emoji = {"Рыцарь": "🗡️", "Тёмный Страж": "💜", "Варвар": "⚔️", "Волшебник": "🧙",
             "Инженер": "🗝️", "Бард": "🎭", "Тень": "🌙", "Следопыт": "🏹", "Жрец": "🛡️", "Друид": "🌿"}
    await message.edit_text(
        f"🎉 Ты — **{emoji[class_name]} {class_name}**!\n\n{CLASS_DESCRIPTIONS.get(class_name, '')}\n\nТеперь заполни анкету."
    )
    await message.answer("📝 Введи **никнейм** (2–30 символов):", reply_markup=cancel_kb())
    await state.set_state(RegForm.username)

@dp.message(RegForm.username)
async def set_username(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if len(name) < 2 or len(name) > 30:
        await msg.answer("❌ Никнейм должен быть 2–30 символов.")
        return
    with SessionLocal() as session_db:
        if session_db.execute(select(User).where(User.username == name)).scalar_one_or_none():
            await msg.answer("❌ Этот никнейм занят.")
            return
    await state.update_data(username=name)
    await msg.answer("🎂 Сколько тебе лет? (16–99)", reply_markup=cancel_kb())
    await state.set_state(RegForm.age)

@dp.message(RegForm.age)
async def set_age(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❌ Введи число.")
        return
    age = int(msg.text)
    if age < 16 or age > 99:
        await msg.answer("❌ Возраст от 16 до 99.")
        return
    await state.update_data(age=age)
    await msg.answer("🏙️ Из какого ты города?", reply_markup=cancel_kb())
    await state.set_state(RegForm.city)

@dp.message(RegForm.city)
async def set_city(msg: Message, state: FSMContext):
    await state.update_data(city=msg.text.strip())
    await msg.answer("🏷️ Выбери теги (по одному из каждой категории):", reply_markup=tag_choice_kb())
    await state.set_state(RegForm.tags)

@dp.callback_query(F.data.startswith("tag_"))
async def set_tag(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tags = data.get("tags", {})
    category, tag = call.data.split("_")[1], "_".join(call.data.split("_")[2:])
    tags[category] = tag
    await state.update_data(tags=tags)
    categories = ["Развлечения", "Активности", "Путешествия", "Интеллект", "Еда", "Личность"]
    if len(tags) >= len(categories):
        await finish_registration(call.message, state)
    else:
        await call.message.edit_text(f"✅ Выбрано {len(tags)} из {len(categories)}. Продолжай:", reply_markup=tag_choice_kb())
    await call.answer()

async def finish_registration(message, state):
    data = await state.get_data()
    with SessionLocal() as session_db:
        user = User(
            tg_id=message.from_user.id,
            username=data["username"],
            class_name=data["class_name"],
            age=data["age"],
            city=data["city"],
            status="idle"
        )
        session_db.add(user)
        session_db.flush()
        for category, tag in data.get("tags", {}).items():
            session_db.add(UserTag(user_id=user.id, category=category, tag=tag))
        session_db.commit()
    await state.clear()
    await message.edit_text(f"✅ Регистрация завершена! Добро пожаловать, {data['username']}!", reply_markup=main_menu())

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.message.answer("❌ Ты не зарегистрирован!")
            return
        tags = session_db.execute(select(UserTag).where(UserTag.user_id == user.id)).scalars().all()
        tags_text = "\n".join([f"• {t.category}: {t.tag}" for t in tags]) or "Не выбраны"
        emoji = {"Рыцарь": "🗡️", "Тёмный Страж": "💜", "Варвар": "⚔️", "Волшебник": "🧙",
                 "Инженер": "🗝️", "Бард": "🎭", "Тень": "🌙", "Следопыт": "🏹", "Жрец": "🛡️", "Друид": "🌿"}
        await call.message.edit_text(
            PROFILE_TEMPLATE.format(
                username=user.username,
                class_name=f"{emoji.get(user.class_name.value, '')} {user.class_name.value}",
                level=user.level,
                age=user.age or "Не указан",
                city=user.city or "Не указан",
                tags=tags_text,
                status=user.status
            ),
            reply_markup=main_menu()
        )
    await call.answer()

@dp.callback_query(F.data == "edit_profile")
async def edit_profile(call: CallbackQuery):
    await call.message.edit_text(
        "📝 Редактирование:\n/setname Имя\n/setage 25\n/setcity Москва",
        reply_markup=main_menu()
    )
    await call.answer()

@dp.callback_query(F.data == "find_match")
async def find_match(call: CallbackQuery):
    await call.message.answer("⚔️ Поиск напарника скоро появится! 🚀")
    await call.answer()

@dp.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Отменено. Напиши /start.")
    await call.answer()

@dp.message(Command("setname"))
async def setname(msg: Message):
    name = msg.text.replace("/setname", "").strip()
    if not name or len(name) < 2:
        await msg.answer("❌ Пример: /setname Артур")
        return
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!")
            return
        if session_db.execute(select(User).where(User.username == name, User.tg_id != msg.from_user.id)).scalar_one_or_none():
            await msg.answer("❌ Этот никнейм занят.")
            return
        user.username = name
        session_db.commit()
        await msg.answer(f"✅ Имя изменено на {name}")

@dp.message(Command("setage"))
async def setage(msg: Message):
    age = msg.text.replace("/setage", "").strip()
    if not age.isdigit() or int(age) < 16 or int(age) > 99:
        await msg.answer("❌ Пример: /setage 25")
        return
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!")
            return
        user.age = int(age)
        session_db.commit()
        await msg.answer(f"✅ Возраст изменён на {age}")

@dp.message(Command("setcity"))
async def setcity(msg: Message):
    city = msg.text.replace("/setcity", "").strip()
    if not city:
        await msg.answer("❌ Пример: /setcity Москва")
        return
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!")
            return
        user.city = city
        session_db.commit()
        await msg.answer(f"✅ Город изменён на {city}")

# ========== ЗАПУСК ==========
async def main():
    bot = await create_bot_with_proxy()
    if not bot:
        print("❌ Не удалось подключиться к Telegram.")
        return
    print("✅ База данных готова!")
    print("🚀 Бот 'Резонанс' запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
     