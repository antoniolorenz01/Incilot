// Explanations of each piece for an outsider: what it does in plain words and what
// it is built with. Shown by <Explain topic="…" />.

export type Topic = { title: string; body: string; stack: string[] };

export const TOPICS = {
  simulate: {
    title: "A real shop, broken on purpose",
    body:
      "The shop is four microservices (shop, users, inventory and payments) with simulated customer traffic. " +
      "Each fault is really injected: a deploy with a bug, a config change, a locked database. " +
      "Innocent commits are added as decoys too, so the agent cannot get it right by chance.",
    stack: ["Python", "FastAPI", "Postgres", "Redis", "Docker Compose", "Git"],
  },
  health: {
    title: "What an on-call team would see",
    body:
      "Every service publishes metrics (orders, errors, response times) that are stored every few seconds. " +
      "These charts cover the last 15 minutes: when we break something, it shows here before anyone explains it.",
    stack: ["Prometheus", "Grafana"],
  },
  agent: {
    title: "An agent that investigates, not a chatbot",
    body:
      "At each step the language model decides what to look at: metrics, logs, code changes, the documentation or the database. " +
      "It reads the results and carries on until it has a cause backed by evidence. All its tools are read-only, " +
      "and it has a limit on steps and tokens.",
    stack: ["LangGraph", "OpenAI", "fallback model", "tool calling"],
  },
  stream: {
    title: "Live, and nothing gets lost",
    body:
      "The investigation runs in a separate process. Each step is published to a queue and arrives here instantly. " +
      "If the connection drops, it resumes from the last step seen.",
    stack: ["Redis Streams", "Server-Sent Events", "Next.js"],
  },
  triage: {
    title: "First, what changed (no AI)",
    body:
      "Before using the model, every indicator is compared with the previous hour and new logs are grouped. " +
      "So the agent starts out knowing where to look, which is cheaper and faster.",
    stack: ["Prometheus", "Loki"],
  },
  query_metrics: {
    title: "Metrics",
    body: "Numbers over time: orders per minute, errors, latency, database connections.",
    stack: ["Prometheus", "PromQL"],
  },
  search_logs: {
    title: "Logs",
    body:
      "What each service writes. Repeated messages are grouped by pattern, " +
      "so the agent sees 3 distinct problems rather than 3,000 lines.",
    stack: ["Loki", "Alloy"],
  },
  git: {
    title: "Code changes",
    body:
      "The agent checks what was deployed recently and what each commit changed. " +
      "Careful: there are innocent commits too, and blaming one counts as a mistake.",
    stack: ["Git (read-only)"],
  },
  rag: {
    title: "RAG: searching the documentation",
    body:
      "The company's runbooks, code and config are split into fragments and turned into vectors. " +
      "When the agent asks something, the fragments closest in meaning are retrieved for it to read. " +
      "The search method (vectors, keywords, hybrid, with a reranker) was chosen by measuring which finds best.",
    stack: ["embeddings", "pgvector", "LangChain"],
  },
  query_database: {
    title: "The database",
    body:
      "Read-only SQL queries, validated before they run. Useful to spot, for example, " +
      "a session that is holding a table locked.",
    stack: ["Postgres", "validated SQL"],
  },
  approval: {
    title: "Nothing is touched without a human",
    body:
      "The agent proposes an action and pauses, saved in the database. It can wait for hours: " +
      "when you decide, it resumes exactly where it stopped. ‘Approve’ applies its proposal; ‘Amend’ applies " +
      "your version if you think it picked the wrong action or target; ‘Reject’ applies nothing. " +
      "The decision is recorded.",
    stack: ["LangGraph interrupt", "Postgres checkpoints", "structured output"],
  },
  verification: {
    title: "Verify, don't assume",
    body:
      "After acting we wait a minute and measure the shop again. " +
      "It only counts as resolved if errors and response times are back to normal.",
    stack: ["Prometheus", "execution connectors"],
  },
  evals: {
    title: "How do we know the agent is any good?",
    body:
      "Every fault has a known right answer. Running all the faults several times measures " +
      "how often the agent picks the action that fixes the problem, and whether it blames a decoy.",
    stack: ["custom evals", "scenarios with known answers"],
  },
  history: {
    title: "Incident memory",
    body: "Every investigation is saved with its diagnosis, the decision and whether it was resolved. You can replay it in full.",
    stack: ["Postgres"],
  },
  tech: {
    title: "Technical mode",
    body:
      "Shows what is normally hidden: each tool's real name, how long each step took, " +
      "the tokens used and the diagnosis exactly as the model returns it (JSON). " +
      "Switched off, everything is explained in plain words. Turn it on if you are technical or want to see how it works inside; " +
      "leave it off when demoing to someone who isn't. You can change it at any time.",
    stack: [],
  },
  dry_run: {
    title: "Dry run",
    body:
      "Goes through the whole flow without calling the AI: the diagnosis is a fixed example and the action is not really applied. " +
      "It is quick and costs nothing. Useful to see how the screen works; " +
      "to watch the agent really investigate, leave it off.",
    stack: [],
  },
  scenario: {
    title: "Fault types",
    body:
      "Typical incidents at a real company, grouped by origin: a deploy with a bug, a config change, " +
      "an infrastructure problem or an external provider going down. The agent never knows which one you picked.",
    stack: [],
  },
  confidence: {
    title: "Confidence",
    body:
      "How sure the agent claims to be, based on how much of the evidence it found points to the same cause. " +
      "The model states it itself, so it is only a guide: that is why your approval and the later verification exist.",
    stack: [],
  },
  evidence: {
    title: "Evidence",
    body:
      "What the agent saw with its tools that led to its conclusion. Every point should be checkable " +
      "in the console: if something doesn't appear there, be sceptical.",
    stack: [],
  },
} satisfies Record<string, Topic>;

export type TopicId = keyof typeof TOPICS;

/** What to look at at each moment, and in which columns (0 to 3, one per step). */
export const FOCUS: Record<string, { columns: number[]; hint: string }> = {
  idle: { columns: [0], hint: "Start here: pick what to break" },
  breaking: { columns: [0], hint: "Watch ‘Shop health’: customers notice" },
  investigating: { columns: [1], hint: "Click a query to see what it found" },
  awaiting_approval: { columns: [2], hint: "Read the evidence and decide below" },
  executing: { columns: [0, 3], hint: "Watch the shop return to normal" },
  done: { columns: [3], hint: "Was it resolved? Did the agent get it right?" },
  error: { columns: [1], hint: "The error details are in the console" },
};
