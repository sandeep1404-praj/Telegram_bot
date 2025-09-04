from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date
import threading, asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.background import BackgroundScheduler
import datetime

from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ------------------------------
# Database setup (PostgreSQL)
# ------------------------------
DATABASE_URL = "postgresql://task_3csn_user:fQbPuodSxPj7W12IZzf4LsFrCynwj10f@dpg-d2sul9muk2gs73cb5qf0-a/task_3csn"  
# Replace with your Render PostgreSQL connection string

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class TaskDB(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    date = Column(String, nullable=False)
    done = Column(Boolean, default=False)


Base.metadata.create_all(bind=engine)


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
# Pydantic Models
# ------------------------------
class Task(BaseModel):
    title: str
    date: str


class TaskUpdate(BaseModel):
    done: bool


# ------------------------------
# Database helpers
# ------------------------------
def get_tasks(for_date=None):
    db = SessionLocal()
    if for_date:
        rows = db.query(TaskDB).filter(TaskDB.date == for_date).all()
    else:
        rows = db.query(TaskDB).all()
    db.close()
    return [{"id": r.id, "title": r.title, "date": r.date, "done": r.done} for r in rows]


def add_task(title, date_str):
    db = SessionLocal()
    task = TaskDB(title=title, date=date_str, done=False)
    db.add(task)
    db.commit()
    db.close()


def toggle_task_status(task_id):
    db = SessionLocal()
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if task:
        task.done = not task.done
        db.commit()
    db.close()


# ------------------------------
# API Endpoints
# ------------------------------
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


@app.put("/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    db = SessionLocal()
    db_task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not db_task:
        db.close()
        raise HTTPException(status_code=404, detail="Task not found")
    db_task.done = task.done
    db.commit()
    db.close()
    return {"message": "✅ Task updated"}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int = Path(..., description="ID of the task to delete")):
    db = SessionLocal()
    deleted = db.query(TaskDB).filter(TaskDB.id == task_id).delete()
    db.commit()
    db.close()

    if deleted == 0:
        raise HTTPException(status_code=404, detail="❌ Task not found")
    return {"message": f"🗑️ Task {task_id} deleted successfully"}


# ------------------------------
# Telegram Bot
# ------------------------------
TELEGRAM_TOKEN = "7783968185:AAEso8rgt_5jhA3PgyCV-vbfSC2I0HIrK7g"  # replace with your bot token
CHAT_ID = "7223100242"  # replace with your Telegram chat ID after /start


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /add <task> <YYYY-MM-DD> or /today")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <task> [YYYY-MM-DD]")
        return

    possible_date = context.args[-1]
    try:
        datetime.date.fromisoformat(possible_date)
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
# Notifications
# ------------------------------
async def send_task_notifications(app_tg):
    today_str = date.today().isoformat()
    today_tasks = get_tasks(for_date=today_str)

    if not today_tasks:
        return

    msg = "⏰ Reminder! Today’s Tasks:\n"
    for t in today_tasks:
        status = "✅" if t["done"] else "⭕"
        msg += f"{status} {t['title']}\n"

    await app_tg.bot.send_message(chat_id=CHAT_ID, text=msg)


def run_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    app_tg = Application.builder().token(TELEGRAM_TOKEN).build()

    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("add", add))
    app_tg.add_handler(CommandHandler("list", list_cmd))
    app_tg.add_handler(CommandHandler("today", today_cmd))
    app_tg.add_handler(CallbackQueryHandler(toggle_task))

    scheduler = BackgroundScheduler()

    async def job():
        await send_task_notifications(app_tg)

    scheduler.add_job(lambda: asyncio.create_task(job()), "interval", hours=2)
    scheduler.start()

    app_tg.run_polling()


def start_bot_in_thread():
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()


# ------------------------------
# FastAPI Startup
# ------------------------------
@app.on_event("startup")
async def startup_event():
    start_bot_in_thread()
