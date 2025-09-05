import sqlite3
from datetime import date
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ------------------------------
# Database setup
# ------------------------------
DB_NAME = "tasks.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        date TEXT NOT NULL,
        done INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

init_db()

def get_tasks(for_date=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if for_date:
        c.execute("SELECT id, title, date, done FROM tasks WHERE date=?", (for_date,))
    else:
        c.execute("SELECT id, title, date, done FROM tasks")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "date": r[2], "done": bool(r[3])} for r in rows]

def add_task(title, date_str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO tasks (title, date) VALUES (?, ?)", (title, date_str))
    conn.commit()
    conn.close()

def toggle_task_status(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT done FROM tasks WHERE id=?", (task_id,))
    row = c.fetchone()
    if row:
        new_status = 0 if row[0] else 1
        c.execute("UPDATE tasks SET done=? WHERE id=?", (new_status, task_id))
        conn.commit()
    conn.close()

# ------------------------------
# Telegram Bot
# ------------------------------
TELEGRAM_TOKEN = "7783968185:AAEso8rgt_5jhA3PgyCV-vbfSC2I0HIrK7g"
CHAT_ID = "7223100242"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /add <task> <YYYY-MM-DD> or /today")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <task> [YYYY-MM-DD]")
        return
    possible_date = context.args[-1]
    try:
        date.fromisoformat(possible_date)
        title = " ".join(context.args[:-1])
        date_str = possible_date
    except ValueError:
        title = " ".join(context.args)
        date_str = date.today().isoformat()
    add_task(title, date_str)
    await update.message.reply_text(f"✅ Task '{title}' added for {date_str}")

async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_str = date.today().isoformat()
    tasks = get_tasks(for_date=today_str)
    if not tasks:
        await update.message.reply_text("📭 No tasks for today!")
        return
    keyboard = [[InlineKeyboardButton(f"{'✅' if t['done'] else '⭕'} {t['title']}", callback_data=f"toggle_{t['id']}")] for t in tasks]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 Today’s Tasks:", reply_markup=reply_markup)

async def toggle_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    toggle_task_status(task_id)

    today_str = date.today().isoformat()
    tasks = get_tasks(for_date=today_str)
    keyboard = [[InlineKeyboardButton(f"{'✅' if t['done'] else '⭕'} {t['title']}", callback_data=f"toggle_{t['id']}")] for t in tasks]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📅 Today’s Tasks:", reply_markup=reply_markup)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_str = context.args[0] if context.args else date.today().isoformat()
    tasks = get_tasks(for_date=date_str)
    if not tasks:
        await update.message.reply_text(f"📭 No tasks for {date_str}")
        return
    msg = f"📅 Tasks for {date_str}:\n" + "\n".join([f"{'✅' if t['done'] else '⭕'} {t['title']}" for t in tasks])
    await update.message.reply_text(msg)

async def send_task_notifications(app_tg):
    today_str = date.today().isoformat()
    tasks = get_tasks(for_date=today_str)
    if not tasks:
        return
    msg = "⏰ Reminder! Today’s Tasks:\n" + "\n".join([f"{'✅' if t['done'] else '⭕'} {t['title']}" for t in tasks])
    await app_tg.bot.send_message(chat_id=CHAT_ID, text=msg)

# ------------------------------
# Main bot runner
# ------------------------------
async def main():
    app_tg = Application.builder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("add", add))
    app_tg.add_handler(CommandHandler("list", list_cmd))
    app_tg.add_handler(CommandHandler("today", today_cmd))
    app_tg.add_handler(CallbackQueryHandler(toggle_task))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_task_notifications(app_tg)), "interval", hours=2)
    scheduler.start()

    print("Bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()  # Keep running

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nBot stopped gracefully.")

