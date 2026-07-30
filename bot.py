import json
import time
import os
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# 1. Securely load your tokens from the environment

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")


LOG_URL = os.environ.get("LOG_URL", "http://localhost/run.jsonl")


# 2. Connect to the AI provider
client = OpenAI(
    base_url="https://aipipe.org/openai/v1",
    api_key=AIPIPE_TOKEN
)

LOG_FILE = "run.jsonl"
conversation_history = {}

# 3. Helper function to save every action to a file
def log_event(event: dict):
    event["timestamp"] = time.time()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")


# 4. The main function that runs whenever someone sends a message
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Log incoming message
    log_event({
        "type": "incoming",
        "chat_id": chat_id,
        "text": user_text
    })

    # Save conversation history
    history = conversation_history.setdefault(chat_id, [])
    history.append({
        "role": "user",
        "content": user_text
    })

    # Instructions for AI
    system_prompt = (
        "You are a careful data analyst. "
        "The user's LAST message asks a data-analysis question and tells you exactly "
        "what JSON shape to reply with. "
        "Work out the real answer. "
        "Reply with ONLY that exact JSON object and absolutely nothing else. "
        "Do NOT wrap the JSON in markdown. "
        "Do NOT add explanations. "
        "Do NOT add extra keys."
    )

    try:

        # Ask AI
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                }
            ] + history[-6:]
        )

        reply_text = response.choices[0].message.content.strip()

        history.append({
            "role": "assistant",
            "content": reply_text
        })

        # Convert AI response into JSON
        try:
            parsed = json.loads(reply_text)

        except json.JSONDecodeError:

            start = reply_text.find("{")
            end = reply_text.rfind("}")

            if start != -1 and end != -1:
                parsed = json.loads(reply_text[start:end + 1])
            else:
                raise ValueError("No JSON object found")

        # Convert "result" → "answer"
        if "result" in parsed and "answer" not in parsed:
            parsed["answer"] = parsed.pop("result")

        # If answer is missing
        if "answer" not in parsed:
            parsed = {
                "answer": parsed
            }

        # Always include log_url
        parsed["log_url"] = LOG_URL

        final_reply = json.dumps(parsed)

    except Exception as e:

        print("Error:", e)

        final_reply = json.dumps({
            "answer": "error",
            "log_url": LOG_URL
        })

    # Log outgoing reply
    log_event({
        "type": "outgoing",
        "chat_id": chat_id,
        "text": final_reply
    })

    # Send reply
    await update.message.reply_text(final_reply)


# 5. Start the bot
if __name__ == "__main__":

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Bot is running... (Ctrl+C to stop)")

    app.run_polling()