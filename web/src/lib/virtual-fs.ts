export class VirtualFS {
  private files: Map<string, string> = new Map();

  constructor() {
    this.files.set("README.md", "# Project\n\nWelcome to the sandbox.\n");
  }

  readFile(path: string): string {
    const content = this.files.get(path);
    if (content === undefined) {
      return `Error: File not found: ${path}`;
    }
    return content;
  }

  writeFile(path: string, content: string): string {
    this.files.set(path, content);
    return `File written: ${path}`;
  }

  editFile(path: string, oldText: string, newText: string): string {
    const content = this.files.get(path);
    if (content === undefined) {
      return `Error: File not found: ${path}`;
    }
    if (!content.includes(oldText)) {
      return `Error: old_text not found in ${path}`;
    }
    this.files.set(path, content.replace(oldText, newText));
    return `File edited: ${path}`;
  }

  bash(command: string): string {
    if (command.startsWith("cat ")) {
      const path = command.slice(4).trim();
      return this.readFile(path);
    }
    if (command.startsWith("ls")) {
      return Array.from(this.files.keys()).join("\n") || "(empty)";
    }
    if (command.startsWith("echo ") && command.includes(">")) {
      const parts = command.split(">");
      const content = parts[0].replace(/^echo\s+/, "").replace(/['"]/g, "").trim();
      const file = parts[1].trim();
      this.files.set(file, content + "\n");
      return "";
    }
    if (command.startsWith("mkdir")) {
      return "";
    }
    if (command.startsWith("rm ")) {
      const path = command.slice(3).trim().replace("-f ", "").replace("-rf ", "");
      this.files.delete(path);
      return "";
    }
    if (command.startsWith("python ") || command.startsWith("node ")) {
      const file = command.split(" ")[1];
      const content = this.files.get(file);
      if (!content) return `Error: File not found: ${file}`;
      return `Simulated execution of ${file}:\n[output would appear here]`;
    }
    return `Simulated: ${command}`;
  }

  executeTool(name: string, input: Record<string, string>): string {
    switch (name) {
      case "bash":
        return this.bash(input.command || "");
      case "read_file":
        return this.readFile(input.path || input.file_path || "");
      case "write_file":
        return this.writeFile(
          input.path || input.file_path || "",
          input.content || ""
        );
      case "edit_file":
        return this.editFile(
          input.path || input.file_path || "",
          input.old_text || input.old_string || "",
          input.new_text || input.new_string || ""
        );
      default:
        return `Simulated tool: ${name}`;
    }
  }

  listFiles(): string[] {
    return Array.from(this.files.keys());
  }
}
