import json
import time
import os
import threading

from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn


# ==========================
# Environment Variables
# ==========================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")

LOG_URL = os.environ.get(
    "LOG_URL",
    "http://localhost/run.jsonl"
)

# ==========================
# OpenAI Client
# ==========================

client = OpenAI(
    base_url="https://aipipe.org/openai/v1",
    api_key=AIPIPE_TOKEN,
)

LOG_FILE = "run.jsonl"

conversation_history = {}

# ==========================
# FastAPI Web Server
# ==========================

web = FastAPI()


@web.get("/")
def home():
    return {"status": "Bot is running"}


@web.get("/run.jsonl")
def download_log():

    if os.path.exists(LOG_FILE):
        return FileResponse(
            LOG_FILE,
            media_type="application/json",
            filename="run.jsonl",
        )

    return {"message": "Log file not found."}


def start_web():

    port = int(os.environ.get("PORT", 10000))

    uvicorn.run(
        web,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


# ==========================
# Logging
# ==========================

def log_event(event: dict):

    event["timestamp"] = time.time()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


# ==========================
# Telegram Bot
# ==========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    user_text = update.message.text

    log_event(
        {
            "type": "incoming",
            "chat_id": chat_id,
            "text": user_text,
        }
    )

    history = conversation_history.setdefault(chat_id, [])

    history.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    system_prompt = (
        "You are a careful data analyst. "
        "The user's LAST message asks a data-analysis question and tells you exactly "
        "what JSON shape to reply with. "
        "Work out the real answer. "
        "Reply ONLY with that JSON object. "
        "Do not use markdown. "
        "Do not add explanations. "
        "Do not add extra keys."
    )

    try:

        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                }
            ]
            + history[-6:],
        )

        reply_text = response.choices[0].message.content.strip()

        history.append(
            {
                "role": "assistant",
                "content": reply_text,
            }
        )

        try:

            parsed = json.loads(reply_text)

        except json.JSONDecodeError:

            start = reply_text.find("{")
            end = reply_text.rfind("}")

            if start != -1 and end != -1:

                parsed = json.loads(reply_text[start : end + 1])

            else:

                raise ValueError("No JSON found.")

        if "result" in parsed and "answer" not in parsed:
            parsed["answer"] = parsed.pop("result")

        if "answer" not in parsed:
            parsed = {
                "answer": parsed
            }

        parsed["log_url"] = LOG_URL

        final_reply = json.dumps(parsed)

    except Exception as e:

        print("ERROR:", e)

        final_reply = json.dumps(
            {
                "answer": "error",
                "log_url": LOG_URL,
            }
        )

    log_event(
        {
            "type": "outgoing",
            "chat_id": chat_id,
            "text": final_reply,
        }
    )

    await update.message.reply_text(final_reply)


# ==========================
# Main
# ==========================

if __name__ == "__main__":

    threading.Thread(
        target=start_web,
        daemon=True,
    ).start()

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("Bot is running...")

    app.run_polling()
