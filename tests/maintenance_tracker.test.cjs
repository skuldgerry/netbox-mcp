const test = require('node:test');
const assert = require('node:assert/strict');
const {checkState, mergeBody} = require('../scripts/maintenance_tracker.cjs');
const run = require('../scripts/maintenance_tracker.cjs');
const {completedCodexSummary} = run;
const passingJobs = () => run.REQUIRED_PR_JOBS.map(name =>
  ({name,app:{slug:'github-actions'},status:'completed',conclusion:'success'}));

test('unknown and skipped checks cannot look ready', () => {
  assert.match(checkState([], []), /Unknown/);
  assert.match(checkState([{name:'ci', status:'completed', conclusion:'skipped'}], []), /Unknown/);
  assert.match(checkState([{name:'tests', status:'completed', conclusion:'success'},
    {name:'analyze', status:'completed', conclusion:'skipped'}], []), /Unknown/);
  assert.match(checkState([...passingJobs(),
    {name:'Published image security', app:{slug:'github-actions'}, status:'completed', conclusion:'skipped'}], []), /passed/);
  assert.match(checkState([{name:'tests', status:'completed', conclusion:'success'},
    {name:'Published image security', app:{slug:'untrusted'}, status:'completed', conclusion:'skipped'}], []), /Unknown/);
});

test('missing required jobs stay unknown despite unrelated successful checks', () => {
  assert.match(checkState(passingJobs(), []), /passed/);
  for (const name of run.REQUIRED_PR_JOBS) {
    assert.match(checkState(passingJobs().filter(job => job.name !== name), []), /Unknown/);
  }
  assert.match(checkState(passingJobs().map(job => ({...job, app:{slug:'another-app'}})), []), /Unknown/);
});

test('scheduled success requires the actual security jobs, including the published image', () => {
  const success = name => ({name,status:'completed',conclusion:'success'});
  assert.equal(run.scheduledJobsPassed('codeql.yml', [success('analyze')]), true);
  assert.equal(run.scheduledJobsPassed('codeql.yml', [{name:'analyze',status:'completed',conclusion:'skipped'}]), false);
  assert.equal(run.scheduledJobsPassed('codeql.yml', []), false);
  const jobs = ['Container build, protocol and security','Published image security','Maintenance reporter dry run'].map(success);
  assert.equal(run.scheduledJobsPassed('maintenance.yml', jobs), true);
  jobs[1].conclusion = 'skipped';
  assert.equal(run.scheduledJobsPassed('maintenance.yml', jobs), false);
});
test('failed and pending checks override passing checks', () => {
  const passed = {name:'tests', status:'completed', conclusion:'success'};
  assert.match(checkState([passed, {name:'image', status:'completed', conclusion:'failure'}], []), /Blocked/);
  assert.match(checkState([passed, {name:'image', status:'queued'}], []), /Waiting/);
  assert.match(checkState([passed], [{context:'legacy', state:'failure'}]), /Blocked/);
});
test('latest retry supersedes an old failed attempt', () => {
  assert.match(checkState([...passingJobs(),
    {name:'test (3.11)', app:{slug:'github-actions'}, status:'completed', conclusion:'failure'}], []), /passed/);
});
test('human decisions outside generated block survive', () => {
  const before = 'Human note\n<!-- maintenance-dashboard:start -->\nold\n<!-- maintenance-dashboard:end -->\n- [x] Approved exception';
  const after = mergeBody(before, 'new');
  assert.ok(after.startsWith('Human note\n'));
  assert.ok(after.endsWith('- [x] Approved exception'));
  assert.throws(() => mergeBody('human replacement', 'new'), /preserve human/);
});

test('only completed bot summaries for this PR revision count as review evidence', () => {
  const repo = {owner: 'owner', repo: 'repo'};
  const metadata = {repository:'owner/repo', pullRequestNumber:11, headSha:'current', status:'completed'};
  const body = `<!-- codex-security-review:v1 ${JSON.stringify(metadata)} -->\n` +
    '| 📝 **Code Review** | ✅ **Completed** |\n| 🔒 **Security Review** | ✅ **Completed** |';
  const comment = {user: {login:'chatgpt-codex-connector[bot]'}, body};
  assert.equal(completedCodexSummary([comment], repo, 11, 'current'), true);
  assert.equal(completedCodexSummary([comment], repo, 11, 'newer'), false);
  assert.equal(completedCodexSummary([comment], repo, 12, 'current'), false);
  assert.equal(completedCodexSummary([{...comment,user:{login:'contributor'}}], repo, 11, 'current'), false);
  assert.equal(completedCodexSummary([{...comment,body:body.replace('📝 **Code Review** | ✅ **Completed**','📝 **Code Review** | Running')}], repo, 11, 'current'), false);
  assert.equal(completedCodexSummary([{...comment,body:'<!-- codex-security-review:v1 {invalid} -->'}], repo, 11, 'current'), false);
});

function reporterFixture({existing = [], denied = false} = {}) {
  const writes = [];
  const rest = {
    repos: {get: async () => ({data: {default_branch: 'main', private: false}}),
      listCommitStatusesForRef: 'statuses'},
    pulls: {list: 'prs', listReviews: 'reviews'},
    checks: {listForRef: 'checks'},
    actions: {listWorkflowRuns: 'runs'},
    issues: {listForRepo: 'issues', listComments: 'comments', create: async args => writes.push(args),
      update: async args => writes.push(args)},
  };
  const github = {rest, paginate: async (route, args) => {
    if (route === 'issues') return existing;
    if (route === 'runs') {
      assert.equal(args.event, 'schedule');
      assert.equal(args.branch, 'main');
      return [];
    }
    if (route.startsWith('GET ') && denied) throw Object.assign(new Error('Denied'), {status: 403});
    if (route.startsWith('GET ')) return [{security_advisory: {severity: 'critical'}}];
    return [];
  }};
  const notices = [];
  const core = {notice: message => notices.push(message),
    summary: {addRaw: () => ({write: async () => {}})}};
  return {github, context: {repo: {owner: 'owner', repo: 'repo'}}, core, writes, notices};
}

test('reporter creates one actionable dashboard for missing scans and denied alert access', async () => {
  const fixture = reporterFixture({denied: true});
  await run(fixture);
  assert.equal(fixture.writes.length, 1);
  const body = fixture.writes[0].body;
  assert.match(body, /Monitoring gap/);
  assert.match(body, /Restore Dependabot alert coverage/);
  assert.match(body, /UNKNOWN \(403\)/);
  assert.doesNotMatch(body, /No pending items/);
  assert.ok(fixture.notices.includes('Dependabot alert coverage UNKNOWN (403); the API read did not succeed.'));
  assert.ok(fixture.notices.every(message => !message.includes('read verified')));
});

test('successful alert API reads are observable independently of overall job success', async () => {
  const fixture = reporterFixture();
  await run(fixture);
  assert.ok(fixture.notices.includes('Dependabot alert read verified: 1 open (1 critical, 0 high).'));
  assert.ok(fixture.notices.includes('Code scanning alert read verified: 1 open (1 critical, 0 high).'));
});

test('reporter updates existing dashboard and skips unchanged writes', async () => {
  const fixture = reporterFixture();
  await run(fixture);
  const existing = [{number: 42, body: fixture.writes[0].body + 'Human decision: wait for approval.'}];
  const unchanged = reporterFixture({existing});
  await run(unchanged);
  assert.equal(unchanged.writes.length, 0);
  const changed = reporterFixture({existing, denied: true});
  await run(changed);
  assert.equal(changed.writes.length, 1);
  assert.equal(changed.writes[0].issue_number, 42);
  assert.ok(changed.writes[0].body.endsWith('Human decision: wait for approval.'));
});
