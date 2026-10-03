import { Effect, Schema } from "effect"
import { execute } from "./opencode-v2.0.22-source/packages/core/src/tool/runtime.ts"
import { Tool } from "./opencode-v2.0.22-source/packages/core/src/tool.ts"
import { Session } from "./opencode-v2.0.22-source/packages/schema/src/session.ts"
import { Agent } from "./opencode-v2.0.22-source/packages/schema/src/agent.ts"
import { SessionMessage } from "./opencode-v2.0.22-source/packages/schema/src/session-message.ts"
import { getConfig } from "./ace_config.ts"

const config = getConfig();
const lab = config.labDir;
const roster = await Bun.file(`${lab}\\ace-free-worker-roster.json`).json() as { workers: Array<{ model: string, verified: boolean }> }
const models = roster.workers.filter((worker) => worker.verified).map((worker) => worker.model)

const aceTool = {
  name: "ace_status",
  description: "Execute canonical ACE host status. OpenCode must not execute this tool.",
  input: Schema.Struct({}),
  output: Schema.Unknown,
  execute: () => Effect.tryPromise({
    try: async () => {
      const child = Bun.spawn([config.python, "-B", config.adapterScript, config.aceRoot], { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
      const requestId = crypto.randomUUID()
      child.stdin.write(JSON.stringify({ protocol: "ace.host_adapter.v0", request_id: requestId, host_id: "free-model-ace-smoke", action: "status" }) + "\n")
      child.stdin.end()
      const text = await new Response(child.stdout).text(); await child.exited
      const response = JSON.parse(text.trim())
      return { output: response, content: JSON.stringify(response) }
    }, catch: (error) => new Tool.Error({ message: String(error) }),
  }),
} satisfies Tool.Info

async function ask(model: string, messages: any[], toolChoice: any = "required") {
  const body: any = { model, messages, tool_choice: toolChoice === "required" ? { type: "function", function: { name: "ace_status" } } : toolChoice, max_tokens: 512 }
  if (toolChoice !== "none") body.tools = [{ type: "function", function: { name: "ace_status", description: aceTool.description, parameters: {} } }]
  const r = await fetch(config.llmEndpoint, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${config.apiKey}` }, body: JSON.stringify(body) })
  const text = await r.text(); let bodyOut; try { bodyOut = JSON.parse(text) } catch { bodyOut = { raw: text } }
  return { status: r.status, body: bodyOut }
}
function normalizedName(name: string) { return name.split(".").at(-1) }
async function runModel(model: string) {
  const sessionID = Session.ID.make(`ses_free_${model.slice(0, 8)}_${Date.now().toString(36)}`)
  const runtimeID = `ace-free-runtime-${model}-${Date.now()}`
  const messages: any[] = [{ role: "system", content: "You are an ACE worker. Call ace_status exactly once now. After receiving the ACE result, call ace_status exactly once again. Then stop tool use." }, { role: "user", content: "Begin the two-step ACE status task." }]
  const result: any = { model, runtimeID, sessionID, calls: [], results: [], final: null, errors: [] }
  try {
    for (let round = 1; round <= 2; round++) {
      const response = await ask(model, messages)
      if (response.status !== 200) throw new Error(`HTTP ${response.status}: ${JSON.stringify(response.body?.error || response.body)}`)
      const message = response.body?.choices?.[0]?.message; const call = message?.tool_calls?.[0]
      if (!call) throw new Error(`no tool call on round ${round}: ${JSON.stringify(message)}`)
      const name = normalizedName(call.function?.name || "")
      if (name !== "ace_status") throw new Error(`unexpected tool ${call.function?.name}`)
      let input: unknown = {}
      try { input = JSON.parse(call.function?.arguments || "{}") } catch {}
      if (typeof input !== "object" || input === null || Array.isArray(input)) input = {}
      result.calls.push({ round, id: call.id, name: call.function.name, arguments: call.function.arguments })
      messages.push(message)
      const executed = await Effect.runPromise(execute(aceTool, input, { sessionID, agent: Agent.ID.make("build"), messageID: SessionMessage.ID.make(`msg_${round}`), id: Tool.CallID.make(`call_${runtimeID}_${round}`), progress: () => Effect.void }))
      result.results.push(executed.content)
      messages.push({ role: "tool", tool_call_id: call.id, name: call.function.name, content: executed.content.map((item: any) => item.text || "").join("\n") })
      if (round === 1) messages.push({ role: "user", content: "The first ACE result is received. Now call ace_status exactly once more." })
    }
    const final = await ask(model, [{ role: "system", content: "Do not call tools. Summarize the completed ACE task." }, { role: "user", content: `ACE status was executed twice by the ACE Tool Adapter in runtime ${runtimeID}. Results: ${JSON.stringify(result.results)}. Confirm completion.` }], "none")
    result.final = { status: final.status, text: final.body?.choices?.[0]?.message?.content, error: final.body?.error }
  } catch (error) { result.errors.push(String(error)) }
  return result
}
const all: any[] = []
for (const model of models) { all.push(await runModel(model)); await Bun.sleep(1000) }
await Bun.write(`${lab}\\free-model-ace-smoke-report.json`, JSON.stringify({ testedAt: new Date().toISOString(), endpoint: config.llmEndpoint, all }, null, 2))
console.log(JSON.stringify({ testedAt: new Date().toISOString(), endpoint: config.llmEndpoint, all }, null, 2))