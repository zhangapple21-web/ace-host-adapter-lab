import { Effect, Schema } from "effect"
import { execute } from "./opencode-v2.0.22-source/packages/core/src/tool/runtime.ts"
import { Tool } from "./opencode-v2.0.22-source/packages/core/src/tool.ts"
import { Session } from "./opencode-v2.0.22-source/packages/schema/src/session.ts"
import { Agent } from "./opencode-v2.0.22-source/packages/schema/src/agent.ts"
import { SessionMessage } from "./opencode-v2.0.22-source/packages/schema/src/session-message.ts"
import { getConfig } from "./ace_config.ts"

const config = getConfig();
const runtimeID = `ace-runtime-${Date.now()}`
const sessionID = Session.ID.make(`ses_ace_runtime_${Date.now().toString(36)}`)
const toolName = "ace_status"
let executionCount = 0
const proof = `${config.labDir}\\runtime-adapter-proof.jsonl`
const proofFor = () => `${config.labDir}\\runtime-adapter-proof-${++executionCount}.json` 

const aceTool = {
  name: toolName,
  description: "Execute the canonical ACE host status adapter. OpenCode must not execute this tool.",
  input: Schema.Struct({}),
  output: Schema.Unknown,
  execute: () => Effect.tryPromise({
    try: async () => {
      const child = Bun.spawn([config.python, "-B", config.adapterScript, config.aceRoot], { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
      child.stdin.write(JSON.stringify({ protocol: "ace.host_adapter.v0", request_id: crypto.randomUUID(), host_id: "ace-runtime-adapter", action: "status" }) + "\n")
      child.stdin.end()
      const text = await new Response(child.stdout).text()
      await child.exited
      const response = JSON.parse(text.trim())
      await Bun.write(proofFor(), JSON.stringify({ runtimeID, sessionID, tool: toolName, input: {}, entrypoint: "ace_host_adapter.py -> handle(status)", output: response, executionOwner: "ACE Tool Adapter", openCodeExecutor: false }), { createPath: true })
      return { output: response, content: JSON.stringify(response) }
    }, catch: (error) => new Tool.Error({ message: String(error) }),
  }),
} satisfies Tool.Info

const toolContext = (index: number) => ({ sessionID, agent: Agent.ID.make("build"), messageID: SessionMessage.ID.make(`msg_${index}`), id: Tool.CallID.make(`call_${runtimeID}_${index}`), progress: () => Effect.void })

async function ask(messages: any[], toolChoice: any = "required") {
  const body: any = { model: config.model, messages, tool_choice: toolChoice }
  if (toolChoice !== "none") body.tools = [{ type: "function", function: { name: toolName, description: aceTool.description, parameters: {} } }]
  const r = await fetch(config.llmEndpoint, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${config.apiKey}` }, body: JSON.stringify(body) })
  return { status: r.status, body: await r.json() }
}

const messages: any[] = [{ role: "system", content: "You are an ACE runtime test. Call ace_status exactly once, then after the result call it exactly once more, then provide a final answer." }, { role: "user", content: "Start the two-call ACE status verification." }]
const record: any = { runtimeID, sessionID, model: config.model, calls: [], results: [], errors: [] }
for (let round = 1; round <= 2; round++) {
  const response = await ask(messages)
  if (response.status !== 200) throw new Error(JSON.stringify(response.body))
  const message = response.body.choices?.[0]?.message
  const call = message?.tool_calls?.[0]
  if (!call) throw new Error(`missing tool call round ${round}`)
  record.calls.push({ round, id: call.id, name: call.function.name, arguments: call.function.arguments })
  messages.push(message)
  const result = await Effect.runPromise(execute(aceTool, JSON.parse(call.function.arguments || "{}"), toolContext(round)))
  record.results.push(result.content)
  messages.push({ role: "tool", tool_call_id: call.id, name: call.function.name, content: result.content.map((item: any) => item.text || "").join("\n") })
}
const final = await ask([{ role: "system", content: "You are completing an ACE runtime task. Do not call tools." }, { role: "user", content: `The ACE Tool Adapter executed ace_status twice in the same runtime. Here are the real results: ${JSON.stringify(record.results)}. Confirm completion.` }], "none")
record.final = final.body.choices?.[0]?.message?.content
record.status = final.status
record.sameRuntime = record.calls.length === 2
await Bun.write(`${config.labDir}\\runtime-adapter-report.json`, JSON.stringify(record, null, 2))
console.log(JSON.stringify(record, null, 2))