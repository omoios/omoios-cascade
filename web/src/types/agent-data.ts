export interface AgentVersion {
  id: string;
  filename: string;
  title: string;
  subtitle: string;
  loc: number;
  tools: string[];
  newTools: string[];
  coreAddition: string;
  keyInsight: string;
  classes: { name: string; startLine: number; endLine: number }[];
  functions: { name: string; signature: string; startLine: number }[];
  layer: "tools" | "planning" | "memory" | "concurrency" | "collaboration";
  source: string;
}

export interface VersionDiff {
  from: string;
  to: string;
  newClasses: string[];
  newFunctions: string[];
  newTools: string[];
  locDelta: number;
}

export interface DocContent {
  version: string;
  locale: "en" | "zh" | "ja";
  title: string;
  content: string; // raw markdown
}

export interface VersionIndex {
  versions: AgentVersion[];
  diffs: VersionDiff[];
}
