# !/usr/bin/env python3
# 指定这是一个 python3 脚本，在 Unix 系统中用来指明执行该脚本的解释器

import os # 导入 os 模块，用于访问操作系统接口，例如读取环境变量
import json # 导入 json 模块，用于处理 JSON 数据的读写
import asyncio # 导入 asyncio 模块，用于编写异步代码，处理异步
import time # 导入 time 模块，用于处理时间相关的功能，例如计算任务执行时间
import aiosqlite # 导入 aiosqlite 模块，用于异步操作
import uuid # 导入 uuid 模块，用于生成唯一的任务 ID
import logging # 导入 logging 模块，用于记录日志信息，调试和监控
from pathlib import Path # 导入 Path 对象，用于处理文件路径，比 os.path 更面向对象
from dotenv import load_dotenv # 从 dotenv 库中导入 load_dotenv，用于从 .env 文件加载环境变量
from telegram import Update # 从 telegram 库导入 Update，代表 telegram 服务器发来的一个更新（比如新消息）
from typing import Any # 从 typing 导入 Any，用于类型注解，表示任意类型
from telegram.ext import Application, CommandHandler, MessageHandler, filters # 从 telegram.ext 导入构建机器人的核心类
from datetime import datetime, timezone, timedelta # 从 datetime 模块导入 datetime 和 timezone，用于处理日期和时间，特别是 UTC 时间
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter
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

logger = logging.getLogger(__name__)

# ===========================================================================
# 配置
# ===========================================================================

load_dotenv() # 加载当前目录下的 .env 文件，将其中的键值对注入到操作系统的环境变量中
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"] # 从环境变量中获取 Telegram 机器人的 Token
ANTHROPIC_AUTH_TOKEN = os.environ["ANTHROPIC_AUTH_TOKEN"] # 从环境变量中获取 Anthropic (Claude) 的 API 密钥
ANTHROPIC_BASE_URL = os.environ["ANTHROPIC_BASE_URL"] # 从环境变量获取请求 Claude API 的基础 URL
ANTHROPIC_DEFAULT_SONNET_MODEL = os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] # 从环境变量获取默认使用的模型名
OWNER_ID = int(os.environ["OWNER_ID"]) # 从环境变量获取机器人的拥有者 ID，并转换成整数类型
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "60")) # 从环境变量获取调度器检查任务的时间间隔，默认为 60 秒，并转换成整数类型
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Ape")

BASE_DIR = Path(__file__).resolve().parent # 获取当前脚本文件所在的绝对目录路径作为 BASE_DIR
WORKSPACE_DIR = BASE_DIR/"workspace" # 在 BASE_DIR 下拼接出 workspace 文件
CONVERSATION_DIR = WORKSPACE_DIR/"conversations" # 在 WORKSPACE_DIR 下拼接出 conversations 文件夹路径，作为存放对话记录的目录
DATA_DIR = BASE_DIR/"data" # 在 BASE_DIR 下拼接出 data 文件夹路径，作为存放数据的目录
STORE_DIR = BASE_DIR/"store" # 在 BASE_DIR 下拼接出 store 文件夹路径，作为存放持久化数据的目录
DB_PATH = STORE_DIR/"nanoclaw.db" # 在 store 目录下定义一个 nanoclaw.db
STATE_FILE = DATA_DIR/"state.json" # 在 data 目录下定义一个 state.json 文件路径，用于存储 Agent 的状态数据

_agent_lock = asyncio.Lock() # 定义一个全局的异步锁对象，用于控制对 Agent 运行的访问，确保同一时间只有一个 Agent 实例在运行，避免资源冲突

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

# ===========================================================================
# 调度器
# ===========================================================================
async def check_due_tasks(bot,db_path:str)->None: # 定义一个异步函数，用于检查是否有到期的任务需要执行，接收 bot 实例作为参数
    try:
        tasks = await get_due_tasks(db_path)
    except Exception:
        logger.exception("Failed to query due tasks")
        return

    for task in tasks:
        try:
            await execute_task(task, bot, db_path)
        except Exception:
            logger.exception("Failed to execute task %s", task["id"])

async def execute_task(task:str, bot:Any, db_path:str)->None: # 定义一个异步函数，用于执行具体的任务，接收任务 ID、聊天 ID 和提示词作为参数
    task_id = task["id"] 
    task_chat_id = task["chat_id"]  # Use chat_id from task, not global OWNER_ID
    prompt = task["prompt"]
    logger.info("Executing task %s for chat %s: %s", task, task_chat_id, prompt[:80])

    wrapped_prompt = f"You are executing a scheduled task. You MUST use the send_message tool to notify the user in Telegram. Task: {prompt}"
    notify_state = {"sent": False}

    start = time.monotonic()
    try:
        result = await run_task_agent(wrapped_prompt, bot, task_chat_id, db_path, notify_state)

        # Fallback to avoid silent runs when the model forgets to call send_message.
        if not notify_state["sent"]:
            await bot.send_message(chat_id=task_chat_id, text=f"⏰ 定时提醒：{prompt}")

        duration_ms = int((time.monotonic() - start) * 1000)
        await log_task_run(db_path, task_id, duration_ms, "success", result=result)
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        await log_task_run(db_path, task_id, duration_ms, "error", error=str(e))
        result = f"Error: {e}"

    # Calculate next_run
    stype = task["schedule_type"]
    svalue = task["schedule_value"]
    now = datetime.now(timezone.utc)

    if stype == "cron":
        next_run = croniter(svalue, now).get_next(datetime).isoformat()
        await update_task_after_run(db_path, task_id, result, next_run, "active")
    elif stype == "interval":
        next_run = (now + timedelta(milliseconds=int(svalue))).isoformat()
        await update_task_after_run(db_path, task_id, result, next_run, "active")
    elif stype == "once":
        await update_task_after_run(db_path, task_id, result, None, "completed")
    else:
        logger.warning("Unknown schedule_type %s for task %s", stype, task_id)

async def setup_scheduler(bot) -> AsyncIOScheduler: # 定义一个异步函数，用于设置调度器，接收 bot 实例作为参数
    scheduler = AsyncIOScheduler() # 创建一个 AsyncIOScheduler 实例，使用 asyncio 事件循环
    scheduler.add_job(check_due_tasks, "interval", seconds=SCHEDULER_INTERVAL, args=[bot, str(DB_PATH)]) # 添加一个定时任务，每 60 秒执行一次 check_due_tasks 函数，传入 bot 作为参数
    return scheduler # 返回配置好的调度器实例

# ===========================================================================
# Telegram 消息处理
# ===========================================================================


def is_owner(update:Update) -> bool: # 定义一个辅助函数，用于检查发出命令的用户是否是机器人的拥有者
    return update.effective_user.id == OWNER_ID # 检查 update 中的用户信息，如果存在且 ID 匹配 OWNER_ID 就返回 True，否则返回 False

async def clear(update:Update, context): # 定义处理 /clear 命令的异步回调函数，接收 update 和 context 两个参数
    """
    处理/clear
    """
    if not is_owner(update): # 调用辅助函数检查发出命令的用户是否是机器人的拥有者
        return
    clear_session_id() # 如果是拥有者，调用之前定义的函数清除 Agent 会话 ID，重置会话状态
    await update.message.reply_text("会话已清除") # 如果不是，回复一个权限不足的消息

async def end(update:Update, context): # 定义处理 /end 命令的异步回调函数
    """
    处理/end命令
    """
    print("============") # 打印分隔符
    print(update) # 打印 update 详细信息
    await update.message.reply_text( # 异步调用，向用户回复文本消息
        "我要清空所有的消息" # 回复的内容
    )

# =========================================================================
# 1. 添加内置对应工具
# 2. 添加MCP工具
# =========================================================================

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run TEXT,
    last_run TEXT,
    last_result TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON scheduled_tasks (next_run);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks (status);
CREATE TABLE IF NOT EXISTS task_run_logs (                                                                                                                          
      id INTEGER PRIMARY KEY AUTOINCREMENT,                                                                                                                           
      task_id TEXT NOT NULL,                                                                                                                                          
      run_at TEXT NOT NULL,                                                                                                                                           
      duration_ms INTEGER,                                                                                                                                            
      status TEXT,                                                                                                                                                    
      result TEXT,                                                                                                                                                    
      error TEXT                                                                                                                                                      
  );
"""



async def init_db(): # 定义一个异步函数用于初始化数据库，创建必要的表格
    async with aiosqlite.connect(str(DB_PATH)) as db: 
        await db.executescript(_CREATE_TABLES) # 执行预定义的 SQL 脚本，创建 scheduled_tasks 表和相关索引
        await db.commit() # 提交事务，确保表格创建成功  

async def create_task(chat_id:int, prompt:str, stype:str, svalue:str, next_run:str) -> str: # 定义一个异步函数用于创建新的定时任务，接收聊天 ID、提示词、调度类型、调度值和下次运行时间作为参数
    task_id = uuid.uuid4().hex[:8]
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "INSERT INTO scheduled_tasks (id, chat_id, prompt, schedule_type, schedule_value, next_run, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                (task_id, chat_id, prompt, stype, svalue, next_run, datetime.now(timezone.utc).isoformat()))
        await db.commit()
    return task_id # 返回新创建的任务 ID

async def get_all_tasks(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM scheduled_tasks")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_due_tasks(db_path: str) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' AND next_run <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_task_status(db_path: str, task_id: str, status: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE scheduled_tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_task(db_path: str, task_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_task_after_run(db_path: str, task_id: str, last_result: str, next_run: str | None, status: str = "active") -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE scheduled_tasks SET last_run = ?, last_result = ?, next_run = ?, status = ? WHERE id = ?",
            (now, last_result, next_run, status, task_id),
        )
        await db.commit()


async def log_task_run(db_path: str, task_id: str, duration_ms: int, status: str, result: str | None = None, error: str | None = None) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, datetime.now(timezone.utc).isoformat(), duration_ms, status, result, error),
        )
        await db.commit()

CLAUDE_MD_TEMPALTE= f"""
# {ASSISTANT_NAME} - 个人 AI 助手

你是 **{ASSISTANT_NAME}**，一个运行在 Telegram 上的个人 AI 助手。

## 核心能力
- **文件管理**：你可以阅读、编写和编辑工作区内的文件。
- **指令执行**：你可以运行 Bash 命令。
- **网络搜索**：你可以进行网页搜索。
- **消息推送**：你可以通过 `mcp__nanoclaw__send_message` 向用户发送消息。
- **任务调度**：你可以通过 `mcp__nanoclaw__schedule_task` 安排任务。
- **任务管理**：你可以通过 `list_tasks`（列出）、`pause_task`（暂停）、`resume_task`（恢复）和 `cancel_task`（取消）来管理任务。

## 任务调度指南
当用户要求你安排日程或提醒时：
- **定时任务 (Cron)**：对于周期性模式使用 `cron` 类型（例如 `"0 9 * * 1"` 表示每周一上午 9 点）。
- **间隔任务 (Interval)**：对于定期重复的任务使用 `interval` 类型（数值单位为毫秒，例如 `"3600000"` 表示每小时一次）。
- **单次任务 (Once)**：对于一次性任务使用 `once` 类型（数值为 ISO 8601 格式的时间戳）。

## 记忆系统
- **长期记忆**：本文件 (`CLAUDE.md`) 是你存储偏好和重要事实的长期记忆库。
- **聊天记录**：`conversations/` 文件夹按日期（`YYYY-MM-DD.md`）存储你的历史对话。
- **回忆检索**：你可以搜索 `conversations/` 文件夹来回顾过去的讨论。
- **动态更新**：随时使用写入/编辑工具更新此文件，以记录重要信息。

## 对话历史管理
你的对话记录存储在 `conversations/` 文件夹中：
- 每个文件以日期命名（如 `2024-01-15.md`）。
- 使用 **Glob** 和 **Grep** 命令搜索过去的对话。
- *示例*：使用 `Grep pattern="天气" path="conversations/"` 来查找与天气相关的聊天记录。

## 用户偏好
（在此处添加你学习到的用户偏好）
"""

def ensure_workspace(): # 定义一个函数用于确保工作目录存在
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True) # 创建 workspace 目录，如果已经存在则不报错
    CONVERSATION_DIR.mkdir(parents=True, exist_ok=True) # 创建 conversations 目录，如果已经存在则不报错

    claude_md = WORKSPACE_DIR/"CLAUDE.md" # 定义 CLAUDE.md 文件的路径
    if not claude_md.exists(): # 如果 CLAUDE.md 文件不存在
        claude_md.write_text(CLAUDE_MD_TEMPALTE) # 将预定义的 CLAUDE.md 模板内容写入该文件

# =========================================================================
# 对话归档
# =========================================================================
def archive_conversation(user_message:str, assistant_response:str)->None: # 定义一个函数用于归档对话，接收一个对话列表作为参数
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d") # 获取当前日期，并格式化为 YYYY-MM-DD 的字符串
    filepath = CONVERSATION_DIR/f"{today}.md" # 定义当天的对话文件路径，命名为当天日期的 Markdown 文件

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") # 获取当前的 UTC 时间戳，格式化为字符串
    entry = f"""## {timestamp}
**User**: {user_message}
**Ape**: {assistant_response}
---
"""

    if filepath.exists(): # 如果当天的对话文件已经存在
        content = filepath.read_text(encoding="utf-8") + entry # 读取现有的对话内容
    else:
        content = f"# 对话记录 - {today}\n\n" + entry # 如果文件不存在，创建新的内容，包含标题和当前对话
    filepath.write_text(content, encoding="utf-8") # 将更新后的内容写回文件中，完成对话归档


def load_session_id() -> str: # 定义一个函数用于加载 Agent 会话 ID
    if STATE_FILE.exists(): # 如果 state.json 文件存在
        with open(STATE_FILE, "r") as f: # 打开文件进行读取
            data = json.load(f) # 解析 JSON 数据
            return data.get("session_id") # 返回其中的 session_id 字段，如果没有
    return None # 修改：如果文件不存在或 ID 为空，返回 None

def save_session_id(session_id:str)-> None :# 定义一个函数用于保存 Agent 会话 ID
    DATA_DIR.mkdir(parents=True, exist_ok=True) # 确保 data 目录存在，如果不存在就创建
    with open(STATE_FILE, "w") as f: # 打开 state.json 文件
        json.dump({"session_id": session_id}, f) # 将 session_id 以 JSON 格式写入文件中

def clear_session_id(): # 定义一个函数用于清除 Agent 会话 ID
    if STATE_FILE.exists(): # 如果 state.json 文件存在
        STATE_FILE.unlink() # 删除该文件

def create_mcp_server_tools(bot, chat_id:int) -> list: # 定义函数用于创建工具列表，接收 bot 实例和 chat_id 参数
    @tool("send_message","发送消息给用户",{"text":str}) # 使用 @tool 装饰器把下面的函数变成一个 Agent 可以调用的工具，并定义了工具名称、描述和它接受的参数类型
    async def send_message(args) -> dict[str, Any]: # 定义处理发送消息逻辑的异步函数，它将收到由 Agent 传入的 args 字典
        # 这一行是主动给用户发消息
        await bot.send_message(chat_id = chat_id, text = args["text"]) # 使用 python-telegram-bot 的接口向指定的 chat_id 发送文本消息
        # 返回值是：告诉Agent发送消息的结果
        return { # 将执行的结果以特定格式封装后返回给 Agent，作为工具执行成功后的反馈
            "content":[
                {
                    "type":"text", # 声明反馈内容为文本
                    "text":f"已向用户发送消息：{(args['text'])}", # 具体的反馈文本内容，告知 Agent 消息已发出
                }
            ]
        }
    
    @tool(
        "schedule_task",
        "Schedule a task. schedule_type: 'cron', 'interval', or 'once'. schedule_value: cron expression, milliseconds, or ISO timestamp.",
        {"prompt": str, "schedule_type": str, "schedule_value": str},
    )
    async def schedule_task(args: dict[str, Any]) -> dict[str, Any]:
        stype = args["schedule_type"]
        svalue = args["schedule_value"]
        now = datetime.now(timezone.utc)

        if stype == "cron":
            next_run = croniter(svalue, now).get_next(datetime).isoformat()
        elif stype == "interval":
            next_run = (now + timedelta(milliseconds=int(svalue))).isoformat()
        elif stype == "once":
            next_run = svalue
        else:
            return {
                "content": [{"type": "text", "text": f"Unknown schedule_type: {stype}"}],
                "is_error": True,
            }

        task_id = await create_task(chat_id, args["prompt"], stype, svalue, next_run)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Task {task_id} scheduled. Next run: {next_run}",
                }
            ]
        }
    
    @tool("list_tasks", "List all scheduled tasks", {})
    async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
        tasks = await get_all_tasks(str(DB_PATH))
        if not tasks:
            return {"content": [{"type": "text", "text": "No scheduled tasks."}]}
        lines = [f"- [{t['id']}] {t['status']} | {t['schedule_type']}({t['schedule_value']}) | {t['prompt'][:60]}" for t in tasks]
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool("pause_task", "Pause a scheduled task", {"task_id": str})
    async def pause_task(args: dict[str, Any]) -> dict[str, Any]:
        ok = await update_task_status(str(DB_PATH), args["task_id"], "paused")
        msg = f"Task {args['task_id']} paused." if ok else f"Task {args['task_id']} not found."
        return {"content": [{"type": "text", "text": msg}]}

    @tool("resume_task", "Resume a paused task", {"task_id": str})
    async def resume_task(args: dict[str, Any]) -> dict[str, Any]:
        ok = await update_task_status(str(DB_PATH), args["task_id"], "active")
        msg = f"Task {args['task_id']} resumed." if ok else f"Task {args['task_id']} not found."
        return {"content": [{"type": "text", "text": msg}]}

    @tool("cancel_task", "Cancel and delete a scheduled task", {"task_id": str})
    async def cancel_task(args: dict[str, Any]) -> dict[str, Any]:
        ok = await delete_task(str(DB_PATH), args["task_id"])
        msg = f"Task {args['task_id']} cancelled." if ok else f"Task {args['task_id']} not found."
        return {"content": [{"type": "text", "text": msg}]}

    return [send_message,schedule_task,list_tasks,pause_task,resume_task,cancel_task] # 返回一个包含所有工具函数的列表，供 Agent 使用

async def _make_prompt(text:str): # 定义一个内部异步生成器函数，用于构造发送给 agent 的消息格式
    yield { # yield 抛出一个字典格式的消息
        "type":"user", # 指定消息类型为用户消息
        "message":{"role":"user","content":text}, # 内部的 message 对象，定义了发出该消息的角色(user)和内容
    }

async def run_agent(prompt:str,bot:Any, chat_id:int) -> str: # 定义一个内部函数用于运行 agent，接收提示词、bot 实例和 chat_id
    async with _agent_lock:
        return await _run_agent_inner(prompt, bot, chat_id) # 通过一个锁来确保同一时间只有一个 agent 实例在运行，避免资源冲突

async def _run_agent_inner(prompt:str,bot:Any,chat_id:int) -> str: # 定义真正运行 agent 的内部函数
    # 1. 准备环境变量
    env = {
        "ANTHROPIC_AUTH_TOKEN": ANTHROPIC_AUTH_TOKEN,
        "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": ANTHROPIC_DEFAULT_SONNET_MODEL,
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }

    # 2. 准备工具
    tools = create_mcp_server_tools(bot, chat_id)

    async def _allow_all_tools(*_):         # 定义一个简单的权限函数，允许 Agent 使用所有工具
        return PermissionResultAllow(behavior="allow")
    
    # 3. 创建 MCP 服务器实例
    mcp_server = create_sdk_mcp_server(name="nanoclaw", tools=tools)

    # 4. 配置 Options
    options = ClaudeAgentOptions(
        cwd = str(WORKSPACE_DIR),
        setting_sources = ["project"],
        env = env,
        allowed_tools = [
            "Read", 
            "Write", 
            "Edit", 
            "Glob", 
            "Grep", 
            "Bash", 
            "WebSearch", 
            "WebFetch",
            "mcp__nanoclaw__schedule_task",
            "mcp__nanoclaw__list_tasks",
            "mcp__nanoclaw__pause_task",
            "mcp__nanoclaw__resume_task",
            "mcp__nanoclaw__cancel_task",
            "mcp__nanoclaw__send_message"
        ],
        # agents = {
        #     "coder": AgentDefinition(
        #         description = "专业程序员",
        #         prompt = "你是一个经验丰富的Python开发者",
        #         tools = ["Read","Write","Bash"],
        #     )
        # },
        permission_mode = 'bypassPermissions',
        can_use_tool = _allow_all_tools,
        mcp_servers = {
            "nanoclaw": mcp_server
        }
    )
    # 5. 恢复会话逻辑
    session_id = load_session_id()
    if session_id and session_id != "None":
        options.resume = session_id

    response_parts:list[str] = []
    try:
        async for message in query(prompt=_make_prompt(prompt),options=options):
            if isinstance(message, ResultMessage):
                save_session_id(message.session_id)
                if message.result:
                    print("Claude 最终结果：", message.result)
                    response_parts.append(message.result)
    except Exception as e:
        print("运行 Agent 时发生错误：", e)
    return "\n".join(response_parts) or "完成"

# 注意：这是个独立的、平级的函数，专门给后台调度器用的，无 session 恢复
async def run_task_agent(prompt: str, bot: Any, chat_id: int, db_path: str, notify_state: dict[str, bool] | None = None) -> str:
    """ 
    Run agent for scheduled tasks — no session resume
    """
    # 修正1：_create_tools 改为create_mcp_server_tools
    tools = create_mcp_server_tools(bot,chat_id)
    mcp_server = create_sdk_mcp_server(name="nanoclaw",tools=tools)
    # 修正2：ANTHROPIC_API_KEY 改为ANTHROPIC_AUTH_TOKEN
    env = {"ANTHROPIC_API_KEY":ANTHROPIC_AUTH_TOKEN}
    if ANTHROPIC_BASE_URL:
        env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
    options = ClaudeAgentOptions(
        cwd=str(WORKSPACE_DIR),
        setting_sources=["project"],
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch",
            "mcp__nanoclaw__schedule_task",
            "mcp__nanoclaw__list_tasks",
            "mcp__nanoclaw__pause_task",
            "mcp__nanoclaw__resume_task",
            "mcp__nanoclaw__cancel_task",
            "mcp__nanoclaw__send_message"],
        permission_mode="bypassPermissions",
        mcp_servers={"nanoclaw": mcp_server},
        env=env,
    )
    response_parts: list[str] =[]
    try:
        async for message in query(prompt=_make_prompt(prompt), options=options):
            if isinstance(message, ResultMessage):
                if message.result:
                    response_parts.append(message.result)
    except Exception:
        if not response_parts:
            logger.exception("Task agent error")
            return "Task execution failed."
        logger.debug("Ignoring query cleanup error", exc_info=True)

    return "".join(response_parts) or "Task completed."

async def handle_message(update:Update, context): # 定义处理所有非命令普通文本消息的异步回调函数
    if not update.message or not update.message.text: # 如果收到的是空消息或者不是文本消息
        return # 直接退出不处理
    response = await run_agent(update.message.text, context.bot, update.effective_chat.id) # 获取 Agent 回复

    archive_conversation(update.message.text, response) # 将用户消息和 Agent 回复归档到文件中

    max_length = 4096 # 定义 Telegram 单条消息的最大长度限制
    for i in range(0, len(response), max_length): # 对长消息按 max_length 进行切片遍历
        await update.message.reply_text(response[i:i+max_length]) # 发送回用户

async def post_init(app:Application) -> None: # 定义一个异步函数，用于在 Application 初始化后执行一些操作
    scheduler = await setup_scheduler(app.bot) # 设置调度器
    scheduler.start() # 启动调度器
    print("Scheduler started") # 打印日志，确认调度器已启动

async def _prepare() -> None: # 定义一个准备函数，当前没有具体实现，可以用于后续添加初始化逻辑
    for d in (WORKSPACE_DIR, STORE_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True) # 确保这些目录存在，如果不存在就创建

        await init_db()
        ensure_workspace() 

def main(): # 定义主函数

    asyncio.run(_prepare()) # 运行准备函数，进行必要的初始化操作

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build() # 构建 Application 实例

    app.add_handler(CommandHandler('start',start)) # 注册命令处理器
    app.add_handler(CommandHandler('end',end))
    app.add_handler(CommandHandler('clear',clear))

    app.add_handler( # 注册消息处理器
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print('Bot is Running...') # 在控制台打印提示
    app.run_polling() # 开始轮询

if __name__ == "__main__":
    main()
