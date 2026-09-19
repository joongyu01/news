"""Replace one small usage snapshot; never persist GitHub credentials or history."""
import re
from datetime import datetime, timezone

import requests
import yaml

from .config import ROOT, env
from .spark_relay import update


def standard_runners():
    """Only claim free standard execution when every checked-in job qualifies."""
    jobs = []
    for path in (ROOT / '.github' / 'workflows').glob('*.y*ml'):
        workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        jobs.extend((workflow.get('jobs') or {}).values())
    return bool(jobs) and all(isinstance(job.get('runs-on'), str) and job['runs-on'] in
        ('ubuntu-latest', 'ubuntu-22.04', 'ubuntu-24.04') for job in jobs)


def collect():
    repo, token = env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or not token:
        raise RuntimeError('GitHub usage configuration missing')
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28'}
    snapshot = {'repository': repo, 'standard_runners': standard_runners(),
                'visibility': None, 'cache_bytes': None, 'rate': None, 'errors': {}}

    def get(section, path):
        try:
            response = requests.get('https://api.github.com' + path, headers=headers, timeout=10)
            if not response.ok:
                snapshot['errors'][section] = f'HTTP {response.status_code}'
                return None
            return response.json()
        except (requests.RequestException, ValueError):
            snapshot['errors'][section] = '조회 실패'
            return None

    info = get('repository', f'/repos/{repo}')
    if isinstance(info, dict) and info.get('visibility') in ('public', 'private', 'internal'):
        snapshot['visibility'] = info['visibility']
    cache = get('cache', f'/repos/{repo}/actions/cache/usage')
    if isinstance(cache, dict) and type(cache.get('active_caches_size_in_bytes')) is int:
        snapshot['cache_bytes'] = max(0, cache['active_caches_size_in_bytes'])
    snapshot['runs'] = {}
    for workflow in ('collect', 'dispatch', 'alerts'):
        result = get(workflow, f'/repos/{repo}/actions/workflows/{workflow}.yml/runs?per_page=4&branch=main')
        if isinstance(result, dict) and isinstance(result.get('workflow_runs'), list):
            snapshot['runs'][workflow] = [
                {key: run.get(key) for key in ('id', 'status', 'conclusion', 'event',
                    'run_started_at', 'updated_at', 'run_attempt')}
                for run in result['workflow_runs'][:4] if type(run.get('id')) is int
                and str(run['id']) != env('GITHUB_RUN_ID')][:3]
    # Last API read: remaining includes the metadata/cache/workflow requests above.
    rate = get('rate', '/rate_limit')
    core = (rate.get('resources') or {}).get('core') if isinstance(rate, dict) else None
    if isinstance(core, dict) and all(type(core.get(k)) is int and core[k] >= 0
                                    for k in ('limit', 'remaining', 'reset')):
        if core['remaining'] <= core['limit'] and core['reset'] <= 253402300799:
            snapshot['rate'] = {k: core[k] for k in ('limit', 'remaining', 'reset')}
    snapshot['checked_at'] = datetime.now(timezone.utc).isoformat()
    return snapshot


def main():
    snapshot = collect()
    update(lambda payload: payload.update({'github_usage': snapshot}))
    print('GitHub 사용량 스냅샷 갱신 완료' + (' · 일부 항목 조회 실패' if snapshot['errors'] else ''))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Request exceptions can include Authorization or a response body.
        print(f'GitHub 사용량 갱신 실패 ({type(error).__name__})')
        raise SystemExit(1)
