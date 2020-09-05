#  Copyright 2020 G-Research
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging
import os
import re
import time
from collections import Counter
from typing import List, Dict

from github import Github
from pybuildkite.buildkite import Buildkite

from pybuildkiteext import artifacts as atf

# to prevent pybuildkiteext import to be auto-removed
if getattr(atf.Artifacts, 'download_artifact') is None:
    raise RuntimeError('patching pybuildkite Artifacts failed')


logger = logging.getLogger('download-buildkite-artifact')

INITIAL_DELAY = 5  # action initially delays accessing GitHub API for this number of seconds
POLL_SLEEP = 30    # action polls GitHub API and Buildkite API every this number of seconds
WAIT_ON_GITHUB_CHECK = 300  # seconds the action waits for a Buildkite check to appear on the commit
DEFAULT_GITHUB_BASE_URL = "https://api.github.com"


def get_buildkite_builds_from_github(api_url: str, token: str, repo: str, commit: str) -> List[str]:
    gh = Github(token, base_url=api_url)
    commit = gh.get_repo(repo).get_commit(commit)
    status = commit.get_combined_status()
    logger.debug('found {} status{}:'.format(status.total_count, '' if status.total_count == 1 else 'es'))
    for s in status.statuses:
        logger.debug('{} - {}'.format(s, s.target_url))

    return list([status.target_url
                 for status in status.statuses
                 if status.context.startswith('buildkite/')])


def parse_buildkite_url(url) -> (str, str, int):
    m = re.match('^http[s]?://buildkite.com/([^/]+)/([^/]+)/builds/([0-9]+)', url)
    if m:
        return m.group(1), m.group(2), int(m.group(3))

    return None


def get_build(token: str, org: str, pipeline: str, build_number: int) -> Dict:
    buildkite = Buildkite()
    buildkite.set_access_token(token)

    return buildkite.builds().get_build_by_number(org, pipeline, build_number)


def get_build_artifacts(token: str, org: str, pipeline: str, build_number: int) -> List[Dict]:
    buildkite = Buildkite()
    buildkite.set_access_token(token)

    list = buildkite.artifacts().list_artifacts_for_build

    page = 1
    artifacts = []
    while page:
        response = list(org, pipeline, build_number, page=page, with_pagination=True)
        for artifact in response.body:
            artifacts.append(artifact)
        page = response.next_page
        if page:
            logger.debug('fetching page {} of artifacts'.format(page))

    logger.debug('found {} artifact{}'.format(len(artifacts), '' if len(artifacts) == 1 else 's'))
    for artifact in artifacts:
        logger.debug('{} artifact: {}'.format(artifact.get('state'), artifact))

    return artifacts


def make_path_safe(string: str) -> str:
    safe_characters = "".join(c if c.isalnum() or c in ['-', '_'] else '-' for c in string).strip()
    reduced = safe_characters[:50]
    for pattern, repl in [('-+', '-'), ('^-+', ''), ('-+$', '')]:
        reduced = re.sub(pattern, repl, reduced)
    return reduced


def make_dict_path_safe(mapping: Dict[str, str]) -> Dict[str, str]:
    counts = Counter()
    safe_dict = dict()
    for id, name in mapping.items():
        safe_name = make_path_safe(name)
        counts[safe_name] += 1
        count = counts[safe_name]
        safe_dict[id] = safe_name if count == 1 else '{}_{}'.format(safe_name, count)
    return safe_dict


def download_artifacts(token: str, org: str, pipeline: str, build_number: int, artifacts: List[Dict],
                       path_safe_job_names: Dict[str, str], path: str) -> List[str]:
    buildkite = Buildkite()
    buildkite.set_access_token(token)

    root_path = os.path.abspath(path)

    def download_artifact(artifact_id: str, job_id: str, file_path: str):
        path_safe_job_name = path_safe_job_names.get(job_id, job_id)
        local_path = os.path.abspath(os.path.join(path, path_safe_job_name, file_path))
        if not local_path.startswith(root_path):
            raise RuntimeError("cannot write artifact to '{}' as output path is '{}'".format(local_path, root_path))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        artifact = buildkite.artifacts().download_artifact(org, pipeline, build_number, job_id, artifact_id)

        logger.info('writing {} bytes to {}'.format(len(artifact), local_path))
        with open(local_path, 'bw') as f:
            f.write(artifact)

        return local_path

    # download only the finished artifacts
    return list([download_artifact(artifact['id'], artifact['job_id'], artifact['path'])
                 for artifact in artifacts if artifact['state'] == 'finished'])


def main(github_api_url: str, github_token: str, repo: str, buildkite_token: str, buildkite_url: str, commit: str, output_path: str):
    if buildkite_url is None:
        # get the Buildkite url from github
        logger.debug('waiting {}s before contacting GitHub API the first time'.format(INITIAL_DELAY))

        start = time.time()
        time.sleep(INITIAL_DELAY)
        while True:
            buildkite_builds = get_buildkite_builds_from_github(github_api_url, github_token, repo, commit)
            if len(buildkite_builds) > 0:
                break

            if time.time() - start >= WAIT_ON_GITHUB_CHECK:
                logger.warning('waited {} seconds for a BuildKite check to appear on commit {}, '
                               'giving up'.format(WAIT_ON_GITHUB_CHECK, commit))
                return

            logger.debug('waiting {}s before contacting GitHub API again'.format(POLL_SLEEP))
            time.sleep(POLL_SLEEP)

        if not logger.isEnabledFor(logging.DEBUG):
            logger.info('found {} status{}'.format(len(buildkite_builds), '' if len(buildkite_builds) == 1 else 'es'))
    else:
        buildkite_builds = [buildkite_url]

    for url in buildkite_builds:
        org, pipeline, build_number = parse_buildkite_url(url)

        # wait until the Buildkite build terminates
        while True:
            build = get_build(buildkite_token, org, pipeline, build_number)
            if build['state'] not in ['running', 'scheduled', 'canceling']:
                logger.info('build is in ''{}'' state'.format(build.get('state')))
                break
            logger.debug('waiting {}s before contacting Buildkite API again'.format(POLL_SLEEP))
            time.sleep(POLL_SLEEP)

        # get a job-id -> name mapping from build
        job_names = dict([(job.get('id'), job.get('name'))
                          for job in build.get('jobs', [])
                          if 'name' in job])
        path_safe_job_names = make_dict_path_safe(job_names)

        # wait until the Buildkite all artifacts terminate
        while True:
            artifacts = get_build_artifacts(buildkite_token, org, pipeline, build_number)
            if any([artifact for artifact in artifacts if artifact['state'] == 'new']):
                break
            logger.debug('{} artifacts caused retry'.format(len([artifact for artifact in artifacts if artifact['state'] == 'new'])))
            for artifact in [artifact for artifact in artifacts if artifact['state'] == 'new']:
                logger.debug('artifact caused retry: {} {}'.format(artifact['state'] == 'new', artifact))
            logger.debug('waiting {}s before contacting Buildkite API again'.format(POLL_SLEEP))
            time.sleep(POLL_SLEEP)
        if not logger.isEnabledFor(logging.DEBUG):
            logger.info('found {} artifact{}'.format(len(artifacts), '' if len(artifacts) == 1 else 's'))

        # download the Buildkite artifacts
        download_artifacts(buildkite_token, org, pipeline, build_number, artifacts, path_safe_job_names, output_path)


def check_event_name(event: str = os.environ.get('GITHUB_EVENT_NAME')) -> None:
    # only checked when run by GitHub Actions GitHub App
    if os.environ.get('GITHUB_ACTIONS') is None:
        logger.warning('action not running on GitHub, skipping event name check')
        return

    if event is None:
        raise RuntimeError('No event name provided trough GITHUB_EVENT_NAME')

    logger.debug('action triggered by ''{}'' event'.format(event))
    if event != 'push':
        raise RuntimeError('Unsupported event, only ''push'' is supported: {}'.format(event))


if __name__ == "__main__":
    def get_var(name: str) -> str:
        return os.environ.get('INPUT_{}'.format(name)) or os.environ.get(name)

    logging.root.level = logging.INFO
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)5s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S %z')
    log_level = get_var('LOG_LEVEL') or 'INFO'
    logger.level = logging.getLevelName(log_level)

    # check event is supported
    check_event_name()

    github_api_url = os.environ.get('GITHUB_API_URL') or DEFAULT_GITHUB_BASE_URL
    github_token = get_var('GITHUB_TOKEN')
    github_repo = get_var('GITHUB_REPOSITORY')
    buildkite_token = get_var('BUILDKITE_TOKEN')
    buildkite_url = get_var('BUILDKITE_BUILD_URL')
    commit = get_var('COMMIT') or os.environ.get('GITHUB_SHA')
    output_path = get_var('OUTPUT_PATH') or '.'

    def check_var(var: str, name: str, label: str) -> None:
        if var is None:
            raise RuntimeError('{} must be provided via action input or environment variable {}'.format(label, name))

    check_var(github_token, 'GITHUB_TOKEN', 'GitHub token')
    check_var(github_repo, 'GITHUB_REPOSITORY', 'GitHub repository')
    check_var(buildkite_token, 'BUILDKITE_TOKEN', 'BuildKite token')
    check_var(commit, 'COMMIT', 'Commit')

    main(github_api_url, github_token, github_repo, buildkite_token, buildkite_url, commit, output_path)
