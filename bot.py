import asyncio
import sqlite3
import threading
from typing import Final

from openai import AsyncOpenAI
from telegram import Update
from telegram.error import TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

OPENAI_API_KEY = "ABC"
OPENAI_MODEL = "gpt-3.5-turbo"

BOT_TOKEN: Final = "ABC"


START_TEXT = """
Hello and welcome here!
Use /help to see how you can use me.
"""

HELP_TEXT = """
You can send me integers to start a timer.
I will send you a message after the timer has finished.
"""


class UserLockManager:
    def __init__(self):
        self.user_locks = {}

    def acquire_lock(self, user_id):
        if user_id not in self.user_locks:
            self.user_locks[user_id] = threading.Lock()

        lock = self.user_locks[user_id]
        lock.acquire()

    def release_lock(self, user_id):
        if user_id in self.user_locks:
            lock = self.user_locks[user_id]
            lock.release()

    def is_lock_acquired(self, user_id):
        if user_id in self.user_locks:
            lock = self.user_locks[user_id]
            return lock.locked()

        return False


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message: str = update.message
    message_text: str = message.text
    user_id: int = message.from_user.id
    username = update.message.from_user.username

    await log_message_to_db(username, message_text)

    if message_text.isdigit():
        await update.message.reply_text(f"Starting timer for {message_text} seconds...")
        asyncio.create_task(run_timer(int(message_text), update, message.message_id))

    else:
        if lock_manager.is_lock_acquired(user_id):
            await update.message.reply_text(
                "I'm still thinking about your last message. 🤔",
                reply_to_message_id=message.message_id,
            )
            return

        lock_manager.acquire_lock(user_id)

        await update.message.reply_text("Let me think about that...")
        await update.message.chat.send_action(action="typing")

        asyncio.create_task(ask_openai(update))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.message.from_user.id

    await update.message.reply_text(
        "I'm sorry, but I couldn't think of a response. 😔",
        reply_to_message_id=update.message.message_id,
    )

    lock_manager.release_lock(user_id)
    username = update.message.from_user.username

    print(f"Chat with user {username} caused an error: {context.error}")


async def run_timer(seconds: int, update: Update, message_id: int) -> None:
    await asyncio.sleep(seconds)

    await update.message.reply_text(
        f"This timer has finished! 🎉",
        reply_to_message_id=message_id,
    )


async def ask_openai(update: Update) -> None:
    message: str = update.message
    message_text: str = message.text
    user_id: int = message.from_user.id

    try:
        chat_completion = await openai_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": message_text,
                }
            ],
            model=OPENAI_MODEL,
        )

    except Exception as exc:
        raise exc

    finally:
        lock_manager.release_lock(user_id)

    await update.message.reply_text(chat_completion.choices[0].message.content)


async def log_message_to_db(username: str, message: str) -> None:
    cursor.execute(
        "INSERT INTO messages (username, text) VALUES (?, ?)",
        (
            username,
            message,
        ),
    )

    conn.commit()


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler(
            command="start",
            callback=handle_start,
        )
    )

    app.add_handler(
        CommandHandler(
            command="help",
            callback=handle_help,
        )
    )

    app.add_handler(
        MessageHandler(
            filters=filters.TEXT,
            callback=handle_response,
        )
    )

    app.add_error_handler(error_handler)

    try:
        app.run_polling(
            poll_interval=1,
            allowed_updates=Update.MESSAGE,
        )

    except TimedOut:
        print("Couldn't connect to telegram. Please restart the bot.")


if __name__ == "__main__":
    conn = sqlite3.connect("messages.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            text TEXT
        )
    """
    )

    lock_manager = UserLockManager()
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    print("Starting bot...")
    threading.Thread(target=asyncio.run, args=(main(),)).start()
