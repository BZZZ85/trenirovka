import logging
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния диалога
(MAIN_MENU, ADD_WORKOUT_DATE, ADD_WORKOUT_EXERCISES, ADD_EXERCISE_NAME,
 ADD_SETS, ADD_REPS, ADD_WEIGHT, ADD_MORE_EXERCISES, ADD_NOTES,
 LOG_WEIGHT, VIEW_HISTORY, SET_REMINDER) = range(12)


# ── БД ────────────────────────────────────────────────────────────────────────

def get_db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL не задан!")
    # Railway даёт postgres://, psycopg2 хочет postgresql://
    return url.replace("postgres://", "postgresql://", 1)


@contextmanager
def get_conn():
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS workouts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            date TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS exercises (
            id SERIAL PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            sets INTEGER,
            reps TEXT,
            weight REAL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS body_weight (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            date TEXT NOT NULL,
            weight REAL NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS reminders (
            user_id BIGINT PRIMARY KEY,
            time TEXT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE
        )''')
    logger.info("БД инициализирована.")


# ── КЛАВИАТУРА ────────────────────────────────────────────────────────────────

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💪 Добавить тренировку"), KeyboardButton("📋 История")],
        [KeyboardButton("⚖️ Записать вес"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("⏰ Напоминания")]
    ], resize_keyboard=True)


# ── СТАРТ ─────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я помогу тебе вести дневник тренировок.\n\n"
        "Выбери действие:",
        reply_markup=main_keyboard()
    )
    return MAIN_MENU


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "💪 Добавить тренировку":
        await update.message.reply_text(
            "📅 Введи дату тренировки (например: 25.06.2025)\n"
            "Или напиши *сегодня* для текущей даты:",
            parse_mode="Markdown"
        )
        context.user_data['exercises'] = []
        return ADD_WORKOUT_DATE
    elif text == "📋 История":
        return await show_history(update, context)
    elif text == "⚖️ Записать вес":
        await update.message.reply_text("⚖️ Введи свой вес в кг (например: 75.5):")
        return LOG_WEIGHT
    elif text == "📊 Статистика":
        return await show_stats(update, context)
    elif text == "⏰ Напоминания":
        return await reminders_menu(update, context)

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
            await update.message.reply_text(
                "❌ Неверный формат. Введи дату как 25.06.2025 или напиши *сегодня*:",
                parse_mode="Markdown"
            )
            return ADD_WORKOUT_DATE

    context.user_data['workout_date'] = date
    await update.message.reply_text(f"✅ Дата: {date}\n\n🏋️ Введи название упражнения:")
    return ADD_EXERCISE_NAME


async def add_exercise_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_exercise'] = {'name': update.message.text.strip()}
    await update.message.reply_text("🔢 Сколько подходов?")
    return ADD_SETS


async def add_sets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sets = int(update.message.text.strip())
        context.user_data['current_exercise']['sets'] = sets
        await update.message.reply_text("🔁 Сколько повторений? (например: 10 или 8-10-12)")
        return ADD_REPS
    except ValueError:
        await update.message.reply_text("❌ Введи число:")
        return ADD_SETS


async def add_reps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_exercise']['reps'] = update.message.text.strip()
    await update.message.reply_text("🏋️ Вес в кг? (или напиши *без веса*):", parse_mode="Markdown")
    return ADD_WEIGHT


async def add_weight_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "без веса":
        weight = None
    else:
        try:
            weight = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ Введи число или напиши *без веса*:", parse_mode="Markdown")
            return ADD_WEIGHT

    context.user_data['current_exercise']['weight'] = weight
    context.user_data['exercises'].append(dict(context.user_data['current_exercise']))

    ex = context.user_data['current_exercise']
    weight_str = f"{weight} кг" if weight else "без веса"
    summary = f"✅ *{ex['name']}* — {ex['sets']} подх. × {ex['reps']} повт. @ {weight_str}\n"

    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить упражнение"), KeyboardButton("✅ Завершить тренировку")]
    ], resize_keyboard=True)

    await update.message.reply_text(
        summary + "\nДобавить ещё упражнение или завершить?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    return ADD_MORE_EXERCISES


async def add_more_exercises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "➕ Добавить упражнение":
        await update.message.reply_text("🏋️ Введи название упражнения:")
        return ADD_EXERCISE_NAME
    elif text == "✅ Завершить тренировку":
        await update.message.reply_text(
            "📝 Заметки к тренировке? (самочувствие, комментарии)\n"
            "Или напиши *пропустить*:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return ADD_NOTES

    return ADD_MORE_EXERCISES


async def add_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    notes = None if text.lower() == "пропустить" else text

    user_id = update.effective_user.id
    date = context.user_data['workout_date']
    exercises = context.user_data['exercises']

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO workouts (user_id, date, notes) VALUES (%s, %s, %s) RETURNING id",
            (user_id, date, notes)
        )
        workout_id = c.fetchone()['id']
        for ex in exercises:
            c.execute(
                "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES (%s, %s, %s, %s, %s)",
                (workout_id, ex['name'], ex['sets'], ex['reps'], ex.get('weight'))
            )

    lines = [f"🎉 *Тренировка сохранена!*\n📅 {date}\n"]
    for ex in exercises:
        w = f"{ex['weight']} кг" if ex.get('weight') else "без веса"
        lines.append(f"• {ex['name']}: {ex['sets']}×{ex['reps']} @ {w}")
    if notes:
        lines.append(f"\n📝 {notes}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN_MENU


# ── ИСТОРИЯ ───────────────────────────────────────────────────────────────────

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, date, notes FROM workouts WHERE user_id=%s ORDER BY date DESC LIMIT 10",
            (user_id,)
        )
        workouts = c.fetchall()

    if not workouts:
        await update.message.reply_text("📭 У тебя пока нет записанных тренировок.", reply_markup=main_keyboard())
        return MAIN_MENU

    buttons = []
    for w in workouts:
        label = f"📅 {w['date']}" + (f" — {w['notes'][:20]}..." if w['notes'] else "")
        buttons.append([InlineKeyboardButton(label, callback_data=f"workout_{w['id']}")])

    await update.message.reply_text(
        "📋 *Последние тренировки:*\nВыбери для просмотра деталей:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return MAIN_MENU


async def show_workout_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    workout_id = int(query.data.split("_")[1])

    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT date, notes FROM workouts WHERE id=%s", (workout_id,))
        workout = c.fetchone()
        c.execute("SELECT name, sets, reps, weight FROM exercises WHERE workout_id=%s", (workout_id,))
        exercises = c.fetchall()

    if not workout:
        await query.edit_message_text("❌ Тренировка не найдена.")
        return

    lines = [f"📅 *Тренировка {workout['date']}*\n"]
    for ex in exercises:
        w = f"{ex['weight']} кг" if ex['weight'] else "без веса"
        lines.append(f"• *{ex['name']}*: {ex['sets']}×{ex['reps']} @ {w}")
    if workout['notes']:
        lines.append(f"\n📝 _{workout['notes']}_")

    buttons = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{workout_id}")]]
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def delete_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    workout_id = int(query.data.split("_")[1])

    with get_conn() as conn:
        c = conn.cursor()
        # ON DELETE CASCADE удалит exercises автоматически
        c.execute("DELETE FROM workouts WHERE id=%s", (workout_id,))

    await query.edit_message_text("✅ Тренировка удалена.")


# ── ВЕС ТЕЛА ──────────────────────────────────────────────────────────────────

async def log_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text.strip().replace(",", "."))
        user_id = update.effective_user.id
        date = datetime.now().strftime("%d.%m.%Y")

        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO body_weight (user_id, date, weight) VALUES (%s, %s, %s)",
                (user_id, date, weight)
            )

        await update.message.reply_text(
            f"⚖️ Записано: *{weight} кг* на {date}",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Введи число, например: 75.5")
        return LOG_WEIGHT


# ── СТАТИСТИКА ────────────────────────────────────────────────────────────────

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    with get_conn() as conn:
        c = conn.cursor()

        c.execute("SELECT COUNT(*) as cnt FROM workouts WHERE user_id=%s", (user_id,))
        total = c.fetchone()['cnt']

        month_ago = (datetime.now() - timedelta(days=30)).strftime("%d.%m.%Y")
        c.execute(
            "SELECT COUNT(*) as cnt FROM workouts WHERE user_id=%s AND date >= %s",
            (user_id, month_ago)
        )
        last_month = c.fetchone()['cnt']

        c.execute("""
            SELECT e.name, COUNT(*) as cnt FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=%s
            GROUP BY e.name ORDER BY cnt DESC LIMIT 3
        """, (user_id,))
        top_exercises = c.fetchall()

        c.execute(
            "SELECT date, weight FROM body_weight WHERE user_id=%s ORDER BY id DESC LIMIT 5",
            (user_id,)
        )
        weights = c.fetchall()

        c.execute("""
            SELECT e.name, MAX(e.weight) as max_weight FROM exercises e
            JOIN workouts w ON e.workout_id = w.id
            WHERE w.user_id=%s AND e.weight IS NOT NULL
            GROUP BY e.name ORDER BY max_weight DESC LIMIT 5
        """, (user_id,))
        pbs = c.fetchall()

    lines = ["📊 *Твоя статистика*\n"]
    lines.append(f"🏋️ Всего тренировок: *{total}*")
    lines.append(f"📅 За последние 30 дней: *{last_month}*\n")

    if top_exercises:
        lines.append("🔥 *Топ упражнений:*")
        for row in top_exercises:
            lines.append(f"  • {row['name']}: {row['cnt']} раз")

    if pbs:
        lines.append("\n🏆 *Личные рекорды (макс. вес):*")
        for row in pbs:
            lines.append(f"  • {row['name']}: {row['max_weight']} кг")

    if weights:
        lines.append("\n⚖️ *История веса тела:*")
        for row in weights:
            lines.append(f"  • {row['date']}: {row['weight']} кг")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    return MAIN_MENU


# ── НАПОМИНАНИЯ ───────────────────────────────────────────────────────────────

async def reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT time, enabled FROM reminders WHERE user_id=%s", (user_id,))
        row = c.fetchone()

    if row:
        status = "✅ включено" if row['enabled'] else "❌ выключено"
        msg = f"⏰ Текущее напоминание: *{row['time']}* ({status})\n\nВведи новое время (например: 09:00) или напиши *выкл* для отключения:"
    else:
        msg = "⏰ Напоминания не настроены.\n\nВведи время для ежедневного напоминания (например: 09:00):"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return SET_REMINDER


async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    user_id = update.effective_user.id

    if text == "выкл":
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE reminders SET enabled=FALSE WHERE user_id=%s", (user_id,))
        await update.message.reply_text("❌ Напоминания отключены.", reply_markup=main_keyboard())
        return MAIN_MENU

    try:
        datetime.strptime(text, "%H:%M")
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO reminders (user_id, time, enabled) VALUES (%s, %s, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET time=%s, enabled=TRUE
            """, (user_id, text, text))
        await update.message.reply_text(
            f"✅ Буду напоминать о тренировке каждый день в *{text}*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введи время как 09:00:")
        return SET_REMINDER


# ── ОТПРАВКА НАПОМИНАНИЙ ──────────────────────────────────────────────────────

async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM reminders WHERE time=%s AND enabled=TRUE", (now,))
        users = c.fetchall()

    for row in users:
        try:
            await context.bot.send_message(
                chat_id=row['user_id'],
                text="💪 Привет! Не забудь про тренировку сегодня!\n\nИспользуй /start чтобы записать её."
            )
        except Exception as e:
            logger.error(f"Не удалось отправить напоминание {row['user_id']}: {e}")


# ── CANCEL ────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.", reply_markup=main_keyboard())
    return MAIN_MENU


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("Укажи TELEGRAM_BOT_TOKEN в переменных окружения!")

    init_db()

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
        ],
        states={
            MAIN_MENU:           [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
            ADD_WORKOUT_DATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_workout_date)],
            ADD_EXERCISE_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_exercise_name)],
            ADD_SETS:            [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sets)],
            ADD_REPS:            [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reps)],
            ADD_WEIGHT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, add_weight_exercise)],
            ADD_MORE_EXERCISES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_more_exercises)],
            ADD_NOTES:           [MessageHandler(filters.TEXT & ~filters.COMMAND, add_notes)],
            LOG_WEIGHT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, log_weight)],
            SET_REMINDER:        [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reminder)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(show_workout_detail, pattern="^workout_"))
    app.add_handler(CallbackQueryHandler(delete_workout, pattern="^delete_"))

    app.job_queue.run_repeating(send_reminders, interval=60, first=10)

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
