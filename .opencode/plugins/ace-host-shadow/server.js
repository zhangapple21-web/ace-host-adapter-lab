const hostOwned = new Set([
  "bash",
  "Bash",
  "shell",
  "grep",
  "Grep",
  "glob",
  "Glob",
  "read",
  "Read",
  "write",
  "Write",
  "edit",
  "Edit",
  "skill",
  "Skill",
  "ace_capabilities",
  "ace_status",
  "ace_tasks",
  "ace_learning",
  "ace_archaeology",
  "ace_governance",
  "ace_query",
  "ace_capsule",
])

const loose = {
  type: "object",
  properties: {},
  additionalProperties: true,
}

async function defer(_input, ctx) {
  const signal = ctx?.signal
  try {
    await new Promise((resolve) => {
      if (!signal) {
        setTimeout(resolve, 30000)
        return
      }
      if (signal.aborted) {
        resolve()
        return
      }
      const timer = setTimeout(resolve, 30000)
      signal.addEventListener(
        "abort",
        () => {
          clearTimeout(timer)
          resolve()
        },
        { once: true },
      )
    })
  } catch {
    // Shadow tools must not abort the OpenCode step.
  }
  return "ACE_HOST_DEFERRED: OpenCode did not execute this host tool."
}

export default {
  id: "ace.host.shadow",
  async setup(ctx) {
    const fs = await import("node:fs/promises")
    const path = await import("node:path")
     const logPath = path.join("C:\\tmp\\ace-host-adapter-lab", ".opencode", "ace-host-shadow.log")
    const writeLog = async (line) => {
      await fs.mkdir(path.dirname(logPath), { recursive: true }).catch(() => undefined)
      await fs.appendFile(logPath, `${new Date().toISOString()} ${line}\n`).catch(() => undefined)
    }

    await ctx.tool.transform((tools) => {
      const existing = tools.list()
      const known = new Set(existing.map((tool) => tool.name))
      for (const tool of existing) {
        if (!hostOwned.has(tool.name) && !hostOwned.has(tool.id)) continue
         tools.update(tool.id, (current) => {
           current.description = `Host-owned ${current.name}. OpenCode must not execute it; ACE Host owns the result.`
           current.execute = defer
         })
       }
      for (const name of hostOwned) {
        if (known.has(name)) continue
        tools.add({
          name,
          description: `Host-owned ${name}. This shadow only occupies the name so OpenCode does not abort or execute it.`,
          input: loose,
          output: loose,
          execute: defer,
          options: { permission: name },
        })
      }
    }).catch((error) => writeLog(`transform failed: ${error instanceof Error ? error.message : String(error)}`))

    const listed = await ctx.tool.list().catch((error) => {
      writeLog(`list failed: ${error instanceof Error ? error.message : String(error)}`)
      return []
    })
    await writeLog(`loaded tools=${listed.map((tool) => `${tool.id}:${tool.name}`).join(",")}`)
    return async () => {
      await writeLog("unloaded")
    }
  },
}
