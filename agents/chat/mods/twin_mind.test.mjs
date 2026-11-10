// Checks for the chat mod: replies reach Telegram, and search results fetch without asking.
// Run: node --test agents/chat/mods/twin_mind.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// No real chat log, no real bot and no sudo: auto-retrieval fails fast and rows land in temp files.
const dir = mkdtempSync(path.join(tmpdir(), "twin-mod-"));
process.env.TWIN_CHAT_LOG = path.join(dir, "chat-log.jsonl");
process.env.TWIN_TELEGRAM_ACCOUNTS = path.join(dir, "accounts.json");
process.env.TWIN_TELEGRAM_API = "http://telegram.test";
writeFileSync(process.env.TWIN_TELEGRAM_ACCOUNTS, JSON.stringify({ accounts: [{ enabled: true, token: "test-token" }] }));
process.env.PATH = dir;
const mod = await import("./twin_mind.ts");
const { default: activate, leftUnsent, rememberSearchUrls, telegramHtml, UNSENT_NUDGE, SENT_FOR_YOU } = mod;

// The Telegram Bot API, faked: each call is recorded and answered with the next status.
let posts = [];
let statuses = [];
globalThis.fetch = async (url, init) => {
  posts.push({ url: String(url), body: JSON.parse(init.body) });
  const status = statuses.shift() ?? 200;
  return { status, ok: status === 200 };
};

function load() {
  posts = [];
  statuses = [];
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
  input: [{ role: "user", content: `<channel-notification source="telegram" chat_id="42">${text}</channel-notification>` }],
});
const send = (on, message, action = "send") =>
  on.tool_start({ conversationId: "c", toolName: "MessageChannel", args: { action, message } });
const chatLog = () => readFileSync(process.env.TWIN_CHAT_LOG, "utf8").trim().split("\n").map((line) => JSON.parse(line));
const LONG_ANSWER = "The offer has three parts, and the second one is the one that matters. ".repeat(4);

test("a reply left as plain text is sent by the mod, and the next turn says so", async () => {
  const { on } = load();
  await on.turn_start(fromTelegram("what is the capital of France?"));
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "I think it is **Paris**." }), undefined);
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, "http://telegram.test/bottest-token/sendMessage");
  assert.deepEqual(posts[0].body, { chat_id: "42", text: "I think it is <b>Paris</b>.", parse_mode: "HTML" });
  assert.equal(chatLog().at(-1).text, "I think it is **Paris**.");
  assert.equal(chatLog().at(-1).via, "relay", "a relayed reply is marked, so relays can be counted");
  const next = fromTelegram("thanks");
  await on.turn_start(next);
  assert.match(next.input[0].content, new RegExp(SENT_FOR_YOU));
  const after = fromTelegram("and now?");
  await on.turn_start(after);
  assert.doesNotMatch(after.input[0].content, new RegExp(SENT_FOR_YOU), "said once, not every turn");
});

test("an answer left as plain text after a short send still arrives", async () => {
  const { on } = load();
  await on.turn_start(fromTelegram("what does the offer say?"));
  send(on, "On it.");
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: LONG_ANSWER }), undefined);
  assert.equal(posts.length, 1, "the long answer is relayed");
  assert.equal(chatLog().at(-1).via, "relay");
});

test("a closing line or a repeat of what was sent is not sent again", async () => {
  const { on } = load();
  await on.turn_start(fromTelegram("what does the offer say?"));
  send(on, LONG_ANSWER);
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "Sent." }), undefined);
  await on.turn_start(fromTelegram("again?"));
  send(on, `Here it is.\n\n${LONG_ANSWER}`);
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: LONG_ANSWER }), undefined);
  assert.equal(posts.length, 0);
  assert.ok(chatLog().slice(-4).every((row) => row.via === undefined), "rows the model sent carry no relay mark");
});

test("the rule for text that still has to go out", () => {
  assert.equal(leftUnsent("Done.", ""), true, "nothing was sent, so even a short text goes out");
  assert.equal(leftUnsent("Sent.", "onit"), false);
  assert.equal(leftUnsent(LONG_ANSWER, "onit"), true);
  assert.equal(leftUnsent(LONG_ANSWER, LONG_ANSWER.replace(/\W+/g, "").toLowerCase()), false);
});

test("markup Telegram rejects is sent again as plain text", async () => {
  const { on } = load();
  statuses = [400, 200];
  await on.turn_start(fromTelegram("hi"));
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "a <b> b" }), undefined);
  assert.deepEqual(posts.map((p) => p.body), [
    { chat_id: "42", text: "a &lt;b&gt; b", parse_mode: "HTML" },
    { chat_id: "42", text: "a <b> b" },
  ]);
});

test("a failed send falls back to one nudge, then stops", async () => {
  const { on } = load();
  statuses = [500];
  await on.turn_start(fromTelegram("hi"));
  assert.deepEqual(await on.turn_end({ conversationId: "c", assistantMessage: "answer" }), { continue: UNSENT_NUDGE });
  await on.turn_start({ conversationId: "c", input: [{ role: "user", content: UNSENT_NUDGE }] });
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "still plain text" }), undefined);
  assert.equal(posts.length, 1, "no second send");
});

test("after a nudge, a reply the model then sends ends the matter", async () => {
  const { on } = load();
  statuses = [500];
  await on.turn_start(fromTelegram("hi"));
  assert.deepEqual(await on.turn_end({ conversationId: "c", assistantMessage: LONG_ANSWER }), { continue: UNSENT_NUDGE });
  await on.turn_start({ conversationId: "c", input: [{ role: "user", content: UNSENT_NUDGE }] });
  send(on, LONG_ANSWER);
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "Sent." }), undefined);
  assert.equal(posts.length, 1, "only the failed attempt reached the fake API");
});

test("a MessageChannel reply, send-rich included, is logged and not sent twice", async () => {
  const { on } = load();
  await on.turn_start(fromTelegram("compare them"));
  send(on, "| a | b |", "send-rich");
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "Sent." }), undefined);
  assert.equal(posts.length, 0);
  assert.equal(chatLog().at(-1).text, "| a | b |");
});

test("a turn that is not Daniel talking is never sent", async () => {
  const { on } = load();
  await on.turn_start({ conversationId: "c", input: [{ role: "user", content: "scheduled reflection" }] });
  assert.equal(await on.turn_end({ conversationId: "c", assistantMessage: "done" }), undefined);
  assert.equal(posts.length, 0);
});

test("headings, bold and code become Telegram HTML", () => {
  assert.equal(telegramHtml("## Funding\n**$9M** via `seed` & more"), "<b>Funding</b>\n<b>$9M</b> via <code>seed</code> &amp; more");
});

test("web_fetch runs at once only for a URL that web_search returned", () => {
  const { check } = load();
  rememberSearchUrls("Acme raises $9M\nhttps://example.com/acme\nsnippet https://planted.example/x");
  assert.equal(check({ toolName: "web_fetch", args: { url: "https://example.com/acme" } }).decision, "allow");
  assert.equal(check({ toolName: "web_fetch", args: { url: "https://example.com/acme?d=secret" } }), undefined);
  assert.equal(check({ toolName: "web_fetch", args: { url: "https://planted.example/x" } }), undefined);
});
