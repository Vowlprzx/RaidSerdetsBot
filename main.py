# -*- coding: utf-8 -*-
import asyncio
import logging
import random
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
    RYTSAR = "Рыцарь"; TEMNYI_STRAZH = "Тёмный Страж"; VARVAR = "Варвар"
    VOLSHEBNIK = "Волшебник"; INZHENER = "Инженер"; BARD = "Бард"
    TEN = "Тень"; SLEDOPYT = "Следопыт"; ZHRETS = "Жрец"; DRUID = "Друид"

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
    key_text = Column(String(200), default="")  # КЛЮЧ
    status = Column(String(20), default="idle")
    partner_tg_id = Column(BigInteger, nullable=True)
    is_ready = Column(Boolean, default=False)
    early_exits = Column(Integer, default=0)
    full_dungeons = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

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
    theme_key = Column(String(30), default="forest")
    current_phase = Column(Integer, default=1)  # 1, 2, 3
    current_question = Column(Integer, default=0)
    player1_answer = Column(Integer, nullable=True)
    player2_answer = Column(Integer, nullable=True)
    player1_ready = Column(Boolean, default=False)
    player2_ready = Column(Boolean, default=False)
    phase1_matches = Column(Integer, default=0)
    phase2_matches = Column(Integer, default=0)
    phase3_matches = Column(Integer, default=0)
    msg_stage = Column(Integer, default=0)  # 0 = никто, 1 = один, 2 = оба
    player1_msg = Column(String(200), nullable=True)
    player2_msg = Column(String(200), nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(engine)
# На ОДИН запуск (после изменения схемы):
# Base.metadata.drop_all(engine)
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

def continue_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Продолжить", callback_data="dungeon_continue")],
        [InlineKeyboardButton(text="❌ Выйти", callback_data="dungeon_exit")]
    ])

def confirm_exit_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, выйти", callback_data="dungeon_exit_confirm")],
        [InlineKeyboardButton(text="↩️ Нет, продолжить", callback_data="dungeon_exit_cancel")]
    ])

def dungeon_answer_kb(theme_key, phase_idx, q_idx):
    q = DUNGEONS[theme_key]["phases"][phase_idx]["questions"][q_idx]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt["text"], callback_data=f"da_{theme_key}_{phase_idx}_{q_idx}_{i}")]
        for i, opt in enumerate(q["options"])
    ])

# ========== ТЕГИ (без изменений) ==========
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

# ========== ДАННЫЕ ТЕМ ==========
# В каждой теме — 3 фазы. Фаза 1: 3 вопроса, Фаза 2: 4, Фаза 3: 4.

FOREST = {
    "name": "🌲 Лес оборотней",
    "phases": [
        {"name": "🏰 Таверна «Мрачные Врата»", "questions": [
            {"text": "🌲 Вы входите в таверну на краю леса. За столом сидит охотник. Он смотрит на вас и улыбается.",
             "options": [{"text": "Подойду и заговорю первым", "soft": False},
                         {"text": "Сяду в стороне и понаблюдаю", "soft": True},
                         {"text": "Спрошу у трактирщика, кто это", "soft": True}],
             "bridges": {"same": "Охотник поднимает кружку и кивает вам. Трактирщик молча ставит перед вами две тарелки.",
                         "soft": "Свечи догорают. Охотник встаёт и подходит к вашему столу — без приглашения.",
                         "mixed": "Трактирщик гасит свет. Охотник остаётся сидеть. Его тень дрожит на стене."}},
            {"text": "🍺 Охотник предлагает выпить с ним и рассказывает о проклятии леса. Что делаете?",
             "options": [{"text": "Выпью и выслушаю до конца", "soft": True},
                         {"text": "Откажусь от выпивки, но слушаю", "soft": False},
                         {"text": "Задам ему прямой вопрос: «Ты кто такой?»", "soft": False}],
             "bridges": {"same": "Он досказывает историю. Последние слова — про женщину, которая исчезла здесь три года назад.",
                         "soft": "Он замолкает и смотрит в окно. За стеклом — лес. И что-то светится между деревьями.",
                         "mixed": "Он резко встаёт и идёт к выходу. У двери оборачивается: «Утром пойдём. Не задерживайся»."}},
            {"text": "🌙 Ночью вы просыпаетесь от воя. Охотник стоит у окна и смотрит на луну. Что делаете?",
             "options": [{"text": "Подойду и спрошу, всё ли в порядке", "soft": True},
                         {"text": "Притворюсь спящим и буду наблюдать", "soft": True},
                         {"text": "Тихо возьму оружие", "soft": False}],
             "bridges": {"same": "Он оборачивается. Его глаза в темноте кажутся жёлтыми. Но он просто улыбается: «Пора».",
                         "soft": "Вой стихает. Утром вы находите его у дверей — с рюкзаком и двумя факелами.",
                         "mixed": "Ночь прошла без сна. Охотник ждёт вас на крыльце. Молча."}}
        ]},
        {"name": "🌲 Мрачная глушь", "questions": [
            {"text": "🌲 Тропа раздваивается: одна — освещённая, но длинная. Другая — тёмная, но короткая.",
             "options": [{"text": "Пойду по светлой — не хочу рисковать", "soft": True},
                         {"text": "Пойду по тёмной — быстрее дойдём", "soft": False},
                         {"text": "Спрошу у охотника, какой путь он выберет", "soft": True}],
             "bridges": {"same": "Тропа выводит к ручью. Вода чёрная, но чистая. Охотник набирает её в флягу.",
                         "soft": "Лес расступается. Впереди — поляна. На ней что-то лежит.",
                         "mixed": "Вы выходите к ручью. Охотник оглядывается: «Кто-то шёл за нами»."}},
            {"text": "🐺 На вас вышел раненый волк. Он не нападает — просто смотрит.",
             "options": [{"text": "Помогу — вдруг он не опасен", "soft": True},
                         {"text": "Обойду стороной", "soft": True},
                         {"text": "Добью — нельзя оставлять за спиной", "soft": False}],
             "bridges": {"same": "Волк уходит в чащу. Охотник смотрит ему вслед и говорит: «Он вернётся».",
                         "soft": "На снегу остаётся кровавый след. Охотник идёт по нему, не оборачиваясь.",
                         "mixed": "Тишина. Охотник достаёт нож и режет метку на дереве: «Здесь мы были»."}},
            {"text": "🏚️ Вы нашли заброшенную хижину. Внутри тепло — кто-то был здесь недавно.",
             "options": [{"text": "Останусь и подожду хозяина", "soft": True},
                         {"text": "Обыщу и уйду", "soft": False},
                         {"text": "Закрою дверь и пойду дальше", "soft": True}],
             "bridges": {"same": "В углу — детская игрушка. Охотник берёт её в руки. Молчит.",
                         "soft": "На столе — карта. Охотник сворачивает её и убирает в карман.",
                         "mixed": "Он бросает спичку в очаг. Огонь вспыхивает и гаснет. «Идём»."}},
            {"text": "👤 Из темноты выходит старик. Он говорит: «Не ходите дальше. Там — смерть».",
             "options": [{"text": "Поблагодарю и поверну назад", "soft": True},
                         {"text": "Пойду дальше — я не верю ему", "soft": False},
                         {"text": "Спрошу, откуда он знает", "soft": False}],
             "bridges": {"same": "Старик смотрит на охотника. Долго. Потом уходит в туман.",
                         "soft": "Охотник говорит: «Он врёт. Всегда врёт». Но голос у него дрожит.",
                         "mixed": "Старик хрипит: «Ты привёл их сюда». Охотник молчит."}}
        ]},
        {"name": "🐺 Жилище оборотня", "questions": [
            {"text": "🌕 Вы вышли к поляне. На ней стоит охотник. Он больше не улыбается. Его глаза светятся жёлтым.",
             "options": [{"text": "Атакую первым", "soft": False},
                         {"text": "Спрошу, что он хочет", "soft": True},
                         {"text": "Притворюсь, что не заметил", "soft": True}],
             "bridges": {"same": "Он снимает плащ. Под ним — шрамы. Много. «Теперь ты знаешь».",
                         "soft": "Он говорит: «Я не трону вас. Мне нужна помощь».",
                         "mixed": "Он опускается на колени. Земля под ним трескается."}},
            {"text": "🐺 Оборотень говорит: «Я помогу вам. Но вы должны сохранить мою тайну».",
             "options": [{"text": "Соглашусь — он помог нам", "soft": True},
                         {"text": "Откажусь — нельзя доверять монстру", "soft": False},
                         {"text": "Соглашусь, но решу потом", "soft": False}],
             "bridges": {"same": "Он встаёт и идёт вперёд. Деревья расступаются перед ним.",
                         "soft": "Он говорит: «Спасибо». Впервые за всё время — искренне.",
                         "mixed": "Он замирает. «Если соврёшь — я найду тебя»."}},
            {"text": "🌿 Оборотень говорит: «Есть способ снять проклятие. Но цветок, который нужен, растёт только в логове того, кто меня проклял. Я не могу идти туда один».",
             "options": [{"text": "Помогу — он заслужил шанс", "soft": True},
                         {"text": "Откажусь — это слишком опасно", "soft": False},
                         {"text": "Спрошу, что он даст взамен", "soft": False}],
             "bridges": {"same": "Вы идёте к логову. Чем ближе, тем темнее лес. Оборотень молчит.",
                         "soft": "Он ведёт вас потайной тропой. Через час вы видите вход в пещеру. Из неё тянет холодом.",
                         "mixed": "Он говорит: «Я подожду здесь». И садится на камень. Ждёт."}},
            {"text": "🏡 Вы вернулись в деревню. Жители собрались на площади. Оборотень стоит рядом. Они не знают, кто он.",
             "options": [{"text": "Скажу правду — пусть решают", "soft": False},
                         {"text": "Совру, чтобы защитить оборотня", "soft": True},
                         {"text": "Уйду молча — это не моё дело", "soft": True}],
             "bridges": {"same": "Толпа молчит. Оборотень кладёт руку вам на плечо и уходит в лес.",
                         "soft": "Староста кивает. Ворота закрываются за вашими спинами.",
                         "mixed": "Никто не двигается. Только ветер гонит пыль по площади."}}
        ]}
    ]
}

BAY = {
    "name": "⚓ Бухта призрачных кораблей",
    "phases": [
        {"name": "🌊 Покинутый берег", "questions": [
            {"text": "🌫️ Вы выходите на берег. Туман стоит стеной. Вдали — силуэты кораблей.",
             "options": [{"text": "Пойду вдоль берега — надо осмотреться", "soft": True},
                         {"text": "Сразу пойду к кораблям — нельзя терять время", "soft": False},
                         {"text": "Останусь здесь до рассвета — ночью опасно", "soft": True}],
             "bridges": {"same": "Волны выбрасывают на берег обломок мачты. На нём — вырезанное имя.",
                         "soft": "Туман сгущается. Между кораблями мелькает огонёк — и гаснет.",
                         "mixed": "Из воды выходит фигура. Она не смотрит на вас. Она идёт к кораблям."}},
            {"text": "🕯️ На берегу — старый фонарь. Он горит, хотя вокруг ни души.",
             "options": [{"text": "Возьму его — свет пригодится", "soft": False},
                         {"text": "Оставлю — кто-то его зажёг, значит, вернётся", "soft": True},
                         {"text": "Затушу — не хочу, чтобы меня заметили", "soft": False}],
             "bridges": {"same": "Фонарь гаснет. В темноте остаётся только шум прибоя.",
                         "soft": "Из тумана выходят двое. Они молчат. И ждут.",
                         "mixed": "Кто-то окликает вас по имени. Но никого не видно."}},
            {"text": "👤 Из тумана выходит старик. Он говорит: «Не ходите туда. Они забирают всех».",
             "options": [{"text": "Спрошу, кто «они»", "soft": False},
                         {"text": "Поблагодарю и пойду дальше", "soft": True},
                         {"text": "Предложу ему пойти с нами", "soft": True}],
             "bridges": {"same": "Старик показывает на корабли и исчезает. Туман смыкается.",
                         "soft": "Он даёт вам амулет и уходит. Не оборачиваясь.",
                         "mixed": "Он смеётся. «Все так говорят». И растворяется."}}
        ]},
        {"name": "🪝 Обломки кораблей", "questions": [
            {"text": "⚓ Вы подошли к первому кораблю. Палуба цела. На ней — свежие следы.",
             "options": [{"text": "Поднимусь на палубу", "soft": False},
                         {"text": "Обойду корабль по кругу", "soft": True},
                         {"text": "Окликну — вдруг кто-то есть", "soft": False}],
             "bridges": {"same": "На палубе — карта. На ней отмечен главный корабль. Крестик.",
                         "soft": "Следы ведут к люку. Он приоткрыт. Из него тянет холодом.",
                         "mixed": "Из трюма доносится пение. Женский голос. Тихий."}},
            {"text": "📜 В каюте вы нашли судовой журнал. Последняя запись: «Он среди нас».",
             "options": [{"text": "Прочитаю журнал с начала", "soft": False},
                         {"text": "Закрою и уйду", "soft": True},
                         {"text": "Покажу напарнику — вдвоём решим", "soft": True}],
             "bridges": {"same": "Журнал рассыпается в руках. Остаётся только одна страница. С именем.",
                         "soft": "Свеча догорает. В темноте кто-то шепчет.",
                         "mixed": "Дверь каюты закрывается сама. Вы остаётесь вдвоём."}},
            {"text": "🔔 Где-то в трюме звенит колокол. Он звонит сам по себе.",
             "options": [{"text": "Спущусь в трюм", "soft": False},
                         {"text": "Останусь на палубе", "soft": True},
                         {"text": "Позову напарника и спустимся вместе", "soft": True}],
             "bridges": {"same": "Колокол стихает. Из трюма выходит человек. Он смотрит на вас.",
                         "soft": "Звон прекращается. На палубе появляется фигура в мундире.",
                         "mixed": "Колокол падает. Тишина. Все корабли вокруг — как один."}},
            {"text": "🕳️ Перед вами — люк. Из него тянет холодом. Напарник предлагает спуститься.",
             "options": [{"text": "Пойду первым", "soft": False},
                         {"text": "Пусть он идёт первым", "soft": False},
                         {"text": "Спустимся вместе", "soft": True}],
             "bridges": {"same": "Внизу — коридор. В конце — свет. И голоса.",
                         "soft": "Ступени ведут вниз. Чем глубже — тем светлее.",
                         "mixed": "Люк закрывается. Темнота. Только дыхание рядом."}}
        ]},
        {"name": "👻 Корабль адмирала призраков", "questions": [
            {"text": "🌑 На палубе — фигура в адмиральском мундире. Она не двигается. И не дышит.",
             "options": [{"text": "Подойду и заговорю", "soft": False},
                         {"text": "Останусь на месте и подожду", "soft": True},
                         {"text": "Достану оружие", "soft": False}],
             "bridges": {"same": "Адмирал поднимает голову. Его глаза — как две чёрные дыры.",
                         "soft": "Он говорит: «Я ждал вас. Долго ждал».",
                         "mixed": "Палуба наклоняется. Корабль медленно идёт ко дну."}},
            {"text": "💀 Адмирал говорит: «Отдайте мне одно имя — и я отпущу вас живыми».",
             "options": [{"text": "Отдам своё имя", "soft": True},
                         {"text": "Откажусь — имя — это я", "soft": False},
                         {"text": "Спрошу, зачем ему имя", "soft": False}],
             "bridges": {"same": "Адмирал кивает. «Хорошо». Море вокруг стихает.",
                         "soft": "Он улыбается. Впервые за сотни лет. «Свободны».",
                         "mixed": "Он поднимает руку. Вода вокруг корабля закипает."}},
            {"text": "🌊 Корабль тонет. Одна шлюпка — на двоих.",
             "options": [{"text": "Уступлю место напарнику", "soft": True},
                         {"text": "Первым прыгну в шлюпку", "soft": False},
                         {"text": "Будем грести по очереди", "soft": True}],
             "bridges": {"same": "Шлюпка отходит. Корабль уходит под воду. На его месте — тишина.",
                         "soft": "Берег близко. Туман расступается.",
                         "mixed": "Вода холодная. Вы гребёте молча. Никто не оглядывается."}},
            {"text": "🏝️ Вы выбрались на берег. Позади — ничего. Только туман.",
             "options": [{"text": "Возьму напарника за плечо — молча", "soft": True},
                         {"text": "Отойду на пару шагов — подышать", "soft": False},
                         {"text": "Сяду прямо на песок — ноги гудят", "soft": True}],
             "bridges": {"same": "Солнце встаёт. Море спокойно. Кораблей больше нет.",
                         "soft": "Вы сидите на песке. Рядом — амулет старика. Он тёплый.",
                         "mixed": "Рассвет. Волны лижут берег. Каждый думает о своём."}}
        ]}
    ]
}

DESERT = {
    "name": "🏜️ Пустыня оставленных надежд",
    "phases": [
        {"name": "🌴 Оазис надежды", "questions": [
            {"text": "🌴 Вы вышли к оазису. У источника сидит человек. Он не двигается.",
             "options": [{"text": "Подойду и спрошу, всё ли в порядке", "soft": True},
                         {"text": "Наберу воды и пойду дальше", "soft": False},
                         {"text": "Сяду рядом и подожду, что он скажет", "soft": True}],
             "bridges": {"same": "Он поднимает голову. «Вы первые, кто подошёл». Голос хриплый.",
                         "soft": "Он протягивает вам флягу. В ней — вода. Чистая. Он отдаёт её без слов.",
                         "mixed": "Он встаёт и уходит в пустыню. Не оглядываясь."}},
            {"text": "🥖 У него есть еда — но только на одного. Он предлагает её вам.",
             "options": [{"text": "Откажусь — он выглядит хуже нас", "soft": True},
                         {"text": "Возьму — нам нужно выжить", "soft": False},
                         {"text": "Разделю на всех", "soft": True}],
             "bridges": {"same": "Он кивает. «Дальше — дюны. Там нет ничего. Будьте осторожны».",
                         "soft": "Он рассказывает, что раньше здесь был город. Теперь — только песок.",
                         "mixed": "Он говорит: «Вы ещё вернётесь». Смеётся и кашляет."}},
            {"text": "💧 Он просит: «Возьмите меня с собой. Я не дойду один».",
             "options": [{"text": "Возьму — не могу бросить", "soft": True},
                         {"text": "Откажу — он замедлит нас", "soft": False},
                         {"text": "Спрошу напарника, что он думает", "soft": True}],
             "bridges": {"same": "Он идёт рядом. Медленно. Но идёт.",
                         "soft": "Он остаётся у оазиса. «Идите. Я догоню». Но вы знаете, что не догонит.",
                         "mixed": "Он смотрит вам вслед. Долго. Потом садится обратно к воде."}}
        ]},
        {"name": "🔥 Жестокие дюны", "questions": [
            {"text": "🔥 Солнце в зените. Впереди — караван. Они машут вам. Но у вас только одна фляга.",
             "options": [{"text": "Подойду — может, у них есть вода", "soft": True},
                         {"text": "Обойду — у них могут быть плохие намерения", "soft": False},
                         {"text": "Подойду, но оружие наготове", "soft": False}],
             "bridges": {"same": "Караванщики дают вам воду. Бесплатно. «Здесь так принято».",
                         "soft": "Они смотрят на вас и молчат. Потом один говорит: «Идите на север. Там храм».",
                         "mixed": "Они уходят. Один оборачивается: «Не ходите к храму. Он забирает всех»."}},
            {"text": "👤 В песке лежит человек. Он без сознания. У вас осталось полфляги воды.",
             "options": [{"text": "Отдам ему всю воду", "soft": True},
                         {"text": "Пройду мимо — нам самим не хватит", "soft": False},
                         {"text": "Смочу ему губы и пойду дальше", "soft": True}],
             "bridges": {"same": "Он приходит в себя. «Идите к храму. Там — ответы».",
                         "soft": "Он не просыпается. Вы идёте дальше. Песок заметает следы.",
                         "mixed": "Он бормочет что-то. Вы не разбираете слов. Только одно: «Не ходи»."}},
            {"text": "🐍 На вас ползёт змея. Она не ядовита, но голодна.",
             "options": [{"text": "Отдам еду — она тоже хочет жить", "soft": True},
                         {"text": "Прогоню — нам нужнее", "soft": False},
                         {"text": "Убью — она опасна", "soft": False}],
             "bridges": {"same": "Змея уползает. В песке остаётся след. Он ведёт к храму.",
                         "soft": "Она хватает еду и исчезает. Вы идёте дальше голодными.",
                         "mixed": "Она сворачивается клубком. Смотрит на вас. Не уходит."}},
            {"text": "⚱️ Вы нашли колодец. Вода есть. Напарник предлагает спуститься.",
             "options": [{"text": "Спущусь первым", "soft": False},
                         {"text": "Пусть он спустится — я подожду", "soft": False},
                         {"text": "Спустимся вместе", "soft": True}],
             "bridges": {"same": "На дне — монеты. Много. Кто-то бросал их сюда годами.",
                         "soft": "Вода холодная. Вы пьёте впервые за день. На дне — ничего.",
                         "mixed": "Верёвка обрывается. Вы выбираетесь по стенам. Колодец остаётся позади."}}
        ]},
        {"name": "🏛️ Утонувший в песках храм", "questions": [
            {"text": "🏛️ Вы вышли к храму. Он наполовину ушёл в песок. Из входа тянет холодом.",
             "options": [{"text": "Войду сразу", "soft": False},
                         {"text": "Обойду храм — может, есть другой вход", "soft": True},
                         {"text": "Сяду и подожду до утра", "soft": True}],
             "bridges": {"same": "Внутри — темнота. Факелы горят сами. Как будто ждали вас.",
                         "soft": "Вы находите боковой вход. Он ведёт вниз. Глубже, чем главный.",
                         "mixed": "Ночь прошла. Утром храм выглядит иначе. Больше. Страшнее."}},
            {"text": "👑 В главном зале — статуя. Женщина с чашей. Надпись: «Отдай — и получишь».",
             "options": [{"text": "Брошу монету — на удачу", "soft": True},
                         {"text": "Ничего не буду бросать — это суеверие", "soft": False},
                         {"text": "Спрошу напарника, что он думает", "soft": True}],
             "bridges": {"same": "Монета падает на дно. Чаша наполняется водой. Сама. Вы пьёте — вода холодная и чистая.",
                         "soft": "Статуя поворачивает голову. Медленно. Смотрит на вас. Из чаши поднимается дым.",
                         "mixed": "Из чаши поднимается дым. Он собирается в фигуру. Фигура молчит."}},
            {"text": "💀 Фигура говорит: «Один из вас должен остаться. Иначе храм не отпустит». Стены начинают дрожать.",
             "options": [{"text": "Останусь я", "soft": True},
                         {"text": "Пусть останется напарник", "soft": False},
                         {"text": "Откажусь — мы уйдём вместе", "soft": True}],
             "bridges": {"same": "Фигура кивает. «Так и будет». Пол трескается. Вы бежите к выходу.",
                         "soft": "Она улыбается. «Ты выбрал. Теперь иди». Камни падают за спиной.",
                         "mixed": "Она поднимает руку. Храм рушится. Вы выбегаете в последний момент."}},
            {"text": "🌅 Вы вышли из храма. Позади — тишина. Впереди — пустыня. И рассвет.",
             "options": [{"text": "Возьму напарника за плечо — молча", "soft": True},
                         {"text": "Отойду на пару шагов — подышать", "soft": False},
                         {"text": "Сяду прямо на песок — ноги гудят", "soft": True}],
             "bridges": {"same": "Солнце встаёт. Пески золотые. Вы идёте на восток.",
                         "soft": "Храм за спиной оседает. На его месте — ровный песок.",
                         "mixed": "Вы идёте молча. Каждый — своей дорогой. Но рядом."}}
        ]}
    ]
}

DUNGEONS = {"forest": FOREST, "bay": BAY, "desert": DESERT}

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
🔑 **Ключ:** {key_text}
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

STATUS_NAMES = {"idle": "🟢 Свободен", "searching": "🟡 В поиске", "matched": "🔵 Нашёл пару",
                "dungeon": "🔴 В приключении", "waiting_msg": "💬 В обмене сообщениями"}

# ========== СОСТОЯНИЯ ==========
class RegForm(StatesGroup):
    username = State(); age = State(); city = State(); key_text = State(); tag_step = State()

# ========== БОТ ==========
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
dp = Dispatcher()

# ---------- /start ----------
@dp.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
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
    step = int(call.data.split("_")[1]); idx = int(call.data.split("_")[2])
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
    await state.update_data(class_name=class_map.get(class_name, UserClass.RYTSAR))
    await message.edit_text(f"🎉 Ты — **{CLASS_EMOJI[class_name]} {class_name}**!\n\n{CLASS_DESCRIPTIONS.get(class_name, '')}\n\nТеперь заполни анкету.")
    await message.answer("📝 Введи **никнейм** (2–30 символов):", reply_markup=cancel_kb())
    await state.set_state(RegForm.username)

# ---------- АНКЕТА ----------
@dp.message(RegForm.username)
async def set_username(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if len(name) < 2 or len(name) > 30:
        await msg.answer("❌ Никнейм должен быть 2–30 символов."); return
    with SessionLocal() as db:
        if db.execute(select(User).where(User.username == name)).scalar_one_or_none():
            await msg.answer("❌ Этот никнейм занят."); return
    await state.update_data(username=name)
    await msg.answer("🎂 Сколько тебе лет? (16–99)", reply_markup=cancel_kb())
    await state.set_state(RegForm.age)

@dp.message(RegForm.age)
async def set_age(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❌ Введи число."); return
    age = int(msg.text)
    if age < 16 or age > 99:
        await msg.answer("❌ Возраст от 16 до 99."); return
    await state.update_data(age=age)
    await msg.answer("🏙️ Из какого ты города?", reply_markup=cancel_kb())
    await state.set_state(RegForm.city)

@dp.message(RegForm.city)
async def set_city(msg: Message, state: FSMContext):
    await state.update_data(city=msg.text.strip())
    await msg.answer(
        "🔑 **Ключ** — это то, что ты хочешь сказать о себе другим. Коротко, до 100 символов.\n\n"
        "Пример: *«М/25, ищу того, с кем можно обсудить аниме и поиграть в D&D»*\n\n"
        "Показывается напарнику **только после 1-й фазы данжа**. Это твой шанс заинтриговать.",
        reply_markup=cancel_kb()
    )
    await state.set_state(RegForm.key_text)

@dp.message(RegForm.key_text)
async def set_key(msg: Message, state: FSMContext):
    key = msg.text.strip()
    if len(key) < 5 or len(key) > 100:
        await msg.answer("❌ Ключ должен быть от 5 до 100 символов. Попробуй снова:"); return
    await state.update_data(key_text=key)
    await state.update_data(selected_tags={})
    await state.set_state(RegForm.tag_step)
    await ask_tag_question(msg, state, 0, msg.from_user.id)

# ---------- КВИЗ ПО ТЕГАМ ----------
async def ask_tag_question(message, state, step, user_id):
    if step >= len(TAG_QUESTIONS):
        await finish_registration(message, state, user_id); return
    q_data = TAG_QUESTIONS[step]
    kb = tag_question_kb(q_data["tags"], step)
    await message.answer(f"{q_data['question']}\n\nВыбери один вариант:", reply_markup=kb)
    await state.update_data(tag_step=step)

@dp.callback_query(F.data.startswith("tag_"))
async def handle_tag_answer(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    step = int(parts[1]); tag_idx = int(parts[2])
    data = await state.get_data()
    selected = data.get("selected_tags", {})
    q_data = TAG_QUESTIONS[step]
    selected[q_data["category"]] = q_data["tags"][tag_idx]
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
        await message.answer("❌ Выбери теги для всех категорий!"); return
    with SessionLocal() as db:
        if db.execute(select(User).where(User.tg_id == user_id)).scalar_one_or_none():
            await message.answer("❌ Ты уже зарегистрирован!"); return
        user = User(tg_id=user_id, username=data["username"], class_name=data["class_name"],
                    age=data["age"], city=data["city"], key_text=data["key_text"], status="idle")
        db.add(user); db.flush()
        for category, tag in selected_tags.items():
            db.add(UserTag(user_id=user.id, category=category, tag=tag))
        db.commit()
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
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.message.answer("❌ Ты не зарегистрирован!"); return
        tags = db.execute(select(UserTag).where(UserTag.user_id == user.id)).scalars().all()
        tags_text = "\n".join([f"• {t.category}: {t.tag}" for t in tags]) or "Не выбраны"
        await call.message.edit_text(
            PROFILE_TEMPLATE.format(
                username=user.username,
                class_name=f"{CLASS_EMOJI.get(user.class_name.value, '')} {user.class_name.value}",
                level=user.level, age=user.age or "Не указан", city=user.city or "Не указан",
                key_text=user.key_text or "Не указан",
                tags=tags_text, status=STATUS_NAMES.get(user.status, user.status)
            ), reply_markup=main_menu()
        )
    await call.answer()

@dp.callback_query(F.data == "edit_profile")
async def edit_profile(call: CallbackQuery):
    await call.message.edit_text("📝 Редактирование:\n/setname Имя\n/setage 25\n/setcity Москва\n/setkey Твой ключ",
                                 reply_markup=main_menu())
    await call.answer()

# ---------- МАТЧМЕЙКИНГ ----------
@dp.callback_query(F.data == "find_match")
async def find_match(call: CallbackQuery):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer("❌ Ты не зарегистрирован!", show_alert=True); return
        if user.status in ("dungeon", "matched", "waiting_msg"):
            await call.answer("⚔️ Ты уже занят!", show_alert=True); return
        user.status = "searching"; db.commit()
        candidates = db.execute(select(User).where(
            User.tg_id != user.tg_id, User.status == "searching",
            User.age.between(user.age - 2, user.age + 2)
        )).scalars().all()
        my_tags_raw = db.execute(select(UserTag).where(UserTag.user_id == user.id)).scalars().all()
        my_tags = {t.tag for t in my_tags_raw}
        best_match = None; best_score = 0
        for c in sorted(candidates, key=lambda x: (x.city != user.city,)):
            c_tags_raw = db.execute(select(UserTag).where(UserTag.user_id == c.id)).scalars().all()
            c_tags = {t.tag for t in c_tags_raw}
            shared = len(my_tags & c_tags)
            if shared >= 1 and shared > best_score:
                best_score = shared; best_match = c
        if not best_match:
            await call.message.answer("🔍 **Ищем напарника...**\n\nПока никого подходящего нет. Как только кто-то появится — мы сразу пришлём уведомление.")
            await call.answer(); return
        user.status = "matched"; user.partner_tg_id = best_match.tg_id; user.is_ready = False
        best_match.status = "matched"; best_match.partner_tg_id = user.tg_id; best_match.is_ready = False
        db.commit()
        partner_tags = db.execute(select(UserTag).where(UserTag.user_id == best_match.id)).scalars().all()
        partner_tags_text = "\n".join([f"• {t.tag}" for t in partner_tags])
        my_tags_text = "\n".join([f"• {t.tag}" for t in my_tags_raw])
        await call.message.answer(
            f"🎉 **Найден напарник!**\n\n👤 **{best_match.username}**\n"
            f"{CLASS_EMOJI[best_match.class_name.value]} Класс: {best_match.class_name.value}\n"
            f"🎂 Возраст: {best_match.age}\n🏙️ Город: {best_match.city}\n"
            f"🏷️ **Общих тегов: {best_score}**\n{partner_tags_text}\n\nГотов отправиться в приключение?",
            reply_markup=ready_kb())
        try:
            await bot.send_message(chat_id=best_match.tg_id, text=(
                f"🎉 **Найден напарник!**\n\n👤 **{user.username}**\n"
                f"{CLASS_EMOJI[user.class_name.value]} Класс: {user.class_name.value}\n"
                f"🎂 Возраст: {user.age}\n🏙️ Город: {user.city}\n"
                f"🏷️ **Общих тегов: {best_score}**\n{my_tags_text}\n\nГотов отправиться в приключение?"
            ), reply_markup=ready_kb())
        except Exception as e:
            print(f"⚠️ {e}")
    await call.answer()

# ---------- ГОТОВНОСТЬ И СТАРТ ДАНЖА ----------
@dp.callback_query(F.data == "ready")
async def ready_handler(call: CallbackQuery):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user or user.status != "matched" or not user.partner_tg_id:
            await call.answer("❌ Нет активного поиска", show_alert=True); return
        user.is_ready = True; db.commit()
        partner = db.execute(select(User).where(User.tg_id == user.partner_tg_id)).scalar_one_or_none()
        if not partner or not partner.is_ready:
            await call.message.edit_text("⏳ **Ждём напарника...**\n\nКак только он подтвердит готовность — начнётся приключение!")
            await call.answer(); return
        user.status = "dungeon"; partner.status = "dungeon"
        theme_key = random.choice(list(DUNGEONS.keys()))
        session = DungeonSession(player1_tg_id=user.tg_id, player2_tg_id=partner.tg_id,
                                 theme_key=theme_key, current_phase=1, current_question=0, status="active")
        db.add(session); db.commit()
        theme = DUNGEONS[theme_key]
        q = theme["phases"][0]["questions"][0]
        intro = (
            f"🎲 **Тема: {theme['name']}**\n"
            f"📍 Фаза 1/3 — {theme['phases'][0]['name']}\n"
            f"📊 Вопрос 1/{len(theme['phases'][0]['questions'])}\n\n"
            f"{q['text']}"
        )
        kb = dungeon_answer_kb(theme_key, 0, 0)
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
@dp.callback_query(F.data.startswith("da_"))
async def dungeon_answer(call: CallbackQuery):
    parts = call.data.split("_")
    theme_key, phase_idx, q_idx, ans_idx = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer("❌ Ошибка", show_alert=True); return
        session = db.execute(select(DungeonSession).where(
            DungeonSession.status == "active",
            ((DungeonSession.player1_tg_id == user.tg_id) | (DungeonSession.player2_tg_id == user.tg_id))
        )).scalars().first()
        if not session:
            await call.answer("❌ Сессия не найдена", show_alert=True); return
        if session.theme_key != theme_key or session.current_phase != phase_idx + 1 or session.current_question != q_idx:
            await call.answer("⏳ Уже идёт другой вопрос", show_alert=True); return
        if session.player1_tg_id == user.tg_id:
            if session.player1_ready:
                await call.answer("✅ Ты уже ответил", show_alert=True); return
            session.player1_answer = ans_idx; session.player1_ready = True
        else:
            if session.player2_ready:
                await call.answer("✅ Ты уже ответил", show_alert=True); return
            session.player2_answer = ans_idx; session.player2_ready = True
        db.commit()
        q = DUNGEONS[theme_key]["phases"][phase_idx]["questions"][q_idx]
        await call.message.edit_text(
            f"✅ Твой выбор: **{q['options'][ans_idx]['text']}**\n\n⏳ Ждём напарника..."
        )
        await call.answer("Ответ сохранён!")
        if session.player1_ready and session.player2_ready:
            await process_question(db, session, theme_key, phase_idx, q_idx)

async def process_question(db, session, theme_key, phase_idx, q_idx):
    q = DUNGEONS[theme_key]["phases"][phase_idx]["questions"][q_idx]
    p1_ans = session.player1_answer; p2_ans = session.player2_answer
    same = (p1_ans == p2_ans)
    p1_soft = q["options"][p1_ans]["soft"]; p2_soft = q["options"][p2_ans]["soft"]
    if same:
        bridge = q["bridges"]["same"]
        if phase_idx == 0: session.phase1_matches += 1
        elif phase_idx == 1: session.phase2_matches += 1
        else: session.phase3_matches += 1
    elif p1_soft and p2_soft:
        bridge = q["bridges"]["soft"]
        if phase_idx == 0: session.phase1_matches += 1
        elif phase_idx == 1: session.phase2_matches += 1
        else: session.phase3_matches += 1
    else:
        bridge = q["bridges"]["mixed"]
    session.player1_ready = False; session.player2_ready = False
    session.player1_answer = None; session.player2_answer = None
    session.current_question += 1
    theme = DUNGEONS[theme_key]
    phase = theme["phases"][phase_idx]
    total_q = len(phase["questions"])
    # Конец фазы?
    if session.current_question >= total_q:
        if phase_idx == 0:
            # КОНЕЦ 1-Й ФАЗЫ
            db.commit()
            await send_end_of_phase_1(session, theme_key, bridge)
            return
        elif phase_idx == 1:
            # КОНЕЦ 2-Й ФАЗЫ
            session.msg_stage = 0
            session.player1_msg = None; session.player2_msg = None
            db.commit()
            await send_end_of_phase_2(session, theme_key, bridge)
            return
        else:
            # КОНЕЦ 3-Й ФАЗЫ
            session.status = "finished"
            p1 = db.execute(select(User).where(User.tg_id == session.player1_tg_id)).scalar_one_or_none()
            p2 = db.execute(select(User).where(User.tg_id == session.player2_tg_id)).scalar_one_or_none()
            if p1: p1.status = "idle"; p1.partner_tg_id = None; p1.is_ready = False; p1.full_dungeons = (p1.full_dungeons or 0) + 1
            if p2: p2.status = "idle"; p2.partner_tg_id = None; p2.is_ready = False; p2.full_dungeons = (p2.full_dungeons or 0) + 1
            db.commit()
            await send_final(session, p1, p2, theme_key)
            return
    # Продолжение фазы
    next_q = phase["questions"][session.current_question]
    next_text = (
        f"{bridge}\n\n"
        f"📍 Фаза {phase_idx + 1}/3 — {phase['name']}\n"
        f"📊 Вопрос {session.current_question + 1}/{total_q}\n\n"
        f"{next_q['text']}"
    )
    next_kb = dungeon_answer_kb(theme_key, phase_idx, session.current_question)
    db.commit()
    try:
        await bot.send_message(chat_id=session.player1_tg_id, text=next_text, reply_markup=next_kb)
    except Exception as e: print(f"⚠️ {e}")
    try:
        await bot.send_message(chat_id=session.player2_tg_id, text=next_text, reply_markup=next_kb)
    except Exception as e: print(f"⚠️ {e}")

async def send_end_of_phase_1(session, theme_key, bridge):
    with SessionLocal() as db:
        p1 = db.execute(select(User).where(User.tg_id == session.player1_tg_id)).scalar_one_or_none()
        p2 = db.execute(select(User).where(User.tg_id == session.player2_tg_id)).scalar_one_or_none()
        text_to_p1 = (
            f"{bridge}\n\n"
            f"🏁 **Фаза 1 пройдена!**\n\n"
            f"🔑 **Ключ напарника:**\n_{p2.key_text if p2 else 'не указан'}_\n\n"
            f"Готов продолжить приключение?"
        )
        text_to_p2 = (
            f"{bridge}\n\n"
            f"🏁 **Фаза 1 пройдена!**\n\n"
            f"🔑 **Ключ напарника:**\n_{p1.key_text if p1 else 'не указан'}_\n\n"
            f"Готов продолжить приключение?"
        )
        try: await bot.send_message(chat_id=session.player1_tg_id, text=text_to_p1, reply_markup=continue_kb())
        except Exception as e: print(f"⚠️ {e}")
        try: await bot.send_message(chat_id=session.player2_tg_id, text=text_to_p2, reply_markup=continue_kb())
        except Exception as e: print(f"⚠️ {e}")

async def send_end_of_phase_2(session, theme_key, bridge):
    text = (
        f"{bridge}\n\n"
        f"🏁 **Фаза 2 пройдена!**\n\n"
        f"💬 **У тебя ОДНО сообщение для напарника.**\n"
        f"Напиши что-то, что заставит его ответить. До 200 символов.\n\n"
        f"Просто отправь текст боту — он передаст напарнику."
    )
    try: await bot.send_message(chat_id=session.player1_tg_id, text=text)
    except Exception as e: print(f"⚠️ {e}")
    try: await bot.send_message(chat_id=session.player2_tg_id, text=text)
    except Exception as e: print(f"⚠️ {e}")

async def send_final(session, p1, p2, theme_key):
    total = 11
    matches = session.phase1_matches + session.phase2_matches + session.phase3_matches
    percent = int(matches / total * 100)
    if percent >= 90:
        verdict = "✨ **Идеальный резонанс!**\n\nВы словно одна душа в двух телах. Такое встречается редко — не упустите друг друга."
    elif percent >= 70:
        verdict = "💫 **Сильный синхрон!**\n\nУ вас много общего. Это отличная основа для настоящего знакомства."
    elif percent >= 50:
        verdict = "🤔 **Есть точки соприкосновения.**\n\nВы разные — но в этом и интерес. Есть о чём поговорить."
    else:
        verdict = "💎 **Вы настолько неповторимы, что найти похожего — почти невозможно.**\n\nЭто как раз тот случай. Может быть, именно поэтому вам стоит узнать друг друга поближе?"
    if percent >= 50 and p1 and p2:
        contacts = f"\n\n📞 **Держите связь:**\n• {p1.username}\n• {p2.username}\n\nНапишите друг другу, не теряйтесь!"
    else:
        contacts = "\n\n💭 Если захотите — попробуйте пройти другой данж вместе."
    final_text = (
        f"🏁 **Данж завершён!**\n\n"
        f"💫 Синхрон: **{percent}%**\n"
        f"✅ Совпадений: **{matches} из {total}**\n\n"
        f"{verdict}{contacts}"
    )
    try: await bot.send_message(chat_id=session.player1_tg_id, text=final_text, reply_markup=main_menu())
    except Exception as e: print(f"⚠️ {e}")
    try: await bot.send_message(chat_id=session.player2_tg_id, text=final_text, reply_markup=main_menu())
    except Exception as e: print(f"⚠️ {e}")

# ---------- ОБРАБОТКА СООБЩЕНИЙ (между 2 и 3 фазой) ----------
@dp.message()
async def handle_text_message(msg: Message, state: FSMContext):
    # Пропускаем команды
    if msg.text and msg.text.startswith("/"):
        return
    if not msg.text:
        return
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user or user.status != "dungeon":
            return
        session = db.execute(select(DungeonSession).where(
            DungeonSession.status == "active",
            ((DungeonSession.player1_tg_id == user.tg_id) | (DungeonSession.player2_tg_id == user.tg_id))
        )).scalars().first()
        if not session:
            return
        if session.current_phase != 2:
            await msg.answer("✉️ Сейчас не время для сообщений. Отвечай на вопросы.")
            return
        if session.msg_stage == 2:
            await msg.answer("✉️ Вы уже обменялись сообщениями.")
            return
        text = msg.text.strip()[:200]
        is_p1 = (session.player1_tg_id == user.tg_id)
        if is_p1 and session.player1_msg:
            await msg.answer("✉️ Ты уже написал сообщение."); return
        if not is_p1 and session.player2_msg:
            await msg.answer("✉️ Ты уже написал сообщение."); return
        if is_p1:
            session.player1_msg = text
            partner_id = session.player2_tg_id
        else:
            session.player2_msg = text
            partner_id = session.player1_tg_id
        session.msg_stage += 1
        db.commit()
        await msg.answer("✅ Твоё сообщение отправлено напарнику.")
        try:
            await bot.send_message(chat_id=partner_id, text=f"💬 **Сообщение от напарника:**\n\n_{text}_")
        except Exception as e:
            print(f"⚠️ {e}")
        # Оба написали?
        if session.player1_msg and session.player2_msg:
            next_phase_text = (
                f"💬 **Вы обменялись сообщениями!**\n\n"
                f"Напарник написал:\n_{session.player2_msg if is_p1 else session.player1_msg}_\n\n"
                f"Готов продолжить приключение?"
            )
            try:
                await bot.send_message(chat_id=session.player1_tg_id, text=next_phase_text, reply_markup=continue_kb())
            except Exception as e: print(f"⚠️ {e}")
            try:
                await bot.send_message(chat_id=session.player2_tg_id, text=next_phase_text, reply_markup=continue_kb())
            except Exception as e: print(f"⚠️ {e}")

# ---------- ПРОДОЛЖЕНИЕ ДАНЖА ----------
@dp.callback_query(F.data == "dungeon_continue")
async def dungeon_continue(call: CallbackQuery):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer(); return
        session = db.execute(select(DungeonSession).where(
            DungeonSession.status == "active",
            ((DungeonSession.player1_tg_id == user.tg_id) | (DungeonSession.player2_tg_id == user.tg_id))
        )).scalars().first()
        if not session:
            await call.answer("❌ Сессия не найдена", show_alert=True); return
        # Если закончилась 1-я фаза — двигаемся во 2-ю
        if session.current_phase == 1 and session.current_question >= len(DUNGEONS[session.theme_key]["phases"][0]["questions"]):
            session.current_phase = 2; session.current_question = 0
            session.player1_ready = False; session.player2_ready = False
            db.commit()
            theme = DUNGEONS[session.theme_key]
            q = theme["phases"][1]["questions"][0]
            text = (
                f"⚔️ **Фаза 2/3 — {theme['phases'][1]['name']}**\n"
                f"📊 Вопрос 1/{len(theme['phases'][1]['questions'])}\n\n{q['text']}"
            )
            kb = dungeon_answer_kb(session.theme_key, 1, 0)
            await call.message.edit_text("⚔️ Идём дальше...")
            try: await bot.send_message(chat_id=session.player1_tg_id, text=text, reply_markup=kb)
            except Exception as e: print(f"⚠️ {e}")
            try: await bot.send_message(chat_id=session.player2_tg_id, text=text, reply_markup=kb)
            except Exception as e: print(f"⚠️ {e}")
        # Если закончилась 2-я фаза (msg_stage=2) — двигаемся в 3-ю
        elif session.current_phase == 2 and session.msg_stage == 2:
            session.current_phase = 3; session.current_question = 0
            session.player1_ready = False; session.player2_ready = False
            session.msg_stage = 0; session.player1_msg = None; session.player2_msg = None
            db.commit()
            theme = DUNGEONS[session.theme_key]
            q = theme["phases"][2]["questions"][0]
            text = (
                f"⚔️ **Фаза 3/3 — {theme['phases'][2]['name']}**\n"
                f"📊 Вопрос 1/{len(theme['phases'][2]['questions'])}\n\n{q['text']}"
            )
            kb = dungeon_answer_kb(session.theme_key, 2, 0)
            await call.message.edit_text("⚔️ Финальная фаза...")
            try: await bot.send_message(chat_id=session.player1_tg_id, text=text, reply_markup=kb)
            except Exception as e: print(f"⚠️ {e}")
            try: await bot.send_message(chat_id=session.player2_tg_id, text=text, reply_markup=kb)
            except Exception as e: print(f"⚠️ {e}")
        else:
            await call.answer("⏳ Ждём напарника", show_alert=True)
    await call.answer()

# ---------- ВЫХОД С ПОДТВЕРЖДЕНИЕМ ----------
@dp.callback_query(F.data == "dungeon_exit")
async def dungeon_exit(call: CallbackQuery):
    await call.message.edit_text(
        "⚠️ **Ты уверен, что хочешь покинуть приключение?**\n\n"
        "Прогресс будет потерян. Напарник продолжит искать нового партнёра.",
        reply_markup=confirm_exit_kb()
    )
    await call.answer()

@dp.callback_query(F.data == "dungeon_exit_cancel")
async def dungeon_exit_cancel(call: CallbackQuery):
    await call.message.edit_text("↩️ Возвращаемся в приключение...")
    await call.answer()

@dp.callback_query(F.data == "dungeon_exit_confirm")
async def dungeon_exit_confirm(call: CallbackQuery):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer(); return
        session = db.execute(select(DungeonSession).where(
            DungeonSession.status == "active",
            ((DungeonSession.player1_tg_id == user.tg_id) | (DungeonSession.player2_tg_id == user.tg_id))
        )).scalars().first()
        if not session:
            await call.answer(); return
        session.status = "finished"
        partner_id = session.player2_tg_id if session.player1_tg_id == user.tg_id else session.player1_tg_id
        user.status = "idle"; user.partner_tg_id = None; user.is_ready = False
        user.early_exits = (user.early_exits or 0) + 1
        partner = db.execute(select(User).where(User.tg_id == partner_id)).scalar_one_or_none()
        if partner:
            partner.status = "idle"; partner.partner_tg_id = None; partner.is_ready = False
        db.commit()
        await call.message.edit_text("❌ Ты покинул приключение. Возвращайся, когда захочешь!", reply_markup=main_menu())
        try:
            await bot.send_message(chat_id=partner_id,
                                   text="❌ Напарник покинул приключение. Ты снова свободен.",
                                   reply_markup=main_menu())
        except Exception as e:
            print(f"⚠️ {e}")
    await call.answer()

# ---------- ОТМЕНА МАТЧА ----------
@dp.callback_query(F.data == "cancel_match")
async def cancel_match(call: CallbackQuery):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == call.from_user.id)).scalar_one_or_none()
        if not user:
            await call.answer(); return
        partner_id = user.partner_tg_id
        user.status = "idle"; user.partner_tg_id = None; user.is_ready = False
        if partner_id:
            partner = db.execute(select(User).where(User.tg_id == partner_id)).scalar_one_or_none()
            if partner:
                partner.status = "idle"; partner.partner_tg_id = None; partner.is_ready = False
        db.commit()
        await call.message.edit_text("❌ Поиск отменён. Можешь попробовать снова.")
        await call.answer()
        if partner_id:
            try:
                await bot.send_message(chat_id=partner_id, text="❌ Напарник отменил поиск. Ты снова свободен.")
            except Exception:
                pass

# ---------- РЕДАКТИРОВАНИЕ ----------
@dp.message(Command("setname"))
async def setname(msg: Message):
    name = msg.text.replace("/setname", "").strip()
    if not name or len(name) < 2:
        await msg.answer("❌ Пример: /setname Артур"); return
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!"); return
        user.username = name; db.commit()
        await msg.answer(f"✅ Имя изменено на {name}")

@dp.message(Command("setage"))
async def setage(msg: Message):
    age = msg.text.replace("/setage", "").strip()
    if not age.isdigit() or int(age) < 16 or int(age) > 99:
        await msg.answer("❌ Пример: /setage 25"); return
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!"); return
        user.age = int(age); db.commit()
        await msg.answer(f"✅ Возраст изменён на {age}")

@dp.message(Command("setcity"))
async def setcity(msg: Message):
    city = msg.text.replace("/setcity", "").strip()
    if not city:
        await msg.answer("❌ Пример: /setcity Москва"); return
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!"); return
        user.city = city; db.commit()
        await msg.answer(f"✅ Город изменён на {city}")

@dp.message(Command("setkey"))
async def setkey(msg: Message):
    key = msg.text.replace("/setkey", "").strip()
    if not key or len(key) < 5 or len(key) > 100:
        await msg.answer("❌ Ключ от 5 до 100 символов. Пример: /setkey М/25, ищу друзей"); return
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!"); return
        user.key_text = key; db.commit()
        await msg.answer("✅ Ключ обновлён!")

# ---------- СБРОС ----------
@dp.message(Command("reset"))
async def reset_status(msg: Message):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.tg_id == msg.from_user.id)).scalar_one_or_none()
        if not user:
            await msg.answer("❌ Ты не зарегистрирован!"); return
        sessions = db.execute(select(DungeonSession).where(
            DungeonSession.status == "active",
            ((DungeonSession.player1_tg_id == user.tg_id) | (DungeonSession.player2_tg_id == user.tg_id))
        )).scalars().all()
        for s in sessions: s.status = "finished"
        user.status = "idle"; user.partner_tg_id = None; user.is_ready = False
        db.commit()
    await msg.answer("✅ Статус сброшен. Ты снова свободен!", reply_markup=main_menu())

# ========== ЗАПУСК ==========
async def main():
    with SessionLocal() as db:
        active_sessions = db.execute(select(DungeonSession).where(DungeonSession.status == "active")).scalars().all()
        for s in active_sessions: s.status = "finished"
        stuck = db.execute(select(User).where(User.status.in_(["dungeon", "matched", "searching", "waiting_msg"]))).scalars().all()
        for u in stuck:
            u.status = "idle"; u.partner_tg_id = None; u.is_ready = False
        db.commit()
        print(f"🧹 Сброшено зависших статусов: {len(stuck)}")
    print("✅ База данных готова!")
    print("🚀 Бот 'Рейд Сердец' запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
