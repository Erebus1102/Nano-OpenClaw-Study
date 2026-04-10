# !/usr/bin/env python3
# 指定这是一个 python3 脚本，在 Unix 系统中用来指明执行该脚本的解释器

import os # 导入 os 模块，用于访问操作系统接口，例如读取环境变量
from pathlib import Path # 导入 Path 对象，用于处理文件路径，比 os.path 更面向对象
from dotenv import load_dotenv # 从 dotenv 库中导入 load_dotenv，用于从 .env 文件加载环境变量
from telegram import Update # 从 telegram 库导入 Update，代表 telegram 服务器发来的一个更新（比如新消息）
from typing import Any # 从 typing 导入 Any，用于类型注解，表示任意类型
from telegram.ext import Application, CommandHandler, MessageHandler, filters # 从 telegram.ext 导入构建机器人的核心类
from claude_agent_sdk import( # 从 claude_agent_sdk 导入与 Claude 交互相关的类和函数
    AssistantMessage, # Claude Agent 回复的消息对象类型
    ClaudeAgentOptions, # 启动 Claude Code 的配置项类（用于配置 MCP，工具，系统提示词等）
    ResultMessage, # 包含最终执行结果的消息类型
    TextBlock, # 文本块对象，代表 Claude 回复中的文本内容
    query, # 核心函数：用于发送消息给 Claude Agent，并以异步生成器的形式获取回复
    create_sdk_mcp_server, # 创建 MCP (Model Context Protocol) 服务器的工具函数
    AgentDefinition, # 定义 Agent 的配置对象
    tool, # 将普通函数注册为 Agent 可用工具的装饰器
    PermissionResultAllow # 允许 Agent 执行操作的结果类型
)

# =========================
# Setting (设置区域)
# =========================

load_dotenv() # 加载当前目录下的 .env 文件，将其中的键值对注入到操作系统的环境变量中
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"] # 从环境变量中获取 Telegram 机器人的 Token
ANTHROPIC_AUTH_TOKEN = os.environ["ANTHROPIC_AUTH_TOKEN"] # 从环境变量中获取 Anthropic (Claude) 的 API 密钥
ANTHROPIC_BASE_URL = os.environ["ANTHROPIC_BASE_URL"] # 从环境变量获取请求 Claude API 的基础 URL
ANTHROPIC_DEFAULT_SONNET_MODEL = os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] # 从环境变量获取默认使用的模型名
OWNER_ID = int(os.environ["OWNER_ID"]) # 从环境变量获取机器人的拥有者 ID，并转换成整数类型

print("TELEGRAM_BOT_TOKEN loaded successfully:", TELEGRAM_BOT_TOKEN) # 在控制台打印日志，确认 Token 成功加载

async def start(update:Update, context): # 定义处理 /start 命令的异步回调函数，接收 update 和 context 两个参数
    """
    处理/Start命令
    """
    print("============") # 打印分隔符，方便在控制台查看日志
    print(update) # 在控制台打印当前 update 的详细信息，用于调试
    await update.message.reply_text( # 异步调用，向用户回复文本消息
        "hello, 我是Nanoclaw。\n\n 给我发送任何消息，我都会原样返还给你" # 回复的内容
    )

async def end(update:Update, context): # 定义处理 /end 命令的异步回调函数
    """
    处理/end命令
    """
    print("============") # 打印分隔符
    print(update) # 打印 update 详细信息
    await update.message.reply_text( # 异步调用，向用户回复文本消息
        "我要清空所有的消息" # 回复的内容
    )

"""
1. 添加内置对应工具
2. 添加MCP工具
"""

# 工作目录，Agent 操作文件
BASE_DIR = Path(__file__).resolve().parent # 获取当前脚本文件所在的绝对目录路径作为 BASE_DIR
WORKSPACE_DIR = BASE_DIR/"workspace" # 在 BASE_DIR 下拼接出 workspace 文件夹路径，作为 Agent 工作目录

async def ask_claude(prompt:str,bot, chat_id) -> str: # 定义一个异步函数 ask_claude，接收提示词、机器人对象和聊天 ID，返回字符串结果
    env = { # 构造一个字典，准备传给 Claude Agent 运行时的环境变量
        "ANTHROPIC_AUTH_TOKEN": ANTHROPIC_AUTH_TOKEN, # 注入认证 token
        "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL, # 注入 Base URL
        "ANTHROPIC_DEFAULT_SONNET_MODEL": ANTHROPIC_DEFAULT_SONNET_MODEL # 注入默认模型
    }
    tools = create_mcp_server_tools(bot, chat_id) # 调用辅助函数，创建给 MCP 使用的工具列表，把 bot 和 chat_id 传进去

    async def _allow_all_tools(*_):         # 定义一个简单的权限函数，允许 Agent 使用所有工具
        return PermissionResultAllow(behavior="allow")

    options = ClaudeAgentOptions( # 实例化 Claude Agent 的配置项对象
        cwd = str(WORKSPACE_DIR), # 将工作目录路径转成字符串并传给 agent，agent 将在此目录下执行操作
        # 可用的工具
        allowed_tools = [ # 配置基础的、默认允许使用的内置工具
            "Read", # 允许读取文件工具
            "Write", # 允许写入文件工具
            "Edit", # 允许编辑文件工具
            "Glob", # 允许根据通配符搜索文件工具
            "Grep", # 允许在文件中搜索文本的工具
            "Bash", # 允许执行 Bash 命令的工具
            "WebSearch", # 允许进行网络搜索的工具
            "WebFetch", # 允许抓取网页内容的工具
        ],
        agents = { # 定义可用的特定角色 agent 列表
            "coder": AgentDefinition( # 定义一个名为 coder 的 agent
                    description = "专业程序员", # 它的角色描述
                    prompt = "你是一个经验丰富的Python开发者", # 给它的特定的提示词指令
                    tools = ["Read","Write","Bash"], # 它可以使用的工具，比默认配置多了 Bash 工具
            )
        },

        # bypassPermissions # 所有操作都自动确认（rm -rf ..）
        permission_mode = 'acceptEdits', # 权限模式设为接受编辑，即 Agent 调用工具时会先返回一个编辑建议，用户确认后才会执行（比 bypass 更安全）
        env = env, # 传入之前准备好的环境变量字典
        can_use_tool = _allow_all_tools, # 允许 Agent 使用所有工具的权限函数（也可以自定义更细粒度的权限控制函数）
        mcp_servers = { # 配置外部传入的 MCP 服务器
            "assistant": create_sdk_mcp_server( # 使用 sdk 快速创建一个名为 assistant 的 mcp server
                name = "assistant", # 指定 server 名字
                tools = tools, # 将上面 `create_mcp_server_tools` 创建的自定义工具注册到这个 mcp server 中
            )
        },
    )

    async def _make_prompt(text:str): # 定义一个内部异步生成器函数，用于构造发送给 agent 的消息格式
        yield { # yield 抛出一个字典格式的消息
            "type":"user", # 指定消息类型为用户消息
            "message":{"role":"user","content":text}, # 内部的 message 对象，定义了发出该消息的角色(user)和内容
        }

    response_parts:list[str] = [] # 定义一个列表用于收集 agent 吐出来的回复碎片
    async for message in query(prompt=_make_prompt(prompt),options=options): # 调用 SDK 的 query 方法，传入 prompt 生成器和 options，异步遍历返回的消息流
        if isinstance(message, AssistantMessage): # 判断如果返回的消息类型是 AssistantMessage (代表 agent 发送给用户的对话消息)
            for block in message.content: # 遍历该消息中的内容块
                if isinstance(block,TextBlock): # 如果该块是文本块类型
                    response_parts.append(block.text) # 把文本内容追加到列表中
        elif isinstance(message, ResultMessage): # 如果返回的是 ResultMessage (代表某种操作的最终执行结果)
            if message.result: # 如果它包含了 result 字段
                print("Claude 最终结果：", message.result) # 在控制台打印调试信息
                response_parts.append(message.result) # 将结果同样追加到回复列表中
    return "\n".join(response_parts) or "我没有得到Claude的回复" # 将所有收集到的片段拼接成一个完整字符串，如果没有收集到任何内容，返回兜底文本

def create_mcp_server_tools(bot, chat_id:int) -> list: # 定义函数用于创建工具列表，接收 bot 实例和 chat_id 参数
    @tool("send_message","发送消息给用户",{"text":str}) # 使用 @tool 装饰器把下面的函数变成一个 Agent 可以调用的工具，并定义了工具名称、描述和它接受的参数类型
    async def send_message(args) -> dict[str, Any]: # 定义处理发送消息逻辑的异步函数，它将收到由 Agent 传入的 args 字典
        # 这一行是主动给用户发消息
        await bot.send_message(chat_id = chat_id, text = args["text"]) # 使用 python-telegram-bot 的接口向指定的 chat_id 发送文本消息
        # 返回值是：告诉Agent发送消息的结果
        return { # 将执行的结果以特定格式封装后返回给 Agent，作为工具执行成功后的反馈
            "content":[ # 返回内容是一个列表
                {
                    "type":"text", # 声明反馈内容为文本
                    "text":f"已向用户发送消息：{(args['text'])}", # 具体的反馈文本内容，告知 Agent 消息已发出
                }
            ]
        }
    return [send_message] # 把上面定义好的通过装饰器包裹后的 `send_message` 工具函数放进列表中并返回

async def handle_message(update:Update, context): # 定义处理所有非命令普通文本消息的异步回调函数
    if not update.message or not update.message.text: # 如果收到的是空消息或者不是文本消息
        return # 直接退出不处理
    response = await ask_claude(update.message.text, context.bot, update.effective_chat.id) # 将用户发来的文本、bot 实例、以及当前聊天的 id 传入 `ask_claude` 以获取 Agent 回复

    max_length = 4000 # 定义 Telegram 单条消息的最大长度限制（目前实际上 Telegram 的限制是 4096）
    for i in range(0, len(response), max_length): # 对长消息按 max_length 进行切片遍历
        await update.message.reply_text(response[i:i+max_length]) # 将每一段截取的文字发送回用户，从而绕过长消息发不出的问题

# async def echo(update:Update, context) -> None: # 这一段是被注释掉的旧代码：简单的回显函数，它收到什么就发回什么
#     """
#     回显用户消息
#     """
#     await update.message.reply_text(update.message.text + "\n(这是回显消息)") # 回显逻辑代码被注释

def main(): # 定义主函数
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build() # 用 Builder 模式使用获取到的 Token 构建一个 Telegram Bot 的核心 Application 实例

    app.add_handler(CommandHandler('start',start)) # 向 app 注册 /start 命令的处理器，关联 `start` 回调函数
    app.add_handler(CommandHandler('end',end)) # 向 app 注册 /end 命令的处理器，关联 `end` 回调函数

    app.add_handler( # 注册消息处理器
        MessageHandler(filters.TEXT & ~filters.COMMAND, # 过滤器配置：只处理纯文本消息（TEXT）并且过滤掉命令消息（~COMMAND）
                       # echo # 之前的回调函数名字（被注释）
                       handle_message # 现在使用把消息发给 Claude 的 `handle_message` 回调函数
                       )
    )

    print('Bot is Running...') # 在控制台打印提示，说明 Bot 开始运行了
    app.run_polling() # 开始持续向 Telegram 服务器轮询请求数据，保持机器人在线监听新消息

if __name__ == "__main__": # 如果这个文件是被直接运行的（而不是被当作模块导入的）
    main() # 那么就执行主函数 main() 启动机器人
