const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const template = readFileSync(
  resolve(__dirname, "../../CTFd/themes/core/templates/components/events-lifecycle.html"),
  "utf8",
);
const script = template.replace(/<\/?script>/g, "");

function fixture({ master = true, state = 1 } = {}) {
  const handlers = {};
  const sources = [];
  class EventSource {
    static CLOSED = 2;
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      sources.push(this);
    }
    close() {
      this.readyState = EventSource.CLOSED;
    }
  }
  const source = new EventSource("https://ctf.example/subdir/events");
  source.readyState = state;
  let connections = 0;
  let elections = 0;
  const events = {
    source,
    disconnect() { this.source.close(); },
    connect() { connections++; },
    controller: { isMaster: master, check() { elections++; } },
  };
  const window = { CTFd: { events }, addEventListener(name, handler) { handlers[name] = handler; } };
  runInNewContext(script, { window, EventSource });
  return { window, events, sources, dispatch: (name, data = {}) => handlers[name](data),
    connections: () => connections, elections: () => elections };
}

test("navigation closes both connecting and open streams before leaving", () => {
  for (const state of [0, 1]) {
    const f = fixture({ state });
    f.dispatch("beforeunload");
    assert.equal(f.events.source.readyState, 2);
  }
});

test("history caching closes the stream even when unload is prohibited", () => {
  const f = fixture();
  f.dispatch("pagehide", { persisted: true });
  assert.equal(f.events.source.readyState, 2);
  f.dispatch("pageshow", { persisted: true });
  assert.equal(f.sources.length, 2);
  assert.equal(f.events.source.url, "https://ctf.example/subdir/events");
  assert.equal(f.connections(), 1);
});

test("beforeunload followed by pagehide still reconnects exactly once on restore", () => {
  const f = fixture();
  f.dispatch("beforeunload");
  f.dispatch("pagehide", { persisted: true });
  f.dispatch("pageshow", { persisted: true });
  f.dispatch("pageshow", { persisted: true });
  assert.equal(f.sources.length, 2);
  assert.equal(f.connections(), 1);
});

test("restoration leaves notification ownership to the tab controller", () => {
  const f = fixture({ master: false });
  f.dispatch("pagehide", { persisted: true });
  f.dispatch("pageshow", { persisted: true });
  assert.equal(f.connections(), 0);
  assert.equal(f.elections(), 1);
});

test("initial load and streams already closed by tab coordination are unchanged", () => {
  const f = fixture({ state: 2 });
  f.dispatch("pageshow", { persisted: false });
  f.dispatch("pagehide", { persisted: true });
  f.dispatch("pageshow", { persisted: true });
  assert.equal(f.sources.length, 1);
  assert.equal(f.connections(), 0);
});

test("navigation before frontend initialization is safe", () => {
  const f = fixture();
  delete f.window.CTFd;
  assert.doesNotThrow(() => {
    f.dispatch("beforeunload");
    f.dispatch("pagehide");
    f.dispatch("pageshow", { persisted: true });
  });
});
