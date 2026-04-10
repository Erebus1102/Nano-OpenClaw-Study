# !/usr/bin/env python3
"""
Claude Bot inject soul to robot
based on claude code sdk

prepare work
1. install claude code cli
2. write ANTHROPIC_API_KEY in .env
3. run: uv run python ep02_claude_bot.py


Claude Agent SDK概念

消息类型：
- AssistantMessage：Claude 生成内容
- TextBlock：文本片段
- ResultMessage：最终结果+Session id

调用方式：
- 'query()'是异步生成器
- 逐步拼接输出
- 可切换Permission Mode
"""

import os
from dotenv import load_dotenv

# =========================
# Setting
# =========================
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_AUTH_TOKEN = os.environ["ANTHROPIC_AUTH_TOKEN"]
ANTHROPIC_BASE_URL = os.environ["ANTHROPIC_BASE_URL"]
ANTHROPIC_DEFAULT_SONNET_MODEL = os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"]

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

from claude_agent_sdk import(
    AssistantMessage, # Claude Agent 回复的消息
    ClaudeAgentOptions, # 启动Claude Code的配置项（MCP，工具，系统提示词等）
    ResultMessage, # 最终执行的结果
    TextBlock, # 文本块的回复
    query # 核心函数，发送消息给Claude Agent，并获取回复
)

async def ask_claude(prompt:str) -> str:
    env = {
        "ANTHROPIC_AUTH_TOKEN": ANTHROPIC_AUTH_TOKEN,
        "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": ANTHROPIC_DEFAULT_SONNET_MODEL
    }
    options = ClaudeAgentOptions(
        # bypassPermissions # 所有操作都自动确认（rm -rf ..）
        permission_mode = 'acceptEdits',
        env = env
    )
    response_parts:list[str] = []
    async for message in query(prompt=prompt,options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block,TextBlock):
                    response_parts.append(block.text)
        elif isinstance(message, ResultMessage):
            if message.result:
                print("Claude 最终结果：", message.result)
                response_parts.append(message.result)
    return "\n".join(response_parts) or "我没有得到Claude的回复"

async def handle_message(update:Update, context):
    if not update.message or not update.message.text:
        return
    response = await ask_claude(update.message.text)

    max_length = 4000
    for i in range(0, len(response), max_length):
        await update.message.reply_text(response[i:i+max_length])

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
        MessageHandler(filters.TEXT & ~filters.COMMAND, 
                       # echo
                       handle_message
                       )
    )

    print('Bot is Running...')
    app.run_polling()

if __name__ == "__main__":
    main() 