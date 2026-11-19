import os from "node:os";
import path from "node:path";
import { mkdtemp, writeFile } from "node:fs/promises";
import { runEngine, timeoutFor } from "./lib/python.js";
import { renderTopology, renderModels, renderApply } from "./lib/render.js";

export const name = "dsh-ptforge";
export const inject = ["tools"];

/** Resolve the directory a tool call should write into. */
function sessionCwd(ctx, exec) {
  try {
    const session = exec?.agent?.session;
    if (session && ctx.workingDirectory) return ctx.workingDirectory.get(session);
  } catch {
    // fall through to the host working directory
  }
  return process.cwd();
}

const numberOr = (value, fallback) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);

export function apply(ctx, config) {
  const engineConfig = config ?? {};

  ctx.tools.register({
    name: "pt_models",
    description:
      "List Cisco Packet Tracer device models bundled with the ptforge engine, with the IOS interface names the generator will emit. Use before pt_build when unsure which model string or interface name to use.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Case-insensitive substring filter on the model name" },
        limit: { type: "number", description: "Maximum models to return (default 40)" },
      },
    },
    output: {
      schema: {
        type: "object",
        properties: { models: { type: "array" }, total: { type: "number" } },
      },
      render: (_args, value) => [{ type: "text", text: renderModels(value) }],
    },
    timeoutMs: timeoutFor("models"),
    isConcurrencySafe: () => true,
    async execute(args) {
      const payload = await runEngine(engineConfig, ["models"], { timeout: timeoutFor("models") });
      const models = Array.isArray(payload.models) ? payload.models : [];
      const query = typeof args?.query === "string" ? args.query.toLowerCase() : "";
      const filtered = query ? models.filter((m) => m.model.toLowerCase().includes(query)) : models;
      const limit = numberOr(args?.limit, 40);
      return { models: filtered.slice(0, limit), total: filtered.length };
    },
  });

  ctx.tools.register({
    name: "pt_build",
    description:
      "Build a Cisco Packet Tracer .pkt topology from a JSON spec (devices, links, CLI config, static IPv4) using this machine's own Packet Tracer device templates and the Twofish-EAX container codec. Returns the written path and the resulting device/link inventory. Use pt_open afterwards to show it in Packet Tracer.",
    parameters: {
      type: "object",
      properties: {
        spec: {
          type: "object",
          description:
            "Topology spec: { name?, devices: [ { model, name?, x?, y?, ipv4?/{address,mask,gateway} or [addr,mask,gw], port?, config?: [...] } ], links: [ { from, to, from_port?, to_port?, cable? } ] }",
        },
        spec_path: { type: "string", description: "Path to a spec JSON file instead of inline spec" },
        out: { type: "string", description: "Output .pkt path (default <session cwd>/<name>.pkt)" },
        open: { type: "boolean", description: "Open the result in Packet Tracer after building (default false)" },
      },
    },
    output: {
      schema: { type: "object", properties: { path: { type: "string" }, devices: { type: "array" }, links: { type: "array" } } },
      render: (_args, value) => [{ type: "text", text: renderTopology(value, { title: "built" }) }],
    },
    timeoutMs: timeoutFor("build") + timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      let specPath = typeof args?.spec_path === "string" ? args.spec_path : undefined;
      let tempDir;
      if (!specPath) {
        if (!args || typeof args.spec !== "object" || args.spec === null) {
          throw new Error("pt_build needs an inline `spec` object or a `spec_path`.");
        }
        tempDir = await mkdtemp(path.join(os.tmpdir(), "ptforge-spec-"));
        specPath = path.join(tempDir, "spec.json");
        await writeFile(specPath, JSON.stringify(args.spec, null, 2), "utf8");
      }
      const name = args?.spec?.name ?? "topology";
      const out =
        typeof args?.out === "string" && args.out.length > 0
          ? args.out
          : path.join(process.cwd(), `${name}.pkt`);
      const built = await runEngine(engineConfig, ["build", specPath, "-o", out], {
        timeout: timeoutFor("build"),
      });
      // Only attach `opened` when it exists: an `undefined` field is not
      // lossless JSON and the host rejects the whole result.
      const result = { ...built };
      if (args?.open === true) {
        result.opened = await runEngine(engineConfig, ["open", built.path ?? out, "--timeout", "20"], {
          timeout: timeoutFor("open"),
        });
      }
      return result;
    },
  });

  ctx.tools.register({
    name: "pt_inspect",
    description:
      "Decode an existing .pkt and report its devices, canvas positions, IOS interfaces, running-config line counts and cable endpoints (device names resolved). Read-only.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to a .pkt file" },
        config_lines: {
          type: "number",
          description:
            "Include the first N running-config lines per device; 0 (default) omits configuration so the report stays small",
        },
      },
      required: ["file"],
    },
    output: {
      schema: { type: "object", properties: { devices: { type: "array" }, links: { type: "array" } } },
      render: (_args, value) => [{ type: "text", text: renderTopology(value) }],
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => true,
    async execute(args) {
      if (typeof args?.file !== "string" || args.file.trim() === "") {
        throw new Error("pt_inspect needs a non-empty `file` path.");
      }
      const payload = await runEngine(engineConfig, ["inspect", args.file], {
        timeout: timeoutFor("inspect"),
      });
      const limit = numberOr(args?.config_lines, 0);
      if (Array.isArray(payload.devices)) {
        payload.devices = payload.devices.map((device) => ({
          ...device,
          // Keep the tool output bounded: 0 means "omit config entirely".
          config:
            limit > 0 && Array.isArray(device.config) ? device.config.slice(0, limit) : [],
        }));
      }
      return payload;
    },
  });

  ctx.tools.register({
    name: "pt_apply",
    description:
      "Write IOS CLI configuration onto a device inside an existing .pkt (hostname, interfaces, VLANs, routing statements) and/or set a static IPv4 address on an end-device interface, then re-encode the container. Packet Tracer parses the RUNNINGCONFIG text when it loads the file.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt to edit" },
        device: { type: "string", description: "Device name as it appears in the topology" },
        lines: { type: "array", items: { type: "string" }, description: "CLI lines to write, in order" },
        lines_file: { type: "string", description: "Read CLI lines from this text file instead" },
        replace: {
          type: "boolean",
          description:
            "Replace the whole running-config instead of merging. By default lines are merged: a block starting with `interface`, `vlan`, `router` or `line` updates that section in place, other lines are appended before `end`.",
        },
        ip: { type: "string", description: "Static IPv4 address for an end device" },
        mask: { type: "string", description: "Subnet mask for `ip` (default 255.255.255.0)" },
        gateway: { type: "string", description: "Default gateway for `ip`" },
        port: { type: "string", description: "Interface that receives `ip` (default the first port)" },
        out: { type: "string", description: "Write to this path instead of editing in place" },
      },
      required: ["file", "device"],
    },
    output: {
      schema: { type: "object", properties: { path: { type: "string" }, device: { type: "string" } } },
      render: (_args, value) => [{ type: "text", text: renderApply(value) }],
    },
    timeoutMs: timeoutFor("apply"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (typeof args?.file !== "string" || typeof args?.device !== "string") {
        throw new Error("pt_apply needs `file` and `device`.");
      }
      const cli = ["apply", args.file, "--device", args.device];
      if (Array.isArray(args.lines) && args.lines.length > 0) cli.push("--lines", ...args.lines.map(String));
      else if (typeof args.lines_file === "string") cli.push("--file", args.lines_file);
      if (args.replace === true) cli.push("--replace");
      if (typeof args.ip === "string") {
        cli.push("--ip", args.ip);
        if (typeof args.mask === "string") cli.push("--mask", args.mask);
        if (typeof args.gateway === "string") cli.push("--gateway", args.gateway);
        if (typeof args.port === "string") cli.push("--port", args.port);
      }
      if (typeof args.out === "string") cli.push("-o", args.out);
      return runEngine(engineConfig, cli, { timeout: timeoutFor("apply") });
    },
  });

  ctx.tools.register({
    name: "pt_open",
    description:
      "Open a .pkt in the installed Cisco Packet Tracer, wait until the window reports the file (or an invalid-file dialog) and bring it to the front. Returns pid, ok and the window title.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt to open" },
        timeout_seconds: { type: "number", description: "How long to wait for the window (default 25)" },
      },
      required: ["file"],
    },
    output: {
      schema: { type: "object", properties: { pid: { type: "number" }, ok: { type: "boolean" }, title: { type: "string" } } },
      render: (_args, value) => [
        {
          type: "text",
          text: `${value.ok ? "opened" : "failed"}: ${value.title ?? ""} (pid ${value.pid ?? "?"})`,
        },
      ],
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (typeof args?.file !== "string" || args.file.trim() === "") {
        throw new Error("pt_open needs a non-empty `file` path.");
      }
      const seconds = numberOr(args?.timeout_seconds, 25);
      return runEngine(engineConfig, ["open", args.file, "--timeout", String(seconds)], {
        timeout: timeoutFor("open"),
      });
    },
  });

  ctx.tools.register({
    name: "pt_gui",
    description:
      "Low-level escape hatch that drives the Packet Tracer Qt window directly: focus a window by title substring, click/double-click at screen pixels, type text, press keys, or grab a PNG screenshot. Packet Tracer exposes no automation API, so higher-level runtime tools are built on this primitive. Coordinates are physical screen pixels.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["focus", "click", "type", "key", "shot", "paste", "copy"],
          description: "What to do",
        },
        title: { type: "string", description: "Window title substring to focus before acting (default: current foreground)" },
        x: { type: "number", description: "Click x in physical screen pixels" },
        y: { type: "number", description: "Click y in physical screen pixels" },
        double: { type: "boolean", description: "Double-click instead of a single click" },
        enter: { type: "boolean", description: "With action=paste, press Enter afterwards" },
        text: { type: "string", description: "Text to type (action=type) or paste via the clipboard (action=paste)" },
        keys: { type: "array", items: { type: "string" }, description: "Keys for action=key, e.g. ['enter','ctrl+s']" },
        path: { type: "string", description: "PNG output path for action=shot" },
        region: { type: "string", description: "Crop for action=shot as x,y,width,height in screen pixels" },
      },
      required: ["action"],
    },
    output: {
      schema: { type: "object", properties: { action: { type: "string" }, path: { type: "string" } } },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value) }],
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      const action = typeof args?.action === "string" ? args.action : "";
      if (!["focus", "click", "type", "key", "shot", "paste", "copy"].includes(action)) {
        throw new Error("pt_gui action must be one of focus, click, type, key, shot, paste, copy.");
      }
      const cli = [action];
      if (action === "focus") {
        cli.push(String(args?.title ?? "Packet Tracer"));
      } else if (action === "click") {
        if (typeof args?.x !== "number" || typeof args?.y !== "number") {
          throw new Error("pt_gui click needs numeric x and y.");
        }
        cli.push(String(Math.round(args.x)), String(Math.round(args.y)));
        if (args?.double === true) cli.push("--double");
        if (typeof args?.title === "string" && args.title) cli.push("--title", args.title);
      } else if (action === "type") {
        if (typeof args?.text !== "string") throw new Error("pt_gui type needs `text`.");
        cli.push(args.text);
        if (typeof args?.title === "string" && args.title) cli.push("--title", args.title);
      } else if (action === "key") {
        const keys = Array.isArray(args?.keys) ? args.keys.map(String) : [];
        if (keys.length === 0) throw new Error("pt_gui key needs `keys`.");
        cli.push(...keys);
        if (typeof args?.title === "string" && args.title) cli.push("--title", args.title);
      } else if (action === "paste") {
        if (typeof args?.text !== "string") throw new Error("pt_gui paste needs `text`.");
        cli.push(args.text);
        if (typeof args?.title === "string" && args.title) cli.push("--title", args.title);
        if (args?.enter === true) cli.push("--enter");
      } else if (action === "copy") {
        if (typeof args?.title === "string" && args.title) cli.push("--title", args.title);
      } else {
        if (typeof args?.path !== "string" || args.path.trim() === "") {
          throw new Error("pt_gui shot needs `path`.");
        }
        cli.push(args.path);
        if (typeof args?.region === "string" && args.region) cli.push("--region", args.region);
      }
      return runEngine(engineConfig, cli, {
        timeout: timeoutFor("open"),
        module: "ptforge.guitool",
        json: false,
      });
    },
  });

  ctx.tools.register({
    name: "pt_exec",
    description:
      "Run commands inside a Packet Tracer device console that is already open (double-click the device on the canvas first). Input goes through the clipboard: PT ignores synthetic per-key typing, but its context menu Paste works. After the run it selects the transcript and copies it back via the context menu Copy, so the result carries the console text as a string plus a PNG screenshot. Prefer pt_check for anything provable from a saved file.",
    parameters: {
      type: "object",
      properties: {
        device: { type: "string", description: "Device name, which is also the console window title (e.g. PC0, R1)" },
        commands: { type: "array", items: { type: "string" }, description: "Commands to run, one per entry" },
        out: { type: "string", description: "PNG output path (default fixtures/console_<device>.png)" },
        wait_ms: { type: "number", description: "Milliseconds to wait after each command (default 1200)" },
        read: { type: "boolean", description: "Copy the console transcript back as text with a select-all drag + context-menu Copy (default true)" },
      },
      required: ["device", "commands"],
    },
    output: {
      schema: {
        type: "object",
        properties: { device: { type: "string" }, screenshot: { type: "string" }, commands: { type: "array" } },
      },
      render: (_args, value) => {
        const output = typeof value.output === "string" ? value.output.trim() : "";
        const lines = [
          `ran ${(value.commands ?? []).length} command(s) on ${value.device}`,
          ...(value.commands ?? []).map((item) => `  > ${item.command}`),
        ];
        if (output) lines.push("--- console ---", output.slice(-4000));
        lines.push(`console screenshot: ${value.screenshot}`);
        return [{ type: "text", text: lines.join("\n") }];
      },
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (typeof args?.device !== "string" || args.device.trim() === "") {
        throw new Error("pt_exec needs a non-empty `device` name.");
      }
      const commands = Array.isArray(args?.commands) ? args.commands.map(String).filter(Boolean) : [];
      if (commands.length === 0) throw new Error("pt_exec needs a non-empty `commands` array.");
      const cli = ["exec", args.device, ...commands];
      if (typeof args?.out === "string" && args.out) cli.push("--out", args.out);
      if (typeof args?.wait_ms === "number" && Number.isFinite(args.wait_ms)) {
        cli.push("--wait", String(args.wait_ms / 1000));
      }
      if (args?.read === false) cli.push("--no-read");
      return runEngine(engineConfig, cli, {
        timeout: timeoutFor("open"),
        module: "ptforge.guitool",
        json: false,
      });
    },
  });
  ctx.tools.register({
    name: "pt_assert",
    description:
      "Run CLI commands in an open device console and assert on the transcript. Each check is {command, contains?, regex?, not_contains?}; the result carries pass/fail per check plus the raw console text, so a failing assertion shows exactly what Packet Tracer printed. Needs the device window open with its CLI/console visible.",
    parameters: {
      type: "object",
      properties: {
        device: { type: "string", description: "Device name, which is also the console window title" },
        checks: {
          type: "array",
          items: { type: "object" },
          description: "Checks, e.g. {command:'show ip route', contains:'O    192.1.3.0/24'}",
        },
        wait_ms: { type: "number", description: "Milliseconds to wait after each command (default 2000)" },
      },
      required: ["device", "checks"],
    },
    output: {
      schema: {
        type: "object",
        properties: { ok: { type: "boolean" }, results: { type: "array" }, output: { type: "string" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: [
            `${value.ok ? "PASS" : "FAIL"} ${(value.results ?? []).filter((item) => item.ok).length}/${(value.results ?? []).length} checks on ${value.device ?? ""}`,
            ...(value.results ?? []).map(
              (item) =>
                `  ${item.ok ? "ok  " : "FAIL"} ${item.command}${item.problems?.length ? ` -- ${item.problems.join("; ")}` : ""}`,
            ),
          ].join("\n"),
        },
      ],
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (!Array.isArray(args?.checks) || args.checks.length === 0) {
        throw new Error("pt_assert needs a non-empty `checks` array.");
      }
      const cli = ["assert", String(args.device ?? ""), "--checks", JSON.stringify(args.checks)];
      if (typeof args?.wait_ms === "number" && Number.isFinite(args.wait_ms)) {
        cli.push("--wait", String(args.wait_ms / 1000));
      }
      return runEngine(engineConfig, cli, {
        timeout: timeoutFor("open"),
        module: "ptforge.guitool",
        json: false,
      });
    },
  });
  ctx.tools.register({
    name: "pt_ping",
    description:
      "Ping a target from an open device console and parse the summary Packet Tracer prints (sent / received / lost / loss%). Returns ok when at least one reply came back, plus the full transcript and a console screenshot. Needs the device window open.",
    parameters: {
      type: "object",
      properties: {
        device: { type: "string", description: "Source device name (console window title)" },
        target: { type: "string", description: "Address to ping" },
        count: { type: "number", description: "Echo requests (default 4)" },
        wait_ms: { type: "number", description: "Milliseconds to wait for the run (default 8000)" },
      },
      required: ["device", "target"],
    },
    output: {
      schema: {
        type: "object",
        properties: { ok: { type: "boolean" }, sent: { type: "number" }, received: { type: "number" }, lost: { type: "number" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: `${value.ok ? "reachable" : "unreachable"} ${value.target ?? ""} from ${value.device ?? ""}: sent=${value.sent} received=${value.received} lost=${value.lost} (${value.loss_percent}%)`,
        },
      ],
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (typeof args?.target !== "string" || args.target.trim() === "") {
        throw new Error("pt_ping needs a non-empty `target`.");
      }
      const cli = ["ping", String(args.device ?? ""), args.target];
      if (typeof args?.count === "number" && Number.isFinite(args.count)) cli.push("--count", String(args.count));
      if (typeof args?.wait_ms === "number" && Number.isFinite(args.wait_ms)) {
        cli.push("--wait", String(args.wait_ms / 1000));
      }
      return runEngine(engineConfig, cli, {
        timeout: timeoutFor("open"),
        module: "ptforge.guitool",
        json: false,
      });
    },
  });
  ctx.tools.register({
    name: "pt_http_get",
    description:
      "Load a URL in a device's Web Browser app (Desktop tab) and return the rendered page text. It fills the URL field, clicks Go, then selects the page body and copies it. ok is false when Packet Tracer shows a timeout/error page. The browser must already be open on that device.",
    parameters: {
      type: "object",
      properties: {
        device: { type: "string", description: "Device name whose browser is open" },
        url: { type: "string", description: "URL to load, e.g. http://192.1.1.2" },
        out: { type: "string", description: "Screenshot output path" },
        wait_ms: { type: "number", description: "Milliseconds to wait for the page (default 3000)" },
      },
      required: ["device", "url"],
    },
    output: {
      schema: {
        type: "object",
        properties: { ok: { type: "boolean" }, url: { type: "string" }, body: { type: "string" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: [
            `${value.ok ? "loaded" : "failed"} ${value.url ?? ""} on ${value.device ?? ""}`,
            "--- page ---",
            String(value.body ?? "").slice(0, 4000),
          ].join("\n"),
        },
      ],
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (typeof args?.url !== "string" || args.url.trim() === "") {
        throw new Error("pt_http_get needs a non-empty `url`.");
      }
      const cli = ["http", String(args.device ?? ""), args.url];
      if (typeof args?.out === "string" && args.out) cli.push("--out", args.out);
      if (typeof args?.wait_ms === "number" && Number.isFinite(args.wait_ms)) {
        cli.push("--wait", String(args.wait_ms / 1000));
      }
      return runEngine(engineConfig, cli, {
        timeout: timeoutFor("open"),
        module: "ptforge.guitool",
        json: false,
      });
    },
  });
  ctx.tools.register({
    name: "pt_server_page",
    description:
      "Read or replace the HTML a Server-PT serves. Packet Tracer keeps each server's web root inside the .pkt, so the page can be rewritten offline: action=list shows the pages, action=get returns one page's HTML, action=set writes new HTML (and optionally a new out file). No GUI needed.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt" },
        action: { type: "string", enum: ["list", "get", "set"], description: "What to do (default get)" },
        device: { type: "string", description: "Server name (default: the first Server-PT in the file)" },
        name: { type: "string", description: "Page filename (default index.html)" },
        html: { type: "string", description: "HTML to write (action=set)" },
        html_file: { type: "string", description: "Read the HTML from this file instead" },
        out: { type: "string", description: "Write the modified .pkt here instead of in place" },
      },
      required: ["file"],
    },
    output: {
      schema: {
        type: "object",
        properties: { device: { type: "string" }, page: { type: "string" }, html: { type: "string" }, pages: { type: "array" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: value.pages
            ? `${value.device}: ${(value.pages ?? []).join(", ")}`
            : `${value.device}:${value.page ?? ""} (${String(value.html ?? "").length} chars)\n${String(value.html ?? "").slice(0, 2000)}`,
        },
      ],
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => false,
    async execute(args) {
      const action = args?.action ?? "get";
      const cli = ["web", action, String(args?.file ?? "")];
      if (typeof args?.device === "string" && args.device) cli.push("--device", args.device);
      if (typeof args?.name === "string" && args.name) cli.push("--name", args.name);
      if (typeof args?.html_file === "string" && args.html_file) cli.push("--html-file", args.html_file);
      else if (typeof args?.html === "string") cli.push("--html", args.html);
      if (typeof args?.out === "string" && args.out) cli.push("-o", args.out);
      return runEngine(engineConfig, cli, { timeout: timeoutFor("inspect") });
    },
  });
  ctx.tools.register({
    name: "pt_ftp",
    description:
      "Run an FTP session from a PC console against a server and return the transcript. Prompts are driven step by step (Username:, Password:, ftp>) rather than by fixed sleeps. Defaults to the Packet Tracer server credentials cisco/cisco and a single `dir` command. Needs the PC's Command Prompt window open.",
    parameters: {
      type: "object",
      properties: {
        device: { type: "string", description: "PC name whose Command Prompt is open" },
        server: { type: "string", description: "FTP server address" },
        username: { type: "string", description: "FTP username (default cisco)" },
        password: { type: "string", description: "FTP password (default cisco)" },
        commands: { type: "array", items: { type: "string" }, description: "FTP commands to run before quitting (default [dir])" },
        out: { type: "string", description: "Screenshot output path" },
        wait_ms: { type: "number", description: "Milliseconds to wait for each prompt (default 3000)" },
      },
      required: ["device", "server"],
    },
    output: {
      schema: {
        type: "object",
        properties: { ok: { type: "boolean" }, steps: { type: "array" }, output: { type: "string" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: [
            `${value.ok ? "session ok" : "session incomplete"}: ${(value.steps ?? []).length} steps`,
            ...(value.steps ?? []).map((item) => `  ${item.ok ? "ok  " : "FAIL"} ${item.step} -> ${item.prompt}`),
            String(value.output ?? "").trim().slice(-2500),
          ].join("\n"),
        },
      ],
    },
    timeoutMs: timeoutFor("open"),
    isConcurrencySafe: () => false,
    async execute(args) {
      if (typeof args?.server !== "string" || args.server.trim() === "") {
        throw new Error("pt_ftp needs a non-empty `server`.");
      }
      const cli = ["ftp", String(args.device ?? ""), args.server];
      if (typeof args?.username === "string" && args.username) cli.push("--user", args.username);
      if (typeof args?.password === "string" && args.password) cli.push("--password", args.password);
      for (const command of Array.isArray(args?.commands) ? args.commands : []) cli.push("--cmd", String(command));
      if (typeof args?.out === "string" && args.out) cli.push("--out", args.out);
      if (typeof args?.wait_ms === "number" && Number.isFinite(args.wait_ms)) {
        cli.push("--wait", String(args.wait_ms / 1000));
      }
      return runEngine(engineConfig, cli, {
        timeout: timeoutFor("open"),
        module: "ptforge.guitool",
        json: false,
      });
    },
  });
  ctx.tools.register({
    name: "pt_note",
    description:
      "List or edit the text notes drawn on the topology canvas. Notes are stored inside the .pkt, so labels like `f0/0 172.16.10.254` can ship with the topology instead of being painted on afterwards. action=add anchors next to a device by default.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt" },
        action: { type: "string", enum: ["list", "add", "set", "remove"], description: "What to do (default list)" },
        text: { type: "string", description: "Note text (action=add/set)" },
        device: { type: "string", description: "Anchor the note next to this device" },
        x: { type: "number", description: "Explicit canvas X instead of a device anchor" },
        y: { type: "number", description: "Explicit canvas Y instead of a device anchor" },
        dx: { type: "number", description: "Offset from the device anchor (default 0)" },
        dy: { type: "number", description: "Offset from the device anchor (default -60)" },
        index: { type: "number", description: "Note index for action=set/remove" },
        out: { type: "string", description: "Write to this path instead of editing in place" },
      },
      required: ["file"],
    },
    output: {
      schema: { type: "object", properties: { notes: { type: "array" }, text: { type: "string" } } },
      render: (_args, value) => [
        {
          type: "text",
          text: Array.isArray(value.notes) && value.notes.length
            ? value.notes.map((item) => `(${item.x},${item.y}) ${item.text.split("\n")[0]}`).join("\n")
            : value.text
              ? `note: ${value.text} @ (${value.x},${value.y})`
              : "no notes",
        },
      ],
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => false,
    async execute(args) {
      const cli = ["note", String(args?.file ?? "")];
      const action = typeof args?.action === "string" ? args.action : "list";
      if (action === "list") cli.push("--list");
      if (action === "set") cli.push("--set-index", String(args?.index ?? 0), "--text", String(args?.text ?? ""));
      if (action === "remove") cli.push("--remove", String(args?.index ?? 0));
      if (action === "add") {
        cli.push("--text", String(args?.text ?? ""));
        if (typeof args?.device === "string" && args.device) cli.push("--device", args.device);
        if (typeof args?.x === "number") cli.push("--x", String(args.x));
        if (typeof args?.y === "number") cli.push("--y", String(args.y));
        if (typeof args?.dx === "number") cli.push("--dx", String(args.dx));
        if (typeof args?.dy === "number") cli.push("--dy", String(args.dy));
      }
      if (typeof args?.out === "string" && args.out) cli.push("-o", args.out);
      return runEngine(engineConfig, cli, { timeout: timeoutFor("inspect") });
    },
  });
  ctx.tools.register({
    name: "pt_state",
    description:
      "Read structured, assertable state out of a .pkt: per-device interface addresses, static routes, NAT statements, ACLs, switchport VLANs and hostname. Optional `device` narrows the report to one device. Packet Tracer only stores configuration, so this reflects what the file can prove, not live counters.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt to read" },
        device: { type: "string", description: "Only report this device (case-insensitive)" },
      },
      required: ["file"],
    },
    output: {
      schema: {
        type: "object",
        properties: { version: { type: "string" }, devices: { type: "array" } },
      },
      render: (args, value) => {
        if (args?.device) {
          const dev = value;
          const lines = [`${dev.name}  ${dev.kind ?? ""}  ${dev.model ?? ""}  hostname=${dev.hostname ?? "-"}`];
          for (const iface of dev.interfaces ?? []) {
            if (!iface.ip) continue;
            const prefix = iface.prefix == null ? "" : `/${iface.prefix}`;
            lines.push(`  ${iface.name} ${iface.ip}${prefix}${iface.gateway ? ` gw ${iface.gateway}` : ""}`);
          }
          for (const route of dev.static_routes ?? []) lines.push(`  route ${route.cidr} via ${route.next_hop}`);
          for (const line of dev.nat ?? []) lines.push(`  ${line}`);
          return [{ type: "text", text: lines.join("\n") }];
        }
        const lines = [`version ${value.version}`];
        for (const dev of value.devices ?? []) {
          const addresses = (dev.interfaces ?? [])
            .filter((i) => i.ip)
            .map((i) => `${i.name} ${i.ip}${i.prefix == null ? "" : `/${i.prefix}`}`);
          lines.push(`  ${dev.name} (${dev.kind ?? "?"})${addresses.length ? ` ${addresses.join(", ")}` : ""}`);
        }
        return [{ type: "text", text: lines.join("\n") }];
      },
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => true,
    async execute(args) {
      if (typeof args?.file !== "string" || args.file.trim() === "") {
        throw new Error("pt_state needs a non-empty `file` path.");
      }
      const cli = ["state", args.file];
      if (typeof args?.device === "string" && args.device) cli.push("--device", args.device);
      return runEngine(engineConfig, cli, { timeout: timeoutFor("inspect") });
    },
  });

  ctx.tools.register({
    name: "pt_check",
    description:
      "Assert expectations against a .pkt and return pass/fail per item with line-level differences. Each expectation is an object such as {device:'R1', route:'172.18.20.0/24'}, {device:'R1', interface:'Gi0/0', ip:'10.1.0.1'}, {device:'SW1', interface:'Fa0/1', access_vlan:10}, {device:'R1', nat:'inside'} or {device:'R1', config_contains:'ip nat inside'}.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt to check" },
        expect: { type: "array", items: { type: "object" }, description: "Expectation objects" },
      },
      required: ["file", "expect"],
    },
    output: {
      schema: { type: "object", properties: { ok: { type: "boolean" }, results: { type: "array" } } },
      render: (_args, value) => {
        const lines = (value.results ?? []).map((item) => {
          const mark = item.ok ? "PASS" : "FAIL";
          const detail = item.ok ? item.evidence.join("; ") : item.problems.join("; ");
          return `${mark} ${item.device}: ${JSON.stringify(item.expect)}${detail ? ` -> ${detail}` : ""}`;
        });
        return [{ type: "text", text: [`${value.ok ? "all checks passed" : "checks failed"}`, ...lines].join("\n") }];
      },
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (typeof args?.file !== "string" || args.file.trim() === "") {
        throw new Error("pt_check needs a non-empty `file` path.");
      }
      if (!Array.isArray(args?.expect) || args.expect.length === 0) {
        throw new Error("pt_check needs a non-empty `expect` array.");
      }
      const dir = await mkdtemp(path.join(os.tmpdir(), "ptforge-"));
      const specPath = path.join(dir, "expect.json");
      await writeFile(specPath, JSON.stringify({ expect: args.expect }, null, 2), "utf8");
      return runEngine(engineConfig, ["check", args.file, "--expect", specPath], {
        timeout: timeoutFor("inspect"),
        okCodes: [0, 1],
      });
    },
  });

  ctx.tools.register({
    name: "pt_patch",
    description:
      "Apply incremental edits to an existing .pkt instead of rebuilding it: set_ipv4, set_config (append or replace), rename, set_switchport and remove_config. Writes once and returns the change list.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt to modify" },
        ops: {
          type: "array",
          items: { type: "object" },
          description:
            "Operations, e.g. {op:'set_ipv4',device:'PC0',port:'FastEthernet0',address:'192.168.10.10',mask:'255.255.255.0',gateway:'192.168.10.1'} or {op:'set_switchport',device:'SW1',port:'FastEthernet0/1',vlan:10}",
        },
        out: { type: "string", description: "Write to this path instead of editing in place" },
      },
      required: ["file", "ops"],
    },
    output: {
      schema: {
        type: "object",
        properties: { path: { type: "string" }, ops: { type: "array" }, bytes: { type: "number" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: [`patched ${value.path} (${value.bytes} bytes)`, ...(value.ops ?? []).map((op) => `  ${op.op} ${op.device ?? ""}`)].join("\n"),
        },
      ],
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      if (typeof args?.file !== "string" || args.file.trim() === "") {
        throw new Error("pt_patch needs a non-empty `file` path.");
      }
      if (!Array.isArray(args?.ops) || args.ops.length === 0) {
        throw new Error("pt_patch needs a non-empty `ops` array.");
      }
      const dir = await mkdtemp(path.join(os.tmpdir(), "ptforge-"));
      const opsPath = path.join(dir, "ops.json");
      await writeFile(opsPath, JSON.stringify({ ops: args.ops }, null, 2), "utf8");
      const cli = ["patch", args.file, "--ops", opsPath];
      if (typeof args?.out === "string" && args.out) cli.push("-o", args.out);
      return runEngine(engineConfig, cli, { timeout: timeoutFor("inspect") });
    },
  });

  ctx.tools.register({
    name: "pt_doctor",
    description:
      "Check that this host can actually run the topology: Packet Tracer executable, Pillow availability, and whether a .pkt decodes as a 8.1.x container with devices. Returns actionable issues instead of letting a broken file reach Packet Tracer.",
    parameters: {
      type: "object",
      properties: { file: { type: "string", description: "Optional .pkt to verify" } },
    },
    output: {
      schema: {
        type: "object",
        properties: { ok: { type: "boolean" }, environment: { type: "object" }, file: { type: "object" } },
      },
      render: (_args, value) => {
        const lines = [];
        const env = value.environment ?? {};
        lines.push(`packet tracer: ${env.packet_tracer ?? "missing"}`);
        for (const issue of env.issues ?? []) lines.push(`  ! ${issue}`);
        if (value.file) {
          lines.push(`file: ${value.file.path} version=${value.file.version} devices=${value.file.devices} links=${value.file.links}`);
          for (const issue of value.file.issues ?? []) lines.push(`  ! ${issue}`);
        }
        lines.unshift(value.ok ? "environment ok" : "environment has problems");
        return [{ type: "text", text: lines.join("\n") }];
      },
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => true,
    async execute(args) {
      const cli = ["doctor"];
      if (typeof args?.file === "string" && args.file) cli.push(args.file);
      return runEngine(engineConfig, cli, { timeout: timeoutFor("inspect") });
    },
  });

  ctx.tools.register({
    name: "pt_report",
    description:
      "Turn a verified .pkt into report material: writes <out>/figures/, <out>/captions.json and <out>/report.md with device, address and link tables plus any figure entries supplied. Optional `figures` entries look like {path:'figures/topology.png', caption:'逻辑拓扑'}.",
    parameters: {
      type: "object",
      properties: {
        file: { type: "string", description: "Path to the .pkt to summarise" },
        out_dir: { type: "string", description: "Output directory (default ./report)" },
        title: { type: "string", description: "Report title" },
        figures: { type: "array", items: { type: "object" }, description: "Figure entries to include" },
      },
      required: ["file"],
    },
    output: {
      schema: {
        type: "object",
        properties: { dir: { type: "string" }, report: { type: "string" }, addresses: { type: "number" }, links: { type: "number" } },
      },
      render: (_args, value) => [
        {
          type: "text",
          text: `report written to ${value.dir} (${value.addresses} addresses, ${value.links} links) -> ${value.report}`,
        },
      ],
    },
    timeoutMs: timeoutFor("inspect"),
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (typeof args?.file !== "string" || args.file.trim() === "") {
        throw new Error("pt_report needs a non-empty `file` path.");
      }
      const outDir = typeof args?.out_dir === "string" && args.out_dir ? args.out_dir : path.join(path.dirname(args.file), "report");
      const cli = ["report", args.file, "-o", outDir];
      if (typeof args?.title === "string" && args.title) cli.push("--title", args.title);
      if (Array.isArray(args?.figures) && args.figures.length > 0) {
        const dir = await mkdtemp(path.join(os.tmpdir(), "ptforge-"));
        const figPath = path.join(dir, "figures.json");
        await writeFile(figPath, JSON.stringify(args.figures, null, 2), "utf8");
        cli.push("--figure", figPath);
      }
      return runEngine(engineConfig, cli, { timeout: timeoutFor("inspect") });
    },
  });
}













