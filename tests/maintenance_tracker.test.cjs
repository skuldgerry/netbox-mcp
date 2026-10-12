const test = require('node:test');
const assert = require('node:assert/strict');
const {checkState, mergeBody} = require('../scripts/maintenance_tracker.cjs');

test('unknown and skipped checks cannot look ready', () => {
  assert.match(checkState([], []), /Unknown/);
  assert.match(checkState([{name:'ci', status:'completed', conclusion:'skipped'}], []), /Unknown/);
});
test('failed and pending checks override passing checks', () => {
  const passed = {name:'tests', status:'completed', conclusion:'success'};
  assert.match(checkState([passed, {name:'image', status:'completed', conclusion:'failure'}], []), /Blocked/);
  assert.match(checkState([passed, {name:'image', status:'queued'}], []), /Waiting/);
  assert.match(checkState([passed], [{context:'legacy', state:'failure'}]), /Blocked/);
});
test('latest retry supersedes an old failed attempt', () => {
  assert.match(checkState([{name:'tests', status:'completed', conclusion:'success'},
    {name:'tests', status:'completed', conclusion:'failure'}], []), /passed/);
});
test('human decisions outside generated block survive', () => {
  const before = 'Human note\n<!-- maintenance-dashboard:start -->\nold\n<!-- maintenance-dashboard:end -->\n- [x] Approved exception';
  const after = mergeBody(before, 'new');
  assert.ok(after.startsWith('Human note\n'));
  assert.ok(after.endsWith('- [x] Approved exception'));
  assert.throws(() => mergeBody('human replacement', 'new'), /preserve human/);
});
