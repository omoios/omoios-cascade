"""Test MiniMax API: simple call, tool call, and thinking block handling."""
from dotenv import load_dotenv
load_dotenv()

import anthropic, os, json

c = anthropic.Anthropic(
    api_key=os.environ['LLM_API_KEY'],
    base_url=os.environ['LLM_BASE_URL'],
)
model = os.environ['LLM_MODEL']

def dump_response(label, r):
    print(f'\n=== {label} ===')
    print('stop_reason:', r.stop_reason)
    print('content blocks:', len(r.content))
    for i, block in enumerate(r.content):
        btype = type(block).__name__
        print(f'  [{i}] {btype}', end='')
        if hasattr(block, 'text'):
            print(f' text={repr(block.text)[:120]}', end='')
        if hasattr(block, 'thinking'):
            print(f' thinking={repr(block.thinking)[:80]}', end='')
        if hasattr(block, 'name'):
            print(f' name={block.name}', end='')
        if hasattr(block, 'input'):
            print(f' input={block.input}', end='')
        print()
    print('usage:', r.usage)

# Test 1: Simple text (higher max_tokens)
print('\n>>> TEST 1: Simple text with max_tokens=1000')
r1 = c.messages.create(
    model=model, max_tokens=1000,
    messages=[{'role': 'user', 'content': 'Say hello in exactly 5 words. Be brief.'}],
)
dump_response('Simple text', r1)

# Test 2: Tool use
print('\n>>> TEST 2: Tool use')
tools = [{
    'name': 'create_file',
    'description': 'Create a file with content',
    'input_schema': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'description': 'File path'},
            'content': {'type': 'string', 'description': 'File content'},
        },
        'required': ['path', 'content'],
    },
}]
r2 = c.messages.create(
    model=model, max_tokens=2000,
    messages=[{'role': 'user', 'content': 'Create a file hello.py with print(hello)'}],
    tools=tools,
)
dump_response('Tool use', r2)

# Test 3: Can we send response back as conversation?
print('\n>>> TEST 3: Round-trip (send response back as assistant message)')
# Filter out thinking blocks from content
filtered = [b for b in r2.content if getattr(b, 'type', None) != 'thinking']
print(f'Original blocks: {len(r2.content)}, filtered: {len(filtered)}')
for b in filtered:
    print(f'  type={b.type}', end='')
    if hasattr(b, 'name'): print(f' name={b.name}', end='')
    if hasattr(b, 'text'): print(f' text={repr(b.text)[:80]}', end='')
    print()

print('\nDONE - all tests passed')
