"""Diagnose why planner.run() hangs: replicate the exact first LLM call."""

import asyncio, os, time, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import anthropic


async def main():
    api_key = os.environ["LLM_API_KEY"]
    base_url = os.environ["LLM_BASE_URL"]
    model = os.environ.get("MODEL_DEFAULT", os.environ.get("LLM_MODEL", "MiniMax-M2.5-highspeed"))

    print(f"Model: {model}")
    print(f"Base URL: {base_url}")
    print(f"API Key: {api_key[:8]}...{api_key[-4:]}")

    client = anthropic.AsyncAnthropic(
        api_key=api_key,
        base_url=base_url,
        timeout=120.0,  # 2 minute timeout
    )

    # Load the actual planner system prompt
    prompt_path = Path(__file__).parent / "src" / "harness" / "prompts" / "planner.md"
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    print(f"\nSystem prompt: {len(system_prompt)} chars, ~{len(system_prompt) // 4} tokens")

    # Test 1: Full system prompt + simple instruction (same as harness)
    print("\n>>> TEST 1: Full planner system prompt + instruction")
    print("    (This replicates the exact call the harness makes)")
    system_blocks = [{"type": "text", "text": system_prompt}]
    messages = [
        {"role": "user", "content": "Create a file called hello.py with a function greet(name) that returns Hello name"}
    ]

    # Load tool schemas from runner
    try:
        from harness.runner import PLANNER_TOOL_SCHEMAS

        tools = PLANNER_TOOL_SCHEMAS
        print(f"    Tools: {len(tools)} planner tools loaded")
    except Exception as e:
        print(f"    Could not load planner tools: {e}")
        tools = None

    t0 = time.time()
    try:
        kwargs = {
            "model": model,
            "max_tokens": 8192,
            "system": system_blocks,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        print(f"    Calling API at {time.strftime('%H:%M:%S')}...")
        response = await client.messages.create(**kwargs)
        elapsed = time.time() - t0

        print(f"    Response received in {elapsed:.1f}s")
        print(f"    stop_reason: {response.stop_reason}")
        print(f"    content blocks: {len(response.content)}")
        for i, block in enumerate(response.content):
            btype = type(block).__name__
            print(f"      [{i}] {btype}", end="")
            if hasattr(block, "text"):
                print(f" text={repr(block.text)[:200]}", end="")
            if hasattr(block, "thinking"):
                print(f" thinking={repr(block.thinking)[:100]}", end="")
            if hasattr(block, "name"):
                print(f" name={block.name}", end="")
            if hasattr(block, "input"):
                import json

                print(f" input={json.dumps(block.input)[:200]}", end="")
            print()
        print(f"    usage: {response.usage}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"    ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}")

    # Test 2: Short system prompt for comparison
    print("\n>>> TEST 2: Short system prompt (control test)")
    t0 = time.time()
    try:
        kwargs2 = {
            "model": model,
            "max_tokens": 2000,
            "system": [{"type": "text", "text": "You are a helpful coding assistant."}],
            "messages": [
                {
                    "role": "user",
                    "content": "Create a file called hello.py with a function greet(name) that returns Hello name",
                }
            ],
        }
        if tools:
            kwargs2["tools"] = tools

        print(f"    Calling API at {time.strftime('%H:%M:%S')}...")
        response2 = await client.messages.create(**kwargs2)
        elapsed = time.time() - t0

        print(f"    Response received in {elapsed:.1f}s")
        print(f"    stop_reason: {response2.stop_reason}")
        print(f"    content blocks: {len(response2.content)}")
        for i, block in enumerate(response2.content):
            btype = type(block).__name__
            print(f"      [{i}] {btype}", end="")
            if hasattr(block, "text"):
                print(f" text={repr(block.text)[:200]}", end="")
            if hasattr(block, "name"):
                print(f" name={block.name}", end="")
            if hasattr(block, "input"):
                import json

                print(f" input={json.dumps(block.input)[:200]}", end="")
            print()
        print(f"    usage: {response2.usage}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"    ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}")

    print("\nDONE")


asyncio.run(main())
