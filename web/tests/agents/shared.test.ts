import { describe, it, expect, vi } from 'vitest';
import { VirtualFS, ToolExecutor } from '@/agents/shared/tool-executor';
import type { ToolUseBlock, ContentBlock } from '@/agents/shared/types';

// Helper to build a ToolUseBlock for testing
function toolUse(name: string, input: Record<string, unknown>, id?: string): ToolUseBlock {
  return { type: 'tool_use', id: id ?? `toolu_${name}`, name, input };
}

// Helper that returns canned API responses for mocking fetch
function mockFetch(responses: Array<{ content: ContentBlock[]; stop_reason: string }>) {
  let callIndex = 0;
  global.fetch = vi.fn(() => {
    const resp = responses[callIndex++];
    return Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve({
          id: 'msg_test',
          role: 'assistant',
          content: resp.content,
          stop_reason: resp.stop_reason,
          usage: { input_tokens: 100, output_tokens: 50 },
        }),
    });
  }) as unknown as typeof fetch;
}

export { toolUse, mockFetch };

// ---------------------------------------------------------------------------
// VirtualFS
// ---------------------------------------------------------------------------
describe('VirtualFS', () => {
  it('readFile returns content of existing file', () => {
    const fs = new VirtualFS({ 'foo.txt': 'hello' });
    expect(fs.readFile('foo.txt')).toBe('hello');
  });

  it('readFile returns error for missing file', () => {
    const fs = new VirtualFS();
    expect(fs.readFile('nope.txt')).toContain('Error');
    expect(fs.readFile('nope.txt')).toContain('nope.txt');
  });

  it('writeFile creates a new file and returns confirmation', () => {
    const fs = new VirtualFS();
    const result = fs.writeFile('new.txt', 'data');
    expect(result).toContain('new.txt');
    expect(fs.readFile('new.txt')).toBe('data');
  });

  it('editFile replaces matching text', () => {
    const fs = new VirtualFS({ 'a.txt': 'foo bar baz' });
    const result = fs.editFile('a.txt', 'bar', 'qux');
    expect(result).toContain('a.txt');
    expect(fs.readFile('a.txt')).toBe('foo qux baz');
  });

  it('editFile returns error when old text not found', () => {
    const fs = new VirtualFS({ 'a.txt': 'hello' });
    expect(fs.editFile('a.txt', 'missing', 'x')).toContain('Error');
  });

  it('editFile returns error for missing file', () => {
    const fs = new VirtualFS();
    expect(fs.editFile('nope.txt', 'a', 'b')).toContain('Error');
  });

  it('bash handles cat command', () => {
    const fs = new VirtualFS({ 'f.txt': 'content' });
    expect(fs.bash('cat f.txt')).toBe('content');
  });

  it('bash handles ls command', () => {
    const fs = new VirtualFS({ 'a.txt': '1', 'b.txt': '2' });
    const output = fs.bash('ls');
    expect(output).toContain('a.txt');
    expect(output).toContain('b.txt');
  });

  it('bash handles echo redirect', () => {
    const fs = new VirtualFS();
    fs.bash("echo 'test' > out.txt");
    expect(fs.readFile('out.txt')).toContain('test');
  });

  it('bash handles mkdir silently', () => {
    const fs = new VirtualFS();
    expect(fs.bash('mkdir -p src')).toBe('');
  });

  it('listFiles returns all file paths', () => {
    const fs = new VirtualFS({ 'x.ts': '', 'y.ts': '' });
    const files = fs.listFiles();
    expect(files).toContain('x.ts');
    expect(files).toContain('y.ts');
    expect(files.length).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// ToolExecutor
// ---------------------------------------------------------------------------
describe('ToolExecutor', () => {
  it('executes bash tool', () => {
    const exec = new ToolExecutor(new VirtualFS({ 'hello.txt': 'hi' }));
    const result = exec.execute(toolUse('bash', { command: 'cat hello.txt' }));
    expect(result.content).toBe('hi');
    expect(result.is_error).toBeFalsy();
  });

  it('executes read_file tool', () => {
    const exec = new ToolExecutor(new VirtualFS({ 'data.txt': 'contents' }));
    const result = exec.execute(toolUse('read_file', { file_path: 'data.txt' }));
    expect(result.content).toBe('contents');
  });

  it('executes write_file tool', () => {
    const exec = new ToolExecutor();
    const result = exec.execute(toolUse('write_file', { file_path: 'out.txt', content: 'value' }));
    expect(result.content).toContain('out.txt');
    expect(exec.fs.readFile('out.txt')).toBe('value');
  });

  it('executes edit_file tool', () => {
    const exec = new ToolExecutor(new VirtualFS({ 'src.ts': 'const a = 1;' }));
    const result = exec.execute(
      toolUse('edit_file', { file_path: 'src.ts', old_string: 'a = 1', new_string: 'a = 2' })
    );
    expect(result.content).toContain('src.ts');
    expect(exec.fs.readFile('src.ts')).toBe('const a = 2;');
  });

  it('returns placeholder for unknown tool', () => {
    const exec = new ToolExecutor();
    const result = exec.execute(toolUse('unknown_tool', {}));
    expect(result.content).toContain('not implemented');
  });

  it('custom handler registration overrides default', () => {
    const exec = new ToolExecutor();
    const handler = vi.fn(() => 'custom result');
    exec.registerTool('my_tool', handler);
    const result = exec.execute(toolUse('my_tool', { key: 'val' }));
    expect(result.content).toBe('custom result');
    expect(handler).toHaveBeenCalledWith({ key: 'val' });
  });

  it('custom handler takes priority over built-in tool', () => {
    const exec = new ToolExecutor();
    exec.registerTool('bash', () => 'intercepted');
    const result = exec.execute(toolUse('bash', { command: 'ls' }));
    expect(result.content).toBe('intercepted');
  });

  it('returns is_error when handler throws', () => {
    const exec = new ToolExecutor();
    exec.registerTool('fail', () => {
      throw new Error('boom');
    });
    const result = exec.execute(toolUse('fail', {}));
    expect(result.is_error).toBe(true);
    expect(result.content).toContain('boom');
  });
});
