/** Text renderers shared by the pt_* tools. Output stays bounded and scannable. */

const deviceWhere = (device) => {
  const logical = device.logical ?? {};
  if (typeof logical.x === "number" || typeof logical.y === "number") {
    return `(${logical.x ?? "?"},${logical.y ?? "?"})`;
  }
  return "";
};

export function renderTopology(payload, { title } = {}) {
  if (!payload || typeof payload !== "object") return "no topology data";
  const devices = Array.isArray(payload.devices) ? payload.devices : [];
  const links = Array.isArray(payload.links) ? payload.links : [];
  const lines = [];
  if (title) lines.push(`${title}: ${payload.path ?? ""}`);
  if (payload.bytes) lines.push(`bytes    ${payload.bytes}`);
  lines.push(`version  ${payload.version ?? "?"}`);
  lines.push(`devices  ${devices.length}`);
  for (const device of devices) {
    const config = Array.isArray(device.config) ? device.config : [];
    const suffix = config.length > 0 ? ` cfg=${config.length}` : "";
    lines.push(
      `  ${String(device.name).padEnd(14)} ${String(device.kind ?? "?").padEnd(10)} ${deviceWhere(device).padEnd(12)} ports=${(device.ports ?? []).length}${suffix}`,
    );
    for (const address of device.addresses ?? []) {
      lines.push(
        `      ${String(address.port ?? "?").padEnd(18)} ${address.ip}/${address.mask ?? "?"}${address.gateway ? ` gw ${address.gateway}` : ""}`,
      );
    }
    for (const line of config) lines.push(`      ${line}`);
  }
  lines.push(`links    ${links.length}`);
  for (const link of links) {
    lines.push(
      `  ${link.from} ${link.from_port ?? "?"} -> ${link.to} ${link.to_port ?? "?"} [${link.cable ?? "?"}]`,
    );
  }
  if (payload.opened) {
    lines.push(`opened   ${payload.opened.ok ? "yes" : "no"} ${payload.opened.title ?? ""}`);
  }
  return lines.join("\n");
}

export function renderModels(payload) {
  const models = Array.isArray(payload?.models) ? payload.models : [];
  const total = payload?.total ?? models.length;
  const lines = [`models ${models.length}/${total}`];
  for (const model of models) {
    const ports = Array.isArray(model.ports) ? model.ports : [];
    const shown = ports.slice(0, 8).join(", ");
    const rest = ports.length > 8 ? `, … (${ports.length})` : "";
    lines.push(`  ${String(model.model).padEnd(20)} ${String(model.kind ?? "?").padEnd(10)} ${shown}${rest}`);
  }
  return lines.join("\n");
}

export function renderApply(payload) {
  if (!payload || typeof payload !== "object") return "config not applied";
  const lines = [`path     ${payload.path}`, `device   ${payload.device}`];
  if (typeof payload.config_lines === "number") lines.push(`config   ${payload.config_lines} lines`);
  return lines.join("\n");
}
