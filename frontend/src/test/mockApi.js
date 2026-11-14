import { vi } from "vitest";

// Replace fetch with a router. routes: [[METHOD, RegExp|string, responder], ...]
// responder returns JSON (200) or { __status, detail } for an error. Calls are recorded.
export function mockApi(routes) {
  const calls = [];
  const fn = vi.fn(async (url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    calls.push({ method, url: String(url) });
    for (const [m, pattern, responder] of routes) {
      const hit = pattern instanceof RegExp ? pattern.test(url) : String(url).includes(pattern);
      if (m === method && hit) {
        const body = typeof responder === "function" ? responder(url, options) : responder;
        if (body && body.__status) {
          return { ok: false, status: body.__status, json: async () => ({ detail: body.detail }) };
        }
        return { ok: true, status: 200, json: async () => body };
      }
    }
    return { ok: false, status: 404, json: async () => ({ detail: `no mock for ${method} ${url}` }) };
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}
