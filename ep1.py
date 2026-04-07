import os
from dotenv import load_dotenv

# =========================
# Setting
# =========================
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

print("TELEGRAM_BOT_TOKEN loaded successfully:", TELEGRAM_BOT_TOKEN)


from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

async def start(update:Update, context):
    """
    处理/Start命令
    """
    print("============")
    print(update)
    await update.message.reply_text(
        "hello, 我是Nanoclaw。\n\n 给我发送任何消息，我都会原样返还给你"
    )

async def end(update:Update, context):
    """
    处理/end命令
    """
    print("============")
    print(update)
    await update.message.reply_text(
        "我要清空所有的消息"
    )


async def echo(update:Update, context) -> None:
    """
    回显用户消息
    """
    await update.message.reply_text(update.message.text + "\n(这是回显消息)")


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('end',end))
                                   
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, echo)
    )

    print('Bot is Running...')
    app.run_polling()

if __name__ == "__main__":
    main()