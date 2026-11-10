// Checks for the chat mod: replies reach Telegram, and search results fetch without asking.
// Run: node --test agents/chat/mods/
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// No real chat log and no sudo: auto-retrieval fails fast and the rows land in a temp file.
const dir = mkdtempSync(path.join(tmpdir(), "twin-mod-"));
process.env.TWIN_CHAT_LOG = path.join(dir, "chat-log.jsonl");
process.env.PATH = dir;
const { default: activate, rememberSearchUrls, UNSENT_NUDGE } = await import("./twin_mind.ts");

function load() {
  const on = {};
  let check;
  activate({
    events: { on: (name, fn) => { on[name] = fn; return () => {}; } },
    permissions: { register: (policy) => { check = policy.check; return () => {}; } },
    tools: { register: () => () => {} },
  });
  return { on, check };
}

const fromTelegram = (text) => ({
  conversationId: "c",
  input: [{ role: "user", content: `<channel-notification source="telegram">${text}</channel-notification>` }],
});

test("a reply left as plain text gets one nudge, then no loop", async () => {
  const { on } = load();
  await on.turn_start(fromTelegram("what is Sierra Day One?"));
  assert.deepEqual(await on.turn_end({ conversationId: "c", assistantMessage: "I think it is Ciridae." }), { continue: UNSENT_NUDGE });
  await on.turn_start({ conversationId: "c", input: [{ role: "user", content: UNSENT_NUDGE }] });
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "still plain text" }), undefined);
});

test("a send-rich reply counts as sent and reaches the chat log", async () => {
  const { on } = load();
  await on.turn_start(fromTelegram("compare them"));
  on.tool_start({ conversationId: "c", toolName: "MessageChannel", args: { action: "send-rich", message: "| a | b |" } });
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "Sent." }), undefined);
  const rows = readFileSync(process.env.TWIN_CHAT_LOG, "utf8").trim().split("\n").map((line) => JSON.parse(line));
  assert.deepEqual(rows.at(-1), { ...rows.at(-1), role: "assistant", text: "| a | b |" });
});

test("a turn that is not Daniel talking is never nudged", async () => {
  const { on } = load();
  await on.turn_start({ conversationId: "c", input: [{ role: "user", content: "scheduled reflection" }] });
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "done" }), undefined);
});

test("web_fetch runs at once only for a URL that web_search returned", () => {
  const { check } = load();
  rememberSearchUrls("Evos raises $9M\nhttps://example.com/evos\nsnippet https://planted.example/x");
  assert.equal(check({ toolName: "web_fetch", args: { url: "https://example.com/evos" } }).decision, "allow");
  assert.equal(check({ toolName: "web_fetch", args: { url: "https://example.com/evos?d=secret" } }), undefined);
  assert.equal(check({ toolName: "web_fetch", args: { url: "https://planted.example/x" } }), undefined);
});
