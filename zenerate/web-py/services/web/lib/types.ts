export interface Agent {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  greeting: string;
  voice_id: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ScenarioStep {
  text: string;
  raw: string;
  quirks: { tag: string; value: string }[];
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  persona: string;
  steps: ScenarioStep[];
  assertions: string[];
  rubric: Record<string, number>;
  compatible_agents: string[];
  created_at: string;
  updated_at: string;
}

export interface JudgeScore {
  id: string;
  field: string;
  score: number;
  reasoning: string;
  passed: boolean;
}

export interface TranscriptTurn {
  speaker: string;
  text: string;
  ts_ms?: number;
  quirks?: { tag: string; value: string }[];
}

export interface TestResult {
  id: string;
  passed: boolean;
  transcript: TranscriptTurn[];
  assertion_results: Record<string, boolean>;
  scores: JudgeScore[];
  created_at: string;
}

export interface TestRun {
  id: string;
  agent: string;
  agent_name?: string;
  scenario: string;
  scenario_name: string;
  mode: "text" | "audio";
  status: "queued" | "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  observer_url?: string;
  result?: TestResult;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
