// Smoke test for the TypeScript SDK: observe + instrumentOpenAI (plain and
// streamed) against a fake OpenAI-shaped client; spans ship to a real local
// Veekshana server. Driven by tests/test_ts_sdk.py.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const vk = require("../sdk-ts/dist/index.js");

vk.init({ host: process.env.VK_HOST, apiKey: "dev-key" });
vk.setSession("ts-smoke-session");

const fakeOpenAI = {
  chat: {
    completions: {
      create: async (body) => {
        if (!body.stream) {
          return {
            model: "gpt-4o",
            usage: { prompt_tokens: 5, completion_tokens: 7 },
            choices: [{ message: { role: "assistant", content: "Hi there" }, finish_reason: "stop" }],
          };
        }
        return (async function* () {
          yield { model: "gpt-4o", choices: [{ delta: { content: "Hi " } }] };
          yield {
            model: "gpt-4o",
            choices: [{ delta: { content: "streamed" }, finish_reason: "stop" }],
            usage: { prompt_tokens: 5, completion_tokens: 7 },
          };
        })();
      },
    },
  },
};

vk.instrumentOpenAI(fakeOpenAI);

const myAgent = vk.observe(async function myAgent(question) {
  const plain = await fakeOpenAI.chat.completions.create({
    model: "gpt-4o",
    messages: [{ role: "user", content: question }],
  });
  const stream = await fakeOpenAI.chat.completions.create({
    model: "gpt-4o",
    messages: [{ role: "user", content: question }],
    stream: true,
  });
  let streamed = "";
  for await (const chunk of stream) {
    for (const choice of chunk.choices ?? []) streamed += choice.delta?.content ?? "";
  }
  return plain.choices[0].message.content + "|" + streamed;
});

const out = await myAgent("hello");
if (out !== "Hi there|Hi streamed") {
  console.error("unexpected agent output:", out);
  process.exit(1);
}
await vk.flush();
console.log("ts smoke: agent ran, spans flushed");
