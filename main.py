# -*- coding: utf-8 -*-
import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.bot import DefaultBotProperties
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, Enum, BigInteger
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

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///database.db")
logging.basicConfig(level=logging.INFO)

# ========== БАЗА ДАННЫХ ==========
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
    tg_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(64), unique=True, nullable=False)
    class_name = Column(Enum(UserClass), nullable=False)
    level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    age = Column(Integer, nullable=True)
    city = Column(String(100), nullable=True)
    status = Column(String(20), default="idle")  # idle / searching / matched / dungeon
    partner_tg_id = Column(BigInteger, nullable=True)
    is_ready = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)

class UserTag(Base):
    __tablename__ = "user_tags"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    category = Column(String(50), nullable=False)
    tag = Column(String(50), nullable=False)

class DungeonSession(Base):
    __tablename__ = "dungeon_sessions"
    id = Column(Integer, primary_key=True)
    player1_tg_id = Column(BigInteger, nullable=False)
    player2_tg_id = Column(BigInteger, nullable=False)
    current_question = Column(Integer, default=0)
    player1_answer = Column(Integer, nullable=True)
    player2_answer = Column(Integer, nullable=True)
    player1_ready = Column(Boolean, default=False)
    player2_ready = Column(Boolean, default=False)
    matches_count = Column(Integer, default=0)   # полных совпадений (same)
    soft_count = Column(Integer, default=0)      # единство по духу (оба soft)
    mixed_count = Column(Integer, default=0)     # компромисс (разные)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(engine)
# Если менял схему (добавлял поля в DungeonSession) - на ОДИН запуск:
# Base.metadata.create_all(engine)

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

def ready_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готов!", callback_data="ready")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_match")]
    ])

# ========== ДАННЫЕ ДЛЯ ТЕГОВ-КВИЗА ==========
TAG_QUESTIONS = [
    {"category": "Развлечения", "question": "🎮 Как ты обычно проводишь свободное время?",
     "tags": ["Видеоигры", "Фильмы", "Книги", "Музыка", "Рисование", "Настольные игры"]},
    {"category": "Активности", "question": "🏃 Что из этого тебя заряжает энергией?",
     "tags": ["Спорт", "Походы", "Велоспорт", "Плавание", "Йога", "Танцы"]},
    {"category": "Путешествия", "question": "🌍 Если бы у тебя был портал в любую точку мира — куда бы ты шагнул?",
     "tags": ["✈️ Новое неизведанное", "🏕️ Лес, костёр и звёзды", "🏖️ Тёплый пляж", "🏔️ Горы и тишина", "🏙️ Шумный мегаполис", "🌿 Дикая природа"]},
    {"category": "Интеллект", "question": "🧠 Какая тема вызывает у тебя живой интерес?",
     "tags": ["Наука", "IT/Технологии", "Психология", "История", "Языки", "Философия"]},
    {"category": "Еда", "question": "🍽️ Что из этого ты предпочитаешь?",
     "tags": ["Кулинария", "Кофе", "Вино", "Фастфуд", "Суши", "ЗОЖ"]},
    {"category": "Личность", "question": "🧑‍🤝‍🧑 Как бы ты описал себя в компании?",
     "tags": ["Лидер", "Наблюдатель", "Эмпат", "Домосед", "Тусовщик", "Дипломат"]}
]

def tag_question_kb(tags, step):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=f"tag_{step}_{i}")] for i, t in enumerate(tags)
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])

# ========== ТЕКСТЫ ==========
WELCOME = """
🏰 Добро пожаловать в **Рейд Сердец**!

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

CLASS_EMOJI = {"Рыцарь": "🗡️", "Тёмный Страж": "💜", "Варвар": "⚔️", "Волшебник": "🧙",
               "Инженер": "🗝️", "Бард": "🎭", "Тень": "🌙", "Следопыт": "🏹", "Жрец": "🛡️", "Друид": "🌿"}

STATUS_NAMES = {"idle": "🟢 Свободен", "searching": "🟡 В поиске", "matched": "🔵 Нашёл пару", "dungeon": "🔴 В приключении"}

# ========== СОСТОЯНИЯ ==========
class RegForm(StatesGroup):
    username = State()
    age = State()
    city = State()
    tag_step = State()

# ========== КВИЗ НА КЛАСС ==========
QUESTIONS = [
    {"text": "Ты заходишь в переполненную комнату. Твои действия?",
     "options": {"Быстро найду знакомых или создам свою компанию.": {"Бард": 2},
                 "Встану у стены и буду наблюдать.": {"Тень": 2},
                 "Подойду к тому, кто выглядит потерянным, и помогу освоиться.": {"Жрец": 2},
                 "Пройду к центру и заявлю о себе.": {"Рыцарь": 2}}},
    {"text": "Ты нашёл старую карту сокровищ. Что сделаешь?",
     "options": {"Сразу отправлюсь на поиски, не раздумывая.": {"Варвар": 2},
                 "Изучу карту, проверю её подлинность.": {"Волшебник": 2},
                 "Попытаюсь продать или обменять.": {"Бард": 2},
                 "Позову друзей, чтобы идти вместе.": {"Рыцарь": 1, "Жрец": 1}}},
    {"text": "Твой друг совершил ошибку, которая тебя подвела. Твоя реакция?",
     "options": {"Прощу, ведь все ошибаются.": {"Жрец": 2},
                 "Устрою разговор, чтобы выяснить причины.": {"Волшебник": 2},
                 "Обижусь, но не покажу виду, буду действовать сам.": {"Тень": 2},
                 "Скажу прямо, что так нельзя, и потребую исправить.": {"Рыцарь": 2},
                 "Запомню этот урок и буду осторожнее в будущем.": {"Тёмный Страж": 2}}},
    {"text": "Какой стиль отдыха тебе ближе?",
     "options": {"Активный отдых на природе с палаткой и костром.": {"Следопыт": 2, "Варвар": 1},
                 "Тихий вечер с книгой или музыкой.": {"Волшебник": 2, "Жрец": 1},
                 "Вечеринка с друзьями в шумной компании.": {"Бард": 2},
                 "Прогулка по городу, изучение новых мест.": {"Инженер": 2, "Бард": 1}}},
    {"text": "Ты оказался в опасной ситуации. Кто может тебе помочь?",
     "options": {"Моя интуиция и быстрая реакция.": {"Варвар": 2},
                 "Разум и холодный расчёт.": {"Волшебник": 2},
                 "Надёжный друг, которому я доверяю.": {"Рыцарь": 2, "Жрец": 1},
                 "Мои скрытые таланты и ловкость.": {"Бард": 2, "Тень": 1},
                 "Моя выдержка и умение ждать.": {"Тёмный Страж": 2}}},
    {"text": "Как ты относишься к правилам?",
     "options": {"Правила созданы, чтобы их уважать и следовать им.": {"Рыцарь": 2, "Жрец": 1},
                 "Правила — это ограничения, которые можно обойти.": {"Бард": 2},
                 "Правила интересно изучать, чтобы понять их суть.": {"Волшебник": 2, "Инженер": 1},
                 "Правила пишутся под ситуацию, я действую по обстоятельствам.": {"Варвар": 2, "Следопыт": 1},
                 "Я следую своему кодексу, даже если он противоречит общим правилам.": {"Тёмный Страж": 2}}},
    {"text": "Какое качество ты ценишь в людях больше всего?",
     "options": {"Честность.": {"Рыцарь": 2, "Тёмный Страж": 1},
                 "Ум.": {"Волшебник": 2, "Инженер": 1},
                 "Доброту.": {"Жрец": 2, "Друид": 1},
                 "Чувство юмора.": {"Бард": 2},
                 "Свободу и независимость.": {"Следопыт": 2, "Варвар": 1}}}
]

# ========== ДАНЖ: ЛЕС ОБОРОТНЕЙ ==========
# Вопросы: text, options (с soft-флагом), bridges (same/soft/mixed)
FOREST_QUESTIONS = [
    {
        "text": "🌲 На опушке вас встретил улыбчивый охотник. Он предлагает проводить до деревни.",
        "options": [
            {"text": "Пойду с ним — помощь нужна", "soft": True},
            {"text": "Откажусь, пойду сам", "soft": False},
            {"text": "Пойду, но буду следить за ним", "soft": False},
        ],
        "bridges": {
            "same": "Охотник повёл вас через лес. Деревья смыкаются за спиной, а тропа становится всё уже.",
            "soft": "Вы идёте по лесу. Тропа извилистая, но тихая. Над головой шумит листва.",
            "mixed": "Вы двинулись вглубь леса. Воздух становится холоднее, где-то вдалеке воет волк.",
        }
    },
    {
        "text": "🌙 Ночью у костра охотник рассказал историю о проклятии. Он странно смотрит на луну.",
        "options": [
            {"text": "Спрошу прямо, что с ним", "soft": False},
            {"text": "Сделаю вид, что не заметил", "soft": True},
            {"text": "Тихо достану оружие", "soft": False},
        ],
        "bridges": {
            "same": "Ночь прошла спокойно. Утром вы продолжили путь молча.",
            "soft": "Вы проснулись от холода. Костёр погас, а охотник сидит и смотрит вдаль.",
            "mixed": "Ночь была тревожной. Вы оба плохо спали, но не подали виду.",
        }
    },
    {
        "text": "🏡 Вы нашли деревню. Жители слишком приветливы, слишком сыты.",
        "options": [
            {"text": "Это заговор, надо быть начеку", "soft": False},
            {"text": "Просто гостеприимные люди", "soft": True},
            {"text": "Что-то тут не так, но виду не подам", "soft": True},
        ],
        "bridges": {
            "same": "Вас пригласили в дом. Ужин на столе, но что-то в этом доме не так.",
            "soft": "Вас встретили тепло. Хозяева улыбаются, но улыбки кажутся застывшими.",
            "mixed": "Вам выделили комнату. Дверь закрылась, и вы остались одни.",
        }
    },
    {
        "text": "🐺 Ночью вы проснулись от воя. Рядом волчий след.",
        "options": [
            {"text": "Разбужу напарника", "soft": True},
            {"text": "Пойду по следу один", "soft": False},
            {"text": "Притворюсь спящим и буду ждать", "soft": True},
        ],
        "bridges": {
            "same": "Вы не сомкнули глаз до утра. След исчез к рассвету.",
            "soft": "Вы лежали тихо, слушая ночь. Вой стих так же внезапно, как и начался.",
            "mixed": "Ночь прошла в напряжении. Утром вы нашли ещё один след — свежий.",
        }
    },
    {
        "text": "📜 Охотник предлагает сделку: «Отдай мне свой амулет — проведу безопасной тропой».",
        "options": [
            {"text": "Отдам — безопасность важнее", "soft": True},
            {"text": "Откажусь — он врёт", "soft": False},
            {"text": "Предложу взамен что-то другое", "soft": False},
        ],
        "bridges": {
            "same": "Охотник кивнул и повёл вас дальше. Тропа стала шире.",
            "soft": "Вы продолжили путь. Лес будто расступился перед вами.",
            "mixed": "Охотник что-то пробормотал и пошёл вперёд. Вы двинулись следом.",
        }
    },
    {
        "text": "🌕 Вы узнали, что охотник — оборотень. Он стоит перед вами и улыбается.",
        "options": [
            {"text": "Атакую первым", "soft": False},
            {"text": "Попробую договориться", "soft": True},
            {"text": "Притворюсь, что не знаю", "soft": True},
        ],
        "bridges": {
            "same": "Оборотень прищурился. Между вами повисла тишина.",
            "soft": "Оборотень опустил глаза. Что-то в его облике смягчилось.",
            "mixed": "Оборотень замер. Воздух стал тяжёлым, будто перед грозой.",
        }
    },
    {
        "text": "🐺 Оборотень предлагает: «Я помогу вам, если сохраните мою тайну».",
        "options": [
            {"text": "Соглашусь", "soft": True},
            {"text": "Откажусь, это опасно", "soft": False},
            {"text": "Соглашусь, но потом расскажу", "soft": False},
        ],
        "bridges": {
            "same": "Оборотень улыбнулся и кивнул. Он повёл вас через лес.",
            "soft": "Он вздохнул с облегчением. Лес вокруг будто стал светлее.",
            "mixed": "Он посмотрел на вас долгим взглядом, но ничего не сказал.",
        }
    },
    {
        "text": "🏡 Вы добрались до деревни. Оборотень ждёт вашего решения.",
        "options": [
            {"text": "Расскажу жителям — они должны знать", "soft": False},
            {"text": "Сохраню тайну — он помог нам", "soft": True},
            {"text": "Уйду молча — это не моё дело", "soft": True},
        ],
        "bridges": {
            "same": "Решение принято. Деревня встречает вас тишиной.",
            "soft": "Вы сделали свой выбор. Лес за спиной будто выдохнул.",
            "mixed": "Деревня ждёт. И вы чувствуете, что этот выбор что-то изменит.",
        }
    },
]

DUNGEON_QUESTIONS = FOREST_QUESTIONS
TOTAL_QUESTIONS = len(DUNGEON_QUESTIONS)

def dungeon_kb(q_idx):
    q = DUNGEON_QUESTIONS[q_idx]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt["text"], callback_data=f"dq_{q_idx}_{i}")]
        for i, opt in enumerate(q["options"])
    ])

# ========== БОТ ==========
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
dp = Dispatcher()

# ---------- /start ----------
@dp.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
    if user:
        await msg.answer(f"С возвращением, {user.username}! 🎮", reply_markup=main_menu())
    else:
        await msg.answer(WELCOME, reply_markup=class_choice())

# ---------- КВИЗ ----------
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
    class_map = {"Рыцарь": UserClass.RYTSAR, "Тёмный Страж": UserClass.TEMNYI_STRAZH,
                 "Варвар": UserClass.VARVAR, "Волшебник": UserClass.VOLSHEBNIK,
                 "Инженер": UserClass.INZHENER, "Бард": UserClass.BARD,
                 "Тень": UserClass.TEN, "Следопыт": UserClass.SLEDOPYT,
                 "Жрец": UserClass.ZHRETS, "Друид": UserClass.DRUID}
    user_class = class_map.get(class_name, UserClass.RYTSAR)
    await state.update_data(class_name=user_class)
    await message.edit_text(
        f"🎉 Ты — **{CLASS_EMOJI[class_name]} {class_name}**!\n\n{CLASS_DESCRIPTIONS.get(class_name, '')}\n\nТеперь заполни анкету."
    )
    await message.answer("📝 Введи **никнейм** (2–30 символов):", reply_markup=cancel_kb())
    await state.set_state(RegForm.username)

# ---------- АНКЕТА ----------
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
    await state.update_data(selected_tags={})
    await state.set_state(RegForm.tag_step)
    await ask_tag_question(msg, state, 0, msg.from_user.id)

# ---------- КВИЗ ПО ТЕГАМ ----------
async def ask_tag_question(message, state, step, user_id):
    if step >= len(TAG_QUESTIONS):
        await finish_registration(message, state, user_id)
        return
    q_data = TAG_QUESTIONS[step]
    kb = tag_question_kb(q_data["tags"], step)
    await message.answer(f"{q_data['question']}\n\nВыбери один вариант:", reply_markup=kb)
    await state.update_data(tag_step=step)

@dp.callback_query(F.data.startswith("tag_"))
async def handle_tag_answer(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    step = int(parts[1])
    tag_idx = int(parts[2])
    data = await state.get_data()
    selected = data.get("selected_tags", {})
    q_data = TAG_QUESTIONS[step]
    tag = q_data["tags"][tag_idx]
    selected[q_data["category"]] = tag
    await state.update_data(selected_tags=selected)
    next_step = step + 1
    if next_step >= len(TAG_QUESTIONS):
        await finish_registration(call.message, state, call.from_user.id)
    else:
        await ask_tag_question(call.message, state, next_step, call.from_user.id)
    await call.answer()

async def finish_registration(message, state, user_id):
    data = await state.get_data()
    selected_tags = data.get("selected_tags", {})
    if len(selected_tags) != len(TAG_QUESTIONS):
        await message.answer("❌ Выбери теги для всех категорий!")
        return
    with SessionLocal() as session_db:
        existing_user = session_db.execute(select(User).where(User.tg_id == user_id)).scalar_one_or_none()
        if existing_user:
            await message.answer("❌ Ты уже зарегистрирован!")
            return
        user = User(tg_id=user_id, username=data["username"], class_name=data["class_name"],
                    age=data["age"], city=data["city"], status="idle")
        session_db.add(user)
        session_db.flush()
        for category, tag in selected_tags.items():
            session_db.add(UserTag(user_id=user.id, category=category, tag=tag))
        session_db.commit()
        print(f"✅ Пользователь сохранён: tg_id={user.tg_id}, username={user.username}")
    await state.clear()
    await message.answer(f"✅ Регистрация завершена! Добро пожаловать, {data['username']}! 🎉",
                         reply_markup=main_menu())

@dp.callback_query(F.data == "cancel")
async def cancel_registration(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Отменено. Напиши /start заново.")
    await call.answer()

# ---------- ПРОФИЛЬ ----------
@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.message.answer("❌ Ты не зарегистрирован!")
            return
        tags = session_db.execute(select(UserTag).where(UserTag.user_id == user.id)).scalars().all()
        tags_text = "\n".join([f"• {t.category}: {t.tag}" for t in tags]) or "Не выбраны"
        await call.message.edit_text(
            PROFILE_TEMPLATE.format(
                username=user.username,
                class_name=f"{CLASS_EMOJI.get(user.class_name.value, '')} {user.class_name.value}",
                level=user.level,
                age=user.age or "Не указан",
                city=user.city or "Не указан",
                tags=tags_text,
                status=STATUS_NAMES.get(user.status, user.status)
            ),
            reply_markup=main_menu()
        )
    await call.answer()

@dp.callback_query(F.data == "edit_profile")
async def edit_profile(call: CallbackQuery):
    await call.message.edit_text("📝 Редактирование:\n/setname Имя\n/setage 25\n/setcity Москва",
                                 reply_markup=main_menu())
    await call.answer()

# ========== МАТЧМЕЙКИНГ ==========
@dp.callback_query(F.data == "find_match")
async def find_match(call: CallbackQuery):
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer("❌ Ты не зарегистрирован!", show_alert=True)
            return
        if user.status in ("dungeon", "matched"):
            await call.answer("⚔️ Ты уже занят!", show_alert=True)
            return

        user.status = "searching"
        session_db.commit()

        candidates = session_db.execute(
            select(User).where(
                User.tg_id != user.tg_id,
                User.status == "searching",
                User.age.between(user.age - 2, user.age + 2)
            )
        ).scalars().all()

        my_tags_raw = session_db.execute(select(UserTag).where(UserTag.user_id == user.id)).scalars().all()
        my_tags = {t.tag for t in my_tags_raw}

        best_match = None
        best_score = 0
        for c in sorted(candidates, key=lambda x: (x.city != user.city,)):
            c_tags_raw = session_db.execute(select(UserTag).where(UserTag.user_id == c.id)).scalars().all()
            c_tags = {t.tag for t in c_tags_raw}
            shared = len(my_tags & c_tags)
            if shared >= 1 and shared > best_score:
                best_score = shared
                best_match = c

        if not best_match:
            await call.message.answer(
                "🔍 **Ищем напарника...**\n\n"
                "Пока никого подходящего нет. Как только кто-то появится — мы сразу пришлём уведомление."
            )
            await call.answer()
            return

        user.status = "matched"
        user.partner_tg_id = best_match.tg_id
        user.is_ready = False
        best_match.status = "matched"
        best_match.partner_tg_id = user.tg_id
        best_match.is_ready = False
        session_db.commit()

        partner_tags = session_db.execute(select(UserTag).where(UserTag.user_id == best_match.id)).scalars().all()
        partner_tags_text = "\n".join([f"• {t.tag}" for t in partner_tags])
        my_tags_text = "\n".join([f"• {t.tag}" for t in my_tags_raw])

        await call.message.answer(
            f"🎉 **Найден напарник!**\n\n"
            f"👤 **{best_match.username}**\n"
            f"{CLASS_EMOJI[best_match.class_name.value]} Класс: {best_match.class_name.value}\n"
            f"🎂 Возраст: {best_match.age}\n"
            f"🏙️ Город: {best_match.city}\n"
            f"🏷️ **Общих тегов: {best_score}**\n{partner_tags_text}\n\n"
            f"Готов отправиться в приключение?",
            reply_markup=ready_kb()
        )

        try:
            await bot.send_message(
                chat_id=best_match.tg_id,
                text=(
                    f"🎉 **Найден напарник!**\n\n"
                    f"👤 **{user.username}**\n"
                    f"{CLASS_EMOJI[user.class_name.value]} Класс: {user.class_name.value}\n"
                    f"🎂 Возраст: {user.age}\n"
                    f"🏙️ Город: {user.city}\n"
                    f"🏷️ **Общих тегов: {best_score}**\n{my_tags_text}\n\n"
                    f"Готов отправиться в приключение?"
                ),
                reply_markup=ready_kb()
            )
        except Exception as e:
            print(f"⚠️ Не смог уведомить {best_match.tg_id}: {e}")

    await call.answer()

# ---------- ГОТОВНОСТЬ И СТАРТ ДАНЖА ----------
@dp.callback_query(F.data == "ready")
async def ready_handler(call: CallbackQuery):
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user or user.status != "matched" or not user.partner_tg_id:
            await call.answer("❌ Нет активного поиска", show_alert=True)
            return

        user.is_ready = True
        session_db.commit()

        partner = session_db.execute(select(User).where(User.tg_id == user.partner_tg_id)).scalar_one_or_none()

        if not partner or not partner.is_ready:
            await call.message.edit_text("⏳ **Ждём напарника...**\n\nКак только он подтвердит готовность — начнётся приключение!")
            await call.answer()
            return

        # Оба готовы — создаём сессию данжа
        user.status = "dungeon"
        partner.status = "dungeon"
        session = DungeonSession(
            player1_tg_id=user.tg_id,
            player2_tg_id=partner.tg_id,
            current_question=0,
            status="active"
        )
        session_db.add(session)
        session_db.commit()

        # Отправляем первый вопрос обоим
        q = DUNGEON_QUESTIONS[0]
        intro = (
            "🌲 **Лес Оборотней**\n\n"
            "Вы вошли в лес, о котором ходят легенды. Говорят, здесь пропадают люди. "
            "Но вы идёте вдвоём — а значит, у вас есть шанс.\n\n"
            "━━━━━━━━━━━━━━━\n"
            f"📍 **Вопрос 1 из {TOTAL_QUESTIONS}**\n\n"
            f"{q['text']}"
        )
        kb = dungeon_kb(0)

        try:
            await call.message.edit_text(intro, reply_markup=kb)
        except Exception:
            await call.message.answer(intro, reply_markup=kb)
        try:
            await bot.send_message(chat_id=partner.tg_id, text=intro, reply_markup=kb)
        except Exception as e:
            print(f"⚠️ {e}")

    await call.answer()

# ---------- ОТВЕТЫ В ДАНЖЕ ----------
@dp.callback_query(F.data.startswith("dq_"))
async def dungeon_answer(call: CallbackQuery):
    parts = call.data.split("_")
    question_idx = int(parts[1])
    answer_idx = int(parts[2])

    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer("❌ Ошибка", show_alert=True)
            return

        session = session_db.execute(
            select(DungeonSession).where(
                DungeonSession.status == "active",
                ((DungeonSession.player1_tg_id == user.tg_id) | (DungeonSession.player2_tg_id == user.tg_id))
            )
        ).scalars().first()

        if not session:
            await call.answer("❌ Сессия не найдена", show_alert=True)
            return

        if session.current_question != question_idx:
            await call.answer("⏳ Уже идёт следующий вопрос", show_alert=True)
            return

        # Сохраняем ответ
        if session.player1_tg_id == user.tg_id:
            if session.player1_ready:
                await call.answer("✅ Ты уже ответил", show_alert=True)
                return
            session.player1_answer = answer_idx
            session.player1_ready = True
        else:
            if session.player2_ready:
                await call.answer("✅ Ты уже ответил", show_alert=True)
                return
            session.player2_answer = answer_idx
            session.player2_ready = True

        session_db.commit()

        # Меняем сообщение у того, кто ответил
        q = DUNGEON_QUESTIONS[question_idx]
        await call.message.edit_text(
            f"✅ Твой выбор: **{q['options'][answer_idx]['text']}**\n\n"
            f"⏳ Ждём напарника..."
        )
        await call.answer("Ответ сохранён!")

        # Если оба ответили — обрабатываем
        if session.player1_ready and session.player2_ready:
            await process_question_result(session_db, session, question_idx)

async def process_question_result(session_db, session, question_idx):
    q = DUNGEON_QUESTIONS[question_idx]
    p1_ans = session.player1_answer
    p2_ans = session.player2_answer

    same = (p1_ans == p2_ans)
    p1_soft = q["options"][p1_ans]["soft"]
    p2_soft = q["options"][p2_ans]["soft"]

    # Определяем тип
    if same:
        bridge = q["bridges"]["same"]
        session.matches_count += 1
        kind = "same"
    elif p1_soft and p2_soft:
        bridge = q["bridges"]["soft"]
        session.soft_count += 1
        kind = "soft"
    else:
        bridge = q["bridges"]["mixed"]
        session.mixed_count += 1
        kind = "mixed"

    session.player1_ready = False
    session.player2_ready = False
    session.current_question += 1
    session.player1_answer = None
    session.player2_answer = None
    session_db.commit()

    # ОДИН И ТОТ ЖЕ текст обоим — они не знают, что произошло
    next_step = session.current_question

    if next_step >= TOTAL_QUESTIONS:
        # Данж закончен
        await finish_dungeon(session_db, session)
        return

    # Отправляем мостик + следующий вопрос ОБОИМ
    next_q = DUNGEON_QUESTIONS[next_step]
    next_text = (
        f"{bridge}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 **Вопрос {next_step + 1} из {TOTAL_QUESTIONS}**\n\n"
        f"{next_q['text']}"
    )
    next_kb = dungeon_kb(next_step)

    try:
        await bot.send_message(chat_id=session.player1_tg_id, text=next_text, reply_markup=next_kb)
    except Exception as e:
        print(f"⚠️ {e}")
    try:
        await bot.send_message(chat_id=session.player2_tg_id, text=next_text, reply_markup=next_kb)
    except Exception as e:
        print(f"⚠️ {e}")

async def finish_dungeon(session_db, session):
    session.status = "finished"
    matches = session.matches_count
    softs = session.soft_count
    mixed = session.mixed_count
    total = TOTAL_QUESTIONS

    # Сбрасываем статусы пользователей
    p1 = session_db.execute(select(User).where(User.tg_id == session.player1_tg_id)).scalar_one_or_none()
    p2 = session_db.execute(select(User).where(User.tg_id == session.player2_tg_id)).scalar_one_or_none()

    exp_gain = matches * 10 + softs * 5

    if p1:
        p1.status = "idle"
        p1.partner_tg_id = None
        p1.is_ready = False
        p1.experience = (p1.experience or 0) + exp_gain
    if p2:
        p2.status = "idle"
        p2.partner_tg_id = None
        p2.is_ready = False
        p2.experience = (p2.experience or 0) + exp_gain
    session_db.commit()

    # Процент = (совпадения + soft*0.5) / всего * 100
    effective = matches + softs * 0.5
    percent = int(effective / total * 100)

    # Вердикт
    if percent >= 90:
        verdict = (
            "✨ **Идеальный резонанс!**\n\n"
            "Вы словно одна душа в двух телах. Такое встречается редко — не упустите друг друга."
        )
    elif percent >= 70:
        verdict = (
            "💫 **Сильный синхрон!**\n\n"
            "У вас много общего. Это отличная основа для настоящего знакомства."
        )
    elif percent >= 40:
        verdict = (
            "🤔 **Есть точки соприкосновения.**\n\n"
            "Вы разные — но в этом и интерес. Есть о чём поговорить и чему удивиться."
        )
    else:
        verdict = (
            "💎 **Вы настолько неповторимы, что найти похожего — почти невозможно.**\n\n"
            "Это как раз тот случай. Может быть, именно поэтому вам стоит узнать друг друга поближе?"
        )

    # Контакты (только если >= 40%)
    if percent >= 40 and p1 and p2:
        contacts = (
            f"\n\n📞 **Держите связь:**\n"
            f"• {p1.username}\n"
            f"• {p2.username}\n\n"
            f"Напишите друг другу, не теряйтесь!"
        )
    else:
        contacts = "\n\n💭 Если захотите — попробуйте пройти другой данж вместе."

    final_text = (
        f"🏁 **Данж завершён!**\n\n"
        f"💫 Синхрон: **{percent}%**\n"
        f"✅ Совпадений: **{matches}**\n"
        f"🤝 Единство по духу: **{softs}**\n"
        f"⚔️ Компромиссов: **{mixed}**\n\n"
        f"{verdict}"
        f"{contacts}"
    )

    try:
        await bot.send_message(chat_id=session.player1_tg_id, text=final_text, reply_markup=main_menu())
    except Exception as e:
        print(f"⚠️ {e}")
    try:
        await bot.send_message(chat_id=session.player2_tg_id, text=final_text, reply_markup=main_menu())
    except Exception as e:
        print(f"⚠️ {e}")

# ---------- ОТМЕНА МАТЧА ----------
@dp.callback_query(F.data == "cancel_match")
async def cancel_match(call: CallbackQuery):
    with SessionLocal() as session_db:
        user = session_db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer()
            return

        partner_tg_id = user.partner_tg_id
        user.status = "idle"
        user.partner_tg_id = None
        user.is_ready = False

        if partner_tg_id:
            partner = session_db.execute(select(User).where(User.tg_id == partner_tg_id)).scalar_one_or_none()
            if partner:
                partner.status = "idle"
                partner.partner_tg_id = None
                partner.is_ready = False

        session_db.commit()

        await call.message.edit_text("❌ Поиск отменён. Можешь попробовать снова.")
        await call.answer()

        if partner_tg_id:
            try:
                await bot.send_message(chat_id=partner_tg_id,
                                       text="❌ Напарник отменил поиск. Ты снова свободен.")
            except Exception:
                pass

# ---------- РЕДАКТИРОВАНИЕ ----------
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
    print("✅ База данных готова!")
    print("🚀 Бот 'Рейд Сердец' запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
