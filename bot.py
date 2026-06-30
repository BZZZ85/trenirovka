import logging
import os
import asyncpg
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

(MAIN_MENU, ADD_WORKOUT_DATE, ADD_EXERCISE_NAME,
 ADD_SETS, ADD_REPS, ADD_WEIGHT, ADD_MORE_EXERCISES, ADD_NOTES,
 LOG_WEIGHT, SET_REMINDER) = range(10)

PRESET_PROGRAMS = {
    "Full Body (3 дня/нед)": [
        {"name": "Приседания со штангой", "sets": 3, "reps": "8-10"},
        {"name": "Жим лёжа", "sets": 3, "reps": "8-10"},
        {"name": "Тяга штанги в наклоне", "sets": 3, "reps": "8-10"},
        {"name": "Жим стоя", "sets": 3, "reps": "10"},
        {"name": "Подтягивания", "sets": 3, "reps": "макс"},
        {"name": "Планка", "sets": 3, "reps": "60 сек"},
    ],
    "Push (грудь/плечи/трицепс)": [
        {"name": "Жим лёжа", "sets": 4, "reps": "6-8"},
        {"name": "Жим гантелей под углом", "sets": 3, "reps": "8-10"},
        {"name": "Жим стоя", "sets": 3, "reps": "8-10"},
        {"name": "Разведения гантелей", "sets": 3, "reps": "12-15"},
        {"name": "Французский жим", "sets": 3, "reps": "10-12"},
        {"name": "Отжимания на брусьях", "sets": 3, "reps": "макс"},
    ],
    "Pull (спина/бицепс)": [
        {"name": "Становая тяга", "sets": 4, "reps": "5-6"},
        {"name": "Подтягивания", "sets": 4, "reps": "макс"},
        {"name": "Тяга штанги в наклоне", "sets": 3, "reps": "8-10"},
        {"name": "Тяга верхнего блока", "sets": 3, "reps": "10-12"},
        {"name": "Подъём штанги на бицепс", "sets": 3, "reps": "10-12"},
        {"name": "Молотки с гантелями", "sets": 3, "reps": "12"},
    ],
    "Leg (ноги/ягодицы)": [
        {"name": "Приседания со штангой", "sets": 4, "reps": "6-8"},
        {"name": "Румынская тяга", "sets": 3, "reps": "8-10"},
        {"name": "Жим ногами", "sets": 3, "reps": "10-12"},
        {"name": "Выпады с гантелями", "sets": 3, "reps": "10 на ногу"},
        {"name": "Подъём на носки", "sets": 4, "reps": "15-20"},
        {"name": "Гиперэкстензия", "sets": 3, "reps": "12-15"},
    ],
    "Начинающий (3 дня/нед)": [
        {"name": "Приседания со штангой", "sets": 3, "reps": "10"},
        {"name": "Жим лёжа", "sets": 3, "reps": "10"},
        {"name": "Тяга штанги в наклоне", "sets": 3, "reps": "10"},
        {"name": "Жим стоя", "sets": 2, "reps": "10"},
        {"name": "Планка", "sets": 3, "reps": "30-45 сек"},
    ],
}
# ── БД ────────────────────────────────────────────────────────────────────────

def get_db_url():
    url = os.getenv("DATABASE_URL", "")
    return url.replace("postgres://", "postgresql://", 1)


async def get_pool(app):
    app.bot_data['pool'] = await asyncpg.create_pool(get_db_url())
    pool = app.bot_data['pool']
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS workouts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                date TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS exercises (
                id SERIAL PRIMARY KEY,
                workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                sets INTEGER,
                reps TEXT,
                weight REAL
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS body_weight (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                date TEXT NOT NULL,
                weight REAL NOT NULL
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                user_id BIGINT PRIMARY KEY,
                time TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS template_exercises (
                id SERIAL PRIMARY KEY,
                template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                sets INTEGER,
                reps TEXT,
                weight REAL
            )''')
    logger.info("БД готова.")


async def close_pool(app):
    if 'pool' in app.bot_data:
        await app.bot_data['pool'].close()


def pool(context):
    return context.application.bot_data['pool']


# ── КЛАВИАТУРА ────────────────────────────────────────────────────────────────

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💪 Добавить тренировку"), KeyboardButton("📋 История")],
        [KeyboardButton("⚖️ Записать вес"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("📈 Прогресс"), KeyboardButton("⏰ Напоминания")],
        [KeyboardButton("Упражнения"), KeyboardButton("📑 Шаблоны")],
        [KeyboardButton("🎯 Готовые программы")]
    ], resize_keyboard=True)

# ── СТАРТ ─────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! 👋\n\n"
        "Я помогу тебе вести дневник тренировок.\n\nВыбери действие:",
        reply_markup=main_keyboard()
    )
    return MAIN_MENU


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if context.user_data.get('waiting_preset_choice'):
        return await use_preset_program(update, context)
    if context.user_data.get('waiting_delete_exercise'):
        return await process_delete_exercise(update, context)
    if context.user_data.get('waiting_progress_exercise'):
        return await show_exercise_progress(update, context)
    if context.user_data.get('waiting_template_name'):
        return await save_template_name(update, context)
    if context.user_data.get('waiting_template_choice'):
        return await use_template(update, context)
    if text == "💪 Добавить тренировку":
        context.user_data['exercises'] = []
        context.user_data['workout_date'] = datetime.now().strftime("%d.%m.%Y")
        context.user_data['choosing_exercise'] = False
        return await add_exercise_name(update, context)
    elif text == "📋 История":
        return await show_history(update, context)
    elif text == "⚖️ Записать вес":
        await update.message.reply_text("⚖️ Введи свой вес в кг (например: 75.5):")
        return LOG_WEIGHT
    elif text == "📊 Статистика":
        return await show_stats(update, context)
    elif text == "⏰ Напоминания":
        return await reminders_menu(update, context)
    elif text == "📈 Прогресс":
        return await show_progress(update, context)
    elif text == "Упражнения":
        return await manage_exercises(update, context)
    elif text == "🎯 Готовые программы":
        return await preset_programs_menu(update, context)
    elif text == "💾 Сохранить как шаблон":
        if not context.user_data.get('last_exercises'):
            await update.message.reply_text("Нет данных последней тренировки.", reply_markup=main_keyboard())
            return MAIN_MENU
        context.user_data['waiting_template_name'] = True
        await update.message.reply_text("Введи название шаблона (например: День ног):",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return MAIN_MENU

async def preset_programs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [[KeyboardButton(name)] for name in PRESET_PROGRAMS.keys()]
    buttons.append([KeyboardButton("🔙 Назад")])

    context.user_data['waiting_preset_choice'] = True
    await update.message.reply_text(
        "🎯 Выбери готовую программу:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return MAIN_MENU


async def use_preset_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop('waiting_preset_choice', None)

    if text == "🔙 Назад":
        await update.message.reply_text("Меню:", reply_markup=main_keyboard())
        return MAIN_MENU

    program = PRESET_PROGRAMS.get(text)
    if not program:
        await update.message.reply_text("Программа не найдена.", reply_markup=main_keyboard())
        return MAIN_MENU

    user_id = update.effective_user.id
    date = datetime.now().strftime("%d.%m.%Y")

    async with pool(context).acquire() as conn:
        workout_id = await conn.fetchval(
            "INSERT INTO workouts (user_id, date, notes) VALUES ($1, $2, $3) RETURNING id",
            user_id, date, f"Программа: {text}"
        )
        await conn.executemany(
            "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES ($1, $2, $3, $4, NULL)",
            [(workout_id, ex['name'], ex['sets'], ex['reps']) for ex in program]
        )

    lines = [f"🎉 *Тренировка по программе «{text}» сохранена!*\n📅 {date}\n"]
    for ex in program:
        lines.append(f"• {ex['name']}: {ex['sets']}×{ex['reps']}")
    lines.append("\n💡 Вес можно добавить позже через редактирование в истории.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    return MAIN_MENU

# ── ДОБАВЛЕНИЕ ТРЕНИРОВКИ ─────────────────────────────────────────────────────

async def add_workout_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ("сегодня", "today"):
        date = datetime.now().strftime("%d.%m.%Y")
    else:
        try:
            datetime.strptime(text, "%d.%m.%Y")
            date = text
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Введи как 25.06.2025 или *сегодня*:", parse_mode="Markdown")
            return ADD_WORKOUT_DATE
    context.user_data['choosing_exercise'] = False
    await update.message.reply_text(f"✅ Дата: {date}")
    return await add_exercise_name(update, context)


async def add_exercise_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "🔙 Назад":
        context.user_data['exercises'] = []
        await update.message.reply_text("Возврат в меню.", reply_markup=main_keyboard())
        return MAIN_MENU

    async with pool(context).acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT name FROM exercises e JOIN workouts w ON e.workout_id=w.id WHERE w.user_id=$1 ORDER BY name LIMIT 8",
            user_id
        )

    known = [r['name'] for r in rows]

    if text == "✏️ Новое упражнение":
        context.user_data['choosing_exercise'] = True
        await update.message.reply_text("🏋️ Введи название упражнения:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ADD_EXERCISE_NAME

    if text in known or context.user_data.get('choosing_exercise'):
        context.user_data['choosing_exercise'] = False
        context.user_data['current_exercise'] = {'name': text}
        await update.message.reply_text("🔢 Сколько подходов?",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ADD_SETS

    # Показываем кнопки
    context.user_data['choosing_exercise'] = True
    buttons = [[KeyboardButton(name)] for name in known]
    buttons.append([KeyboardButton("✏️ Новое упражнение")])
    buttons.append([KeyboardButton("🔙 Назад")])
    await update.message.reply_text(
        "🏋️ Выбери упражнение:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return ADD_EXERCISE_NAME


async def add_sets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "🔙 Назад":
        context.user_data['choosing_exercise'] = False
        return await add_exercise_name(update, context)
    try:
        context.user_data['current_exercise']['sets'] = int(update.message.text.strip())
        await update.message.reply_text("🔁 Сколько повторений? (например: 10 или 8-10-12)",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ADD_REPS
    except ValueError:
        await update.message.reply_text("❌ Введи число:")
        return ADD_SETS


async def add_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "🔙 Назад":
        await update.message.reply_text("🔢 Сколько подходов?",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ADD_SETS
    context.user_data['current_exercise']['reps'] = update.message.text.strip()
    sets = context.user_data['current_exercise']['sets']
    await update.message.reply_text(
        f"🏋️ Введи вес для каждого подхода через пробел ({sets} подх.)\nНапример: `100 95 90` или `80` если везде одинаково\nИли напиши *без веса*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    )
    return ADD_WEIGHT


async def add_weight_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "🔙 Назад":
        sets = context.user_data['current_exercise']['sets']
        await update.message.reply_text(
            f"🔁 Сколько повторений?",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ADD_REPS

    if text.lower() == "без веса":
        weight_str = "без веса"
        weight = None
    else:
        parts = text.replace(",", ".").split()
        try:
            weights = [float(p) for p in parts]
        except ValueError:
            await update.message.reply_text("❌ Введи числа через пробел, например: `100 95 90`", parse_mode="Markdown")
            return ADD_WEIGHT
        if len(weights) == 1:
            weight = weights[0]
            weight_str = f"{weight} кг"
        else:
            weight = max(weights)
            weight_str = " / ".join(f"{w} кг" for w in weights)
            context.user_data['current_exercise']['weight_detail'] = weight_str

    context.user_data['current_exercise']['weight'] = weight
    context.user_data['exercises'].append(dict(context.user_data['current_exercise']))
    ex = context.user_data['current_exercise']
    w_display = ex.get('weight_detail', weight_str)
    await update.message.reply_text(
        f"✅ *{ex['name']}* — {ex['sets']} подх. × {ex['reps']} повт. @ {w_display}\n\nДобавить ещё?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("➕ Добавить упражнение"), KeyboardButton("✅ Завершить тренировку")],
            [KeyboardButton("🔙 Назад")]
        ], resize_keyboard=True)
    )
    return ADD_MORE_EXERCISES


async def add_more_exercises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Назад":
        if context.user_data['exercises']:
            context.user_data['exercises'].pop()
        context.user_data['choosing_exercise'] = False
        return await add_exercise_name(update, context)
    elif text == "➕ Добавить упражнение":
        context.user_data['choosing_exercise'] = False
        return await add_exercise_name(update, context)
    elif text == "✅ Завершить тренировку":
        await update.message.reply_text(
            "📝 Заметки к тренировке? Или напиши *пропустить*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("пропустить"), KeyboardButton("🔙 Назад")]
            ], resize_keyboard=True)
        )
        return ADD_NOTES
    return ADD_MORE_EXERCISES


async def add_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    notes = None if text.lower() == "пропустить" else text
    user_id = update.effective_user.id
    date = context.user_data['workout_date']
    exercises = context.user_data['exercises']

    async with pool(context).acquire() as conn:
        workout_id = await conn.fetchval(
            "INSERT INTO workouts (user_id, date, notes) VALUES ($1, $2, $3) RETURNING id",
            user_id, date, notes
        )
        await conn.executemany(
            "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES ($1, $2, $3, $4, $5)",
            [(workout_id, ex['name'], ex['sets'], ex['reps'], ex.get('weight')) for ex in exercises]
        )

    lines = [f"🎉 *Тренировка сохранена!*\n📅 {date}\n"]
    for ex in exercises:
        w = ex.get('weight_detail') or (f"{ex['weight']} кг" if ex.get('weight') else "без веса")
        lines.append(f"• {ex['name']}: {ex['sets']}×{ex['reps']} @ {w}")
    if notes:
        lines.append(f"\n📝 {notes}")

    context.user_data['last_exercises'] = exercises
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("💾 Сохранить как шаблон")],
            [KeyboardButton("💪 Добавить тренировку"), KeyboardButton("📋 История")],
            [KeyboardButton("⚖️ Записать вес"), KeyboardButton("📊 Статистика")],
            [KeyboardButton("📈 Прогресс"), KeyboardButton("⏰ Напоминания")],
            [KeyboardButton("Упражнения"), KeyboardButton("📑 Шаблоны")],
            [KeyboardButton("🎯 Готовые программы")]
        ], resize_keyboard=True)
    )
    return MAIN_MENU


# ── ИСТОРИЯ ───────────────────────────────────────────────────────────────────

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with pool(context).acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, date, notes FROM workouts WHERE user_id=$1 ORDER BY date DESC LIMIT 10",
            user_id
        )
    if not rows:
        await update.message.reply_text("📭 Пока нет тренировок.", reply_markup=main_keyboard())
        return MAIN_MENU

    buttons = []
    for r in rows:
        label = f"📅 {r['date']}" + (f" — {r['notes'][:20]}..." if r['notes'] else "")
        buttons.append([InlineKeyboardButton(label, callback_data=f"workout_{r['id']}")])

    await update.message.reply_text(
        "📋 *Последние тренировки:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return MAIN_MENU


async def show_workout_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    workout_id = int(query.data.split("_")[1])

    async with pool(context).acquire() as conn:
        w = await conn.fetchrow("SELECT date, notes FROM workouts WHERE id=$1", workout_id)
        exs = await conn.fetch("SELECT id, name, sets, reps, weight FROM exercises WHERE workout_id=$1", workout_id)

    if not w:
        await query.edit_message_text("❌ Тренировка не найдена.")
        return

    lines = [f"📅 *Тренировка {w['date']}*\n"]
    for ex in exs:
        wt = f"{ex['weight']} кг" if ex['weight'] else "без веса"
        lines.append(f"• *{ex['name']}*: {ex['sets']}×{ex['reps']} @ {wt}")
    if w['notes']:
        lines.append(f"\n📝 _{w['notes']}_")

    buttons = []
    for ex in exs:
        buttons.append([InlineKeyboardButton(f"🗑 {ex['name']}", callback_data=f"delex_one_{ex['id']}")])
    buttons.append([InlineKeyboardButton("🗑 Удалить всю тренировку", callback_data=f"delete_{workout_id}")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
async def delete_one_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ex_id = int(query.data.replace("delex_one_", "", 1))

    async with pool(context).acquire() as conn:
        await conn.execute("DELETE FROM exercises WHERE id=$1", ex_id)

    await query.edit_message_text("✅ Упражнение удалено из тренировки.")

async def delete_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    workout_id = int(query.data.split("_")[1])
    async with pool(context).acquire() as conn:
        await conn.execute("DELETE FROM workouts WHERE id=$1", workout_id)
    await query.edit_message_text("✅ Тренировка удалена.")


# ── ВЕС ТЕЛА ──────────────────────────────────────────────────────────────────

async def log_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text.strip().replace(",", "."))
        user_id = update.effective_user.id
        date = datetime.now().strftime("%d.%m.%Y")
        async with pool(context).acquire() as conn:
            await conn.execute(
                "INSERT INTO body_weight (user_id, date, weight) VALUES ($1, $2, $3)",
                user_id, date, weight
            )
        await update.message.reply_text(f"⚖️ Записано: *{weight} кг* на {date}", parse_mode="Markdown", reply_markup=main_keyboard())
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Введи число, например: 75.5")
        return LOG_WEIGHT


# ── СТАТИСТИКА ────────────────────────────────────────────────────────────────

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%d.%m.%Y")

    async with pool(context).acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM workouts WHERE user_id=$1", user_id)
        last_month = await conn.fetchval(
            "SELECT COUNT(*) FROM workouts WHERE user_id=$1 AND date >= $2", user_id, month_ago
        )
        top = await conn.fetch("""
            SELECT e.name, COUNT(*) as cnt FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=$1 GROUP BY e.name ORDER BY cnt DESC LIMIT 3
        """, user_id)
        pbs = await conn.fetch("""
            SELECT e.name, MAX(e.weight) as max_w FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=$1 AND e.weight IS NOT NULL
            GROUP BY e.name ORDER BY max_w DESC LIMIT 5
        """, user_id)
        weights = await conn.fetch(
            "SELECT date, weight FROM body_weight WHERE user_id=$1 ORDER BY id DESC LIMIT 5", user_id
        )

    lines = ["📊 *Твоя статистика*\n",
             f"🏋️ Всего тренировок: *{total}*",
             f"📅 За последние 30 дней: *{last_month}*\n"]
    if top:
        lines.append("🔥 *Топ упражнений:*")
        for r in top:
            lines.append(f"  • {r['name']}: {r['cnt']} раз")
    if pbs:
        lines.append("\n🏆 *Личные рекорды:*")
        for r in pbs:
            lines.append(f"  • {r['name']}: {r['max_w']} кг")
    if weights:
        lines.append("\n⚖️ *История веса тела:*")
        for r in weights:
            lines.append(f"  • {r['date']}: {r['weight']} кг")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    return MAIN_MENU


# ── НАПОМИНАНИЯ ───────────────────────────────────────────────────────────────

async def reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with pool(context).acquire() as conn:
        row = await conn.fetchrow("SELECT time, enabled FROM reminders WHERE user_id=$1", user_id)

    if row:
        status = "✅ включено" if row['enabled'] else "❌ выключено"
        msg = f"⏰ Текущее напоминание: *{row['time']}* ({status})\n\nВведи новое время (09:00) или *выкл*:"
    else:
        msg = "⏰ Напоминания не настроены.\n\nВведи время (например: 09:00):"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return SET_REMINDER


async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    user_id = update.effective_user.id

    if text == "выкл":
        async with pool(context).acquire() as conn:
            await conn.execute("UPDATE reminders SET enabled=FALSE WHERE user_id=$1", user_id)
        await update.message.reply_text("❌ Напоминания отключены.", reply_markup=main_keyboard())
        return MAIN_MENU

    try:
        datetime.strptime(text, "%H:%M")
        async with pool(context).acquire() as conn:
            await conn.execute("""
                INSERT INTO reminders (user_id, time, enabled) VALUES ($1, $2, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET time=$2, enabled=TRUE
            """, user_id, text)
        await update.message.reply_text(
            f"✅ Буду напоминать каждый день в *{text}*",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введи как 09:00:")
        return SET_REMINDER


async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%H:%M")
    async with pool(context).acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM reminders WHERE time=$1 AND enabled=TRUE", now)
    for row in users:
        try:
            await context.bot.send_message(
                chat_id=row['user_id'],
                text="💪 Не забудь про тренировку сегодня!\n\nИспользуй /start чтобы записать её."
            )
        except Exception as e:
            logger.error(f"Ошибка напоминания {row['user_id']}: {e}")
#прогресс
async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with pool(context).acquire() as conn:
        # Все упражнения пользователя
        exercises = await conn.fetch("""
            SELECT DISTINCT e.name FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=$1 ORDER BY e.name
        """, user_id)

    if not exercises:
        await update.message.reply_text("📭 Пока нет данных для прогресса.", reply_markup=main_keyboard())
        return MAIN_MENU

    buttons = [[KeyboardButton(r['name'])] for r in exercises]
    buttons.append([KeyboardButton("🔙 Назад")])
    await update.message.reply_text(
        "📈 Выбери упражнение для анализа прогресса:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    context.user_data['waiting_progress_exercise'] = True
    return MAIN_MENU


async def show_exercise_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "🔙 Назад":
        context.user_data.pop('waiting_progress_exercise', None)
        await update.message.reply_text("Меню:", reply_markup=main_keyboard())
        return MAIN_MENU

    async with pool(context).acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.date, e.weight, e.reps, e.sets FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=$1 AND e.name=$2
            ORDER BY w.date DESC LIMIT 5
        """, user_id, text)

    if not rows:
        await update.message.reply_text("Нет данных по этому упражнению.", reply_markup=main_keyboard())
        context.user_data.pop('waiting_progress_exercise', None)
        return MAIN_MENU

    context.user_data.pop('waiting_progress_exercise', None)
    lines = [f"📈 *Прогресс: {text}*\n"]

    last_weight = None
    for r in reversed(rows):
        w = r['weight']
        lines.append(f"📅 {r['date']}: {r['sets']}×{r['reps']} @ {w if w else '—'} кг")
        last_weight = w

    # Рекомендация
    if last_weight:
        next_weight = round(last_weight * 1.05 / 2.5) * 2.5  # +5%, округление до 2.5 кг
        lines.append(f"\n💡 *Рекомендация:* попробуй {next_weight} кг на следующей тренировке (+5%)")
    else:
        lines.append("\n💡 Добавь вес на следующей тренировке!")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    return MAIN_MENU
#Удаления 
async def manage_exercises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with pool(context).acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT e.name FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=$1 ORDER BY e.name
        """, user_id)

    if not rows:
        await update.message.reply_text("📭 Нет упражнений.", reply_markup=main_keyboard())
        return MAIN_MENU

    names = [r['name'] for r in rows]
    buttons = [[KeyboardButton(name)] for name in names]
    buttons.append([KeyboardButton("🔙 Назад")])

    context.user_data['waiting_delete_exercise'] = True
    await update.message.reply_text(
        "Выбери упражнение для удаления из всей истории:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return MAIN_MENU
async def save_template_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop('waiting_template_name', None)

    if text == "🔙 Назад":
        await update.message.reply_text("Меню:", reply_markup=main_keyboard())
        return MAIN_MENU

    user_id = update.effective_user.id
    exercises = context.user_data.get('last_exercises', [])

    async with pool(context).acquire() as conn:
        template_id = await conn.fetchval(
            "INSERT INTO templates (user_id, name) VALUES ($1, $2) RETURNING id",
            user_id, text
        )
        await conn.executemany(
            "INSERT INTO template_exercises (template_id, name, sets, reps, weight) VALUES ($1, $2, $3, $4, $5)",
            [(template_id, ex['name'], ex['sets'], ex['reps'], ex.get('weight')) for ex in exercises]
        )

    await update.message.reply_text(f"✅ Шаблон «{text}» сохранён!", reply_markup=main_keyboard())
    return MAIN_MENU


async def templates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with pool(context).acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM templates WHERE user_id=$1 ORDER BY name", user_id)

    if not rows:
        await update.message.reply_text("📭 Нет сохранённых шаблонов.\nСохрани после следующей тренировки кнопкой «💾 Сохранить как шаблон»!", reply_markup=main_keyboard())
        return MAIN_MENU

    context.user_data['template_map'] = {r['name']: r['id'] for r in rows}
    buttons = [[KeyboardButton(r['name'])] for r in rows]
    buttons.append([KeyboardButton("🔙 Назад")])

    context.user_data['waiting_template_choice'] = True
    await update.message.reply_text(
        "📑 Выбери шаблон для запуска тренировки:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return MAIN_MENU


async def use_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop('waiting_template_choice', None)

    if text == "🔙 Назад":
        await update.message.reply_text("Меню:", reply_markup=main_keyboard())
        return MAIN_MENU

    template_map = context.user_data.get('template_map', {})
    template_id = template_map.get(text)

    if not template_id:
        await update.message.reply_text("Шаблон не найден.", reply_markup=main_keyboard())
        return MAIN_MENU

    async with pool(context).acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, sets, reps, weight FROM template_exercises WHERE template_id=$1",
            template_id
        )

    exercises = [{'name': r['name'], 'sets': r['sets'], 'reps': r['reps'], 'weight': r['weight']} for r in rows]

    user_id = update.effective_user.id
    date = datetime.now().strftime("%d.%m.%Y")

    async with pool(context).acquire() as conn:
        workout_id = await conn.fetchval(
            "INSERT INTO workouts (user_id, date, notes) VALUES ($1, $2, $3) RETURNING id",
            user_id, date, f"По шаблону: {text}"
        )
        await conn.executemany(
            "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES ($1, $2, $3, $4, $5)",
            [(workout_id, ex['name'], ex['sets'], ex['reps'], ex.get('weight')) for ex in exercises]
        )

    lines = [f"🎉 *Тренировка по шаблону «{text}» сохранена!*\n📅 {date}\n"]
    for ex in exercises:
        w = f"{ex['weight']} кг" if ex.get('weight') else "без веса"
        lines.append(f"• {ex['name']}: {ex['sets']}×{ex['reps']} @ {w}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    return MAIN_MENU

async def process_delete_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop('waiting_delete_exercise', None)

    if text == "🔙 Назад":
        await update.message.reply_text("Меню:", reply_markup=main_keyboard())
        return MAIN_MENU

    user_id = update.effective_user.id
    async with pool(context).acquire() as conn:
        await conn.execute("""
            DELETE FROM exercises WHERE name=$1 AND workout_id IN (
                SELECT id FROM workouts WHERE user_id=$2
            )
        """, text, user_id)

    await update.message.reply_text(f"✅ Упражнение «{text}» удалено из всей истории.", reply_markup=main_keyboard())
    return MAIN_MENU

    # Сохраняем имена во временный словарь, в кнопке передаём короткий индекс
    names = [r['name'] for r in rows]
    context.user_data['delex_names'] = names

    buttons = [[InlineKeyboardButton(f"🗑 {name}", callback_data=f"delex_{i}")] for i, name in enumerate(names)]
    await update.message.reply_text(
        "🗑 Выбери упражнение для удаления из истории:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return MAIN_MENU

async def delete_exercise_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.replace("delex_", "", 1))
    names = context.user_data.get('delex_names', [])

    if idx >= len(names):
        await query.edit_message_text("❌ Упражнение не найдено, попробуй снова через меню.")
        return

    name = names[idx]
    user_id = query.from_user.id

    async with pool(context).acquire() as conn:
        await conn.execute("""
            DELETE FROM exercises WHERE name=$1 AND workout_id IN (
                SELECT id FROM workouts WHERE user_id=$2
            )
        """, name, user_id)

    await query.edit_message_text(f"✅ Упражнение *{name}* удалено из всей истории.", parse_mode="Markdown")
    
# ── CANCEL + MAIN ─────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.", reply_markup=main_keyboard())
    return MAIN_MENU

async def error_handler(update, context):
    logger.error("Exception while handling update:", exc_info=context.error)
def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("Укажи TELEGRAM_BOT_TOKEN!")
    if not os.getenv("DATABASE_URL"):
        raise ValueError("Укажи DATABASE_URL!")

    app = (Application.builder()
           .token(TOKEN)
           .post_init(get_pool)
           .post_shutdown(close_pool)
           .build())

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU:          [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
            ADD_EXERCISE_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exercise_name)],
            ADD_SETS:           [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sets)],
            ADD_REPS:           [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reps)],
            ADD_WEIGHT:         [MessageHandler(filters.TEXT & ~filters.COMMAND, add_weight_exercise)],
            ADD_MORE_EXERCISES: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_more_exercises)],
            ADD_NOTES:          [MessageHandler(filters.TEXT & ~filters.COMMAND, add_notes)],
            LOG_WEIGHT:         [MessageHandler(filters.TEXT & ~filters.COMMAND, log_weight)],
            SET_REMINDER:       [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reminder)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_error_handler(error_handler)
    app.add_handler(CallbackQueryHandler(show_workout_detail, pattern="^workout_"))
    app.add_handler(CallbackQueryHandler(delete_workout, pattern="^delete_\\d+$"))
    app.add_handler(CallbackQueryHandler(delete_exercise_type, pattern="^delex_\\d+$"))
    app.add_handler(CallbackQueryHandler(delete_one_exercise, pattern="^delex_one_\\d+$"))
    app.job_queue.run_repeating(send_reminders, interval=60, first=10)

    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
