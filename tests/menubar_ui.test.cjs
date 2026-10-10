const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function popover() {
  const html = fs.readFileSync(path.join(__dirname, '../runtime/menubar/popover.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const timers = [];
  const context = vm.createContext({
    window: { addEventListener() {}, webkit: { messageHandlers: { cf: { postMessage() {} } } } },
    document: { getElementById() { return null; } },
    setInterval() {},
    setTimeout(fn, ms) { timers.push({ fn, ms }); },
    clearTimeout() {},
  });
  vm.runInContext(script, context);
  return { context, timers, run: code => vm.runInContext(code, context) };
}

test('refresh shows actual daemon state, including after reopening the menu', async () => {
  const ui = popover();
  ui.run('bridge = async () => ({status: {daemon: {loaded: false}}})');
  await ui.run('cfRefresh(true)');
  assert.equal(ui.run('state.paused'), true);
  ui.run('bridge = async () => ({status: {daemon: {loaded: true}}})');
  await ui.run('cfRefresh(true)');
  assert.equal(ui.run('state.paused'), false);
});

test('UI timeouts allow the native bridge to finish', () => {
  const ui = popover();
  ui.run('bridge("popover-feed")');
  assert.ok(ui.timers.at(-1).ms > 20000);
  ui.run('bridge("run-event", {id:"example"})');
  assert.ok(ui.timers.at(-1).ms > 60000);
});

test('refresh cannot re-enable a running event or send it twice', async () => {
  const ui = popover();
  ui.run('let complete; let requests = 0; bridge = () => {requests++; return new Promise(resolve => { complete = resolve; });}; cfRefresh = async () => {};');
  const first = ui.run('cfRunEvent("example")');
  assert.match(ui.run('renderRunButton({id:"example"}, "")'), /disabled/);
  await ui.run('cfRunEvent("example")');
  assert.equal(ui.run('requests'), 1);
  ui.run('complete({success:true})');
  await first;
  assert.doesNotMatch(ui.run('renderRunButton({id:"example"}, "")'), /disabled/);
});
