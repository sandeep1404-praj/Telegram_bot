from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date
import sqlite3
import threading, asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from fastapi import Path
from fastapi import Body
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
from pydantic import BaseModel

class TaskUpdate(BaseModel):
    done: bool

# ------------------------------
# FastAPI setup with CORS
# ------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # local dev
        "https://dailybot.netlify.app"  # production frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    

@app.put("/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET done=? WHERE id=?", (1 if task.done else 0, task_id))
    conn.commit()
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    conn.close()
    return {"message": "✅ Task updated"}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int = Path(..., description="ID of the task to delete")):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    deleted = c.rowcount
    conn.close()

    if deleted == 0:
        raise HTTPException(status_code=404, detail="❌ Task not found")
    return {"message": f"🗑️ Task {task_id} deleted successfully"}

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
# API Endpoints
# ------------------------------
class Task(BaseModel):
    title: str
    date: str

@app.get("/tasks")
def list_tasks(date: str = None):
    return get_tasks(for_date=date)

@app.post("/tasks")
def create_task(task: Task):
    today = date.today().isoformat()
    if task.date < today:
        raise HTTPException(status_code=400, detail="❌ Cannot add tasks in the past.")
    add_task(task.title, task.date)
    return {"message": "✅ Task added successfully"}

# ------------------------------
# Telegram Bot
# ------------------------------
TELEGRAM_TOKEN = "7783968185:AAEso8rgt_5jhA3PgyCV-vbfSC2I0HIrK7g"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /add <task> <YYYY-MM-DD> or /today")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <task> [YYYY-MM-DD]")
        return

    # If the last arg looks like a date, use it, otherwise assume today
    possible_date = context.args[-1]
    try:
        datetime.date.fromisoformat(possible_date)  # valid date?
        title = " ".join(context.args[:-1])
        date_str = possible_date
    except ValueError:
        title = " ".join(context.args)
        date_str = date.today().isoformat()

    add_task(title, date_str)
    await update.message.reply_text(f"✅ Task '{title}' added for {date_str}")


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_str = date.today().isoformat()
    today_tasks = get_tasks(for_date=today_str)

    if not today_tasks:
        await update.message.reply_text("📭 No tasks for today!")
        return

    keyboard = []
    for t in today_tasks:
        status = "✅" if t["done"] else "⭕"
        button = InlineKeyboardButton(
            f"{status} {t['title']}",
            callback_data=f"toggle_{t['id']}"
        )
        keyboard.append([button])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 Today’s Tasks:", reply_markup=reply_markup)

async def toggle_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    toggle_task_status(task_id)

    today_str = date.today().isoformat()
    today_tasks = get_tasks(for_date=today_str)
    keyboard = []
    for t in today_tasks:
        status = "✅" if t["done"] else "⭕"
        button = InlineKeyboardButton(
            f"{status} {t['title']}",
            callback_data=f"toggle_{t['id']}"
        )
        keyboard.append([button])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📅 Today’s Tasks:", reply_markup=reply_markup)
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If a date is given → use it, else → today
    if context.args:
        date_str = context.args[0]
    else:
        date_str = date.today().isoformat()

    tasks = get_tasks(for_date=date_str)

    if not tasks:
        await update.message.reply_text(f"📭 No tasks for {date_str}")
        return

    msg = f"📅 Tasks for {date_str}:\n"
    for t in tasks:
        status = "✅" if t["done"] else "⭕"
        msg += f"{status} {t['title']}\n"

    await update.message.reply_text(msg)

# ------------------------------
# Notification Sender
# ------------------------------
async def send_task_notifications(app_tg):
    today_str = date.today().isoformat()
    today_tasks = get_tasks(for_date=today_str)

    if not today_tasks:
        return

    # send notification to your Telegram chat (replace with your chat_id)
    chat_id = "7223100242"  # replace after getting from /start
    msg = "⏰ Reminder! Today’s Tasks:\n"
    for t in today_tasks:
        status = "✅" if t["done"] else "⭕"
        msg += f"{status} {t['title']}\n"

    await app_tg.bot.send_message(chat_id=chat_id, text=msg)

# ------------------------------
# Start bot + scheduler
# ------------------------------
def run_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    app_tg = Application.builder().token(TELEGRAM_TOKEN).build()

    # Bot commands
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("add", add))
    app_tg.add_handler(CommandHandler("list", list_cmd))
    app_tg.add_handler(CommandHandler("today", today_cmd))
    app_tg.add_handler(CallbackQueryHandler(toggle_task))

    # Scheduler for reminders
    scheduler = BackgroundScheduler()

    async def job():
        await send_task_notifications(app_tg)

    # Run every 2 hours
    scheduler.add_job(lambda: asyncio.create_task(job()), "interval", hours=2)
    scheduler.start()

    app_tg.run_polling()


def start_bot_in_thread():
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()

# ------------------------------
# FastAPI Startup Event
# ------------------------------
@app.on_event("startup")
async def startup_event():
    start_bot_in_thread()
