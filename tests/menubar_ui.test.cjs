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
  assert.ok(ui.timers.at(-1).ms > 20000);
});

test('refresh cannot re-enable a running event or send it twice', async () => {
  const ui = popover();
  ui.run('let complete; let requests = 0; bridge = () => {requests++; return new Promise(resolve => { complete = resolve; });}; cfRefresh = async () => {};');
  const first = ui.run('cfRunEvent("example")');
  assert.match(ui.run('renderRunButton({id:"example"}, "")'), /disabled/);
  await ui.run('cfRunEvent("example")');
  assert.equal(ui.run('requests'), 1);
  ui.run('bridge = async () => ({id:"job", status:"succeeded", result:{success:true}}); complete({job_id:"job"})');
  await first;
  assert.doesNotMatch(ui.run('renderRunButton({id:"example"}, "")'), /disabled/);
});

test('a queued run is not reported complete before its worker finishes', async () => {
  const ui = popover();
  ui.run('let calls = []; bridge = async (op) => { calls.push(op); return op === "run-event" ? {job_id:"job"} : {id:"job", status:"failed", result:{success:false,error:"Example"}}; }; cfRefresh = async () => {};');
  await ui.run('cfRunEvent("example")');
  assert.equal(ui.run('calls.join(",")'), 'run-event,job-status');
  assert.match(ui.run('renderJobs()'), /Example/);
});

test('job diagnostics are escaped and cancellation is offered only for active work', () => {
  const ui = popover();
  ui.run('state.jobs = [{id:"job", kind:"script", status:"failed", result:{error:"<img src=x>"}}]');
  assert.match(ui.run('renderJobs()'), /&lt;img/);
  assert.doesNotMatch(ui.run('renderJobs()'), /onclick="cfCancelJob/);
  ui.run('state.jobs[0].status = "running"; state.jobs[0].cancellable = true');
  assert.match(ui.run('renderJobs()'), /onclick="cfCancelJob/);
});

test('Playbooks guards keyboard reentry and renders worker errors', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../runtime/menubar/recipes.html'), 'utf8');
  const nodes = new Map();
  const context = vm.createContext({
    window: {},
    document: { addEventListener() {}, getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {value:'+CalFlow+\nwait 0', innerHTML:'', classList:{add(){},remove(){},toggle(){}}});
      return nodes.get(id);
    }},
    setTimeout() {}, clearTimeout() {},
  });
  const run = code => vm.runInContext(code, context);
  run(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
  run('let requests = 0; let done; bridge = () => {requests++; return new Promise(resolve => {done = resolve;});};');
  const first = run('onRun()');
  await run('onRun()');
  assert.equal(run('requests'), 1);
  run('bridge = async () => ({status:"failed", result:{success:false,error:"<example>"}}); done({job_id:"job"});');
  await first;
  assert.match(nodes.get('console').innerHTML, /&lt;example&gt;/);
  assert.equal(nodes.get('btn-run').disabled, false);
  assert.equal(nodes.get('btn-cancel').hidden, true);
});
