/* The write-enabled reporter consumes API metadata only, never PR code/artifacts. */
const START = '<!-- maintenance-dashboard:start -->';
const END = '<!-- maintenance-dashboard:end -->';
const REQUIRED_PR_JOBS = ['test (3.11)', 'test (3.12)', 'test (3.13)', 'test (3.14)',
  'compose', 'Container build, protocol and security', 'Maintenance reporter dry run', 'analyze'];

function checkState(runs, statuses) {
  // GitHub returns newest first; only the latest result for each check/context counts.
  const latest = new Map();
  for (const run of runs) {
    const key = `${run.app?.id || ''}:${run.name}`;
    if (!latest.has(key)) latest.set(key, run);
  }
  const contexts = new Map();
  for (const status of statuses) if (!contexts.has(status.context)) contexts.set(status.context, status);
  const failed = [...latest.values()].some(r => r.status === 'completed' &&
    !['success', 'neutral', 'skipped'].includes(r.conclusion)) ||
    [...contexts.values()].some(s => ['error', 'failure'].includes(s.state));
  const pending = [...latest.values()].some(r => r.status !== 'completed') ||
    [...contexts.values()].some(s => s.state === 'pending');
  const passed = [...latest.values()].some(r => r.conclusion === 'success') ||
    [...contexts.values()].some(s => s.state === 'success');
  // This helper summarizes PR checks. The published-image job is intentionally
  // scheduled/manual-only; every other skipped/neutral check needs inspection.
  const unknown = [...latest.values()].some(r => ['skipped', 'neutral'].includes(r.conclusion) &&
    !(r.name === 'Published image security' && r.app?.slug === 'github-actions'));
  if (failed) return 'Blocked: inspect failed checks';
  if (pending) return 'Waiting for checks';
  if (unknown) return 'Unknown: skipped or neutral checks require coverage verification';
  if (!passed) return 'Unknown: no successful checks reported';
  if (!REQUIRED_PR_JOBS.every(name => [...latest.values()].some(r =>
    r.name === name && r.app?.slug === 'github-actions' && r.conclusion === 'success'))) {
    return 'Unknown: required PR jobs are missing or not verified as successful';
  }
  return 'Reported checks passed; verify required coverage and review';
}

function scheduledJobsPassed(file, jobs) {
  const required = file === 'codeql.yml' ? ['analyze'] :
    ['Container build, protocol and security', 'Published image security', 'Maintenance reporter dry run'];
  return required.every(name => jobs.some(job => job.name === name &&
    job.status === 'completed' && job.conclusion === 'success'));
}

function mergeBody(existing, managed) {
  const start = existing.indexOf(START), end = existing.indexOf(END);
  if (start < 0 || end < start) throw new Error('Dashboard markers missing; preserve human content');
  return existing.slice(0, start) + START + '\n' + managed + '\n' + existing.slice(end);
}

function completedCodexSummary(comments, repo, number, sha) {
  return comments.some(comment => {
    if (comment.user?.login !== 'chatgpt-codex-connector[bot]') return false;
    const match = comment.body?.match(/<!-- codex-security-review:v1 (\{[^\n]+\}) -->/);
    if (!match) return false;
    try {
      const status = JSON.parse(match[1]);
      return status.repository === `${repo.owner}/${repo.repo}` &&
        status.pullRequestNumber === number && status.headSha === sha &&
        status.status === 'completed' &&
        comment.body.includes('| 📝 **Code Review** | ✅ **Completed**') &&
        comment.body.includes('| 🔒 **Security Review** | ✅ **Completed**');
    } catch {
      return false; // An unfamiliar summary is unknown, never evidence of approval.
    }
  });
}

async function run({github, context, core}) {
  const repo = context.repo;
  const {data: metadata} = await github.rest.repos.get(repo);
  const branch = metadata.default_branch;
  const now = Date.now();
  const pending = [];
  const coverage = [];
  const prs = await github.paginate(github.rest.pulls.list, {...repo, state: 'open', per_page: 100});
  for (const pr of prs) {
    const checks = await github.paginate(github.rest.checks.listForRef,
      {...repo, ref: pr.head.sha, filter: 'latest', per_page: 100});
    const statuses = await github.paginate(github.rest.repos.listCommitStatusesForRef,
      {...repo, ref: pr.head.sha, per_page: 100});
    const reviews = await github.paginate(github.rest.pulls.listReviews,
      {...repo, pull_number: pr.number, per_page: 100});
    const comments = await github.paginate(github.rest.issues.listComments,
      {...repo, issue_number: pr.number, per_page: 100});
    const codex = reviews.filter(r => r.commit_id === pr.head.sha &&
      r.user?.login === 'chatgpt-codex-connector[bot]' && r.state !== 'DISMISSED');
    const age = Math.floor((now - Date.parse(pr.updated_at)) / 86400000);
    // Clean reviews can finish with a bot summary/reaction instead of a review object.
    const reviewed = codex.length || completedCodexSummary(comments, repo, pr.number, pr.head.sha);
    const review = reviewed ? 'Codex review present on current revision; inspect findings' :
      'No Codex review verified on current revision';
    pending.push(`- [ ] PR #${pr.number}: ${checkState(checks, statuses)}. ${review}. ` +
      `${pr.draft ? 'Draft. ' : ''}${age >= 7 ? `No update for ${age} days. ` : ''}` +
      `[Open PR](https://github.com/${repo.owner}/${repo.repo}/pull/${pr.number}).`);
  }

  for (const [file, maxDays, event] of [
    ['maintenance.yml', 2, 'schedule'], ['codeql.yml', 8, 'schedule'],
  ]) {
    if (file === 'codeql.yml' && metadata.private) {
      coverage.push('- Private CodeQL coverage must be checked against the repository licence/opt-in.');
    }
    const runs = await github.paginate(github.rest.actions.listWorkflowRuns,
      {...repo, workflow_id: file, branch, event, per_page: 100});
    const latest = runs[0];
    // A green PR/push run does not prove that the scheduled published-image scan ran.
    if (!latest || now - Date.parse(latest.created_at) > maxDays * 86400000) {
      pending.push(`- [ ] Monitoring gap: no recent scheduled run of ${file}. Check Actions scheduling.`);
    } else if (latest.status !== 'completed') {
      coverage.push(`- ${file}: [scheduled run in progress](${latest.html_url}); results pending.`);
    } else if (latest.conclusion !== 'success') {
      pending.push(`- [ ] Monitoring/security check needs attention: [${file}](${latest.html_url}) ` +
        `ended ${latest.conclusion}. A failure is not by itself evidence of a vulnerability.`);
    } else {
      const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun,
        {...repo, run_id: latest.id, filter: 'latest', per_page: 100});
      if (scheduledJobsPassed(file, jobs)) {
        coverage.push(`- ${file}: [scheduled jobs passed](${latest.html_url}) at ${latest.updated_at}.`);
      } else {
        pending.push(`- [ ] Monitoring gap: [${file}](${latest.html_url}) did not complete all required jobs successfully. ` +
          'Coverage is UNKNOWN; inspect skipped, missing or incomplete jobs.');
      }
    }
  }

  // Do not disclose advisory details or exploit information in a public dashboard.
  // Default GITHUB_TOKEN may not read Dependabot alerts; report denied coverage explicitly.
  for (const [name, route] of [
    ['Dependabot', 'GET /repos/{owner}/{repo}/dependabot/alerts'],
    ['Code scanning', 'GET /repos/{owner}/{repo}/code-scanning/alerts'],
  ]) {
    try {
      const alerts = await github.paginate(route, {...repo, state: 'open', per_page: 100});
      const critical = alerts.filter(a => (a.security_advisory?.severity ||
        a.rule?.security_severity_level) === 'critical').length;
      const high = alerts.filter(a => (a.security_advisory?.severity ||
        a.rule?.security_severity_level) === 'high').length;
      coverage.push(`- ${name}: ${alerts.length} open alerts (${critical} critical, ${high} high).`);
      if (alerts.length) pending.push(`- [ ] Triage ${name} alerts in the repository Security tab; ` +
        'confirm exposure, affected versions and fix availability.');
    } catch (error) {
      if (![403, 404].includes(error.status)) throw error;
      coverage.push(`- ${name}: UNKNOWN (${error.status}); access or feature enablement needs checking. ` +
        'No conclusion about the absence of vulnerabilities.');
      pending.push(`- [ ] Restore ${name} alert coverage: verify feature enablement and scoped read access.`);
    }
  }
  const managed = [
    '## To do', '', ...(pending.length ? pending : ['No pending items found in the checked sources.']),
    '', '## Coverage and evidence', '', ...coverage,
    '', 'This dashboard is generated. Record decisions outside the managed block.',
    'Checkboxes are status indicators, not permission to merge, publish or deploy.',
    'Image scans cover the published image and candidate; deployment state is not monitored here.',
  ].join('\n');
  const issues = await github.paginate(github.rest.issues.listForRepo,
    {...repo, state: 'open', creator: 'github-actions[bot]', per_page: 100});
  const dashboard = issues.find(i => !i.pull_request && i.body?.includes(START));
  if (!dashboard) {
    await github.rest.issues.create({...repo, title: 'Maintenance dashboard',
      body: `${START}\n${managed}\n${END}\n\n## Maintainer decisions\n\n`,
      assignees: [repo.owner]});
  } else {
    const body = mergeBody(dashboard.body, managed);
    if (body !== dashboard.body) await github.rest.issues.update({...repo,
      issue_number: dashboard.number, body});
  }
  await core.summary.addRaw(managed).write();
}

module.exports = run;
module.exports.checkState = checkState;
module.exports.mergeBody = mergeBody;
module.exports.completedCodexSummary = completedCodexSummary;
module.exports.scheduledJobsPassed = scheduledJobsPassed;
module.exports.REQUIRED_PR_JOBS = REQUIRED_PR_JOBS;
