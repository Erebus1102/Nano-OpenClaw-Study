import asyncio
import os
from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

async def test():
    load_dotenv()
    print("正在测试 Claude SDK 启动...")

    env = {
        "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL"),
        "ANTHROPIC_DEFAULT_SONNET_MODEL": os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL"),
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }

    options = ClaudeAgentOptions(
        cwd=os.getcwd(),
        env=env,
    )

    async def _make_prompt(text: str):
        yield {
            "type": "user",
            "message": {"role": "user", "content": text},
        }

    try:
        print("发送消息中...")
        async for message in query(prompt=_make_prompt("你好，请回复'测试通过'"), options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude 回复: {block.text}")
        print("测试完成！")
    except Exception as e:
        print(f"启动失败，错误详情:\n{str(e)}")

if __name__ == "__main__":
    asyncio.run(test())
