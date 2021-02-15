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

import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import timedelta
from threading import Timer
from typing import List, Dict, Optional

import humanize
from github import Github
from pybuildkite.buildkite import Buildkite
from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

logger = logging.getLogger('download-buildkite-artifact')

INITIAL_DELAY = 5  # action initially delays accessing GitHub API for this number of seconds
POLL_SLEEP = 30    # action polls GitHub API and Buildkite API every this number of seconds
WAIT_ON_GITHUB_CHECK = 300  # seconds the action waits for a Buildkite check to appear on the commit
LOG_EVERY_SECONDS = 60*60   # some logging only occurs every X seconds
DEFAULT_GITHUB_BASE_URL = "https://api.github.com"


def get_buildkite_builds_from_github(api_url: str, token: str, repo: str, commit: str) -> List[str]:
    retry = Retry(total=10, backoff_factor=1)
    gh = Github(token, base_url=api_url, retry=retry)
    commit = gh.get_repo(repo).get_commit(commit)
    status = commit.get_combined_status()
    logger.debug('Found {} status{}:'.format(status.total_count, '' if status.total_count == 1 else 'es'))
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


def get_build(buildkite: Buildkite, org: str, pipeline: str, build_number: int) -> Dict:
    return buildkite.builds().get_build_by_number(org, pipeline, build_number, include_retried_jobs=True)


def get_build_artifacts(buildkite: Buildkite, org: str, pipeline: str, build_number: int) -> List[Dict]:
    list = buildkite.artifacts().list_artifacts_for_build

    page = 1
    artifacts = []
    while page:
        response = list(org, pipeline, build_number, page=page, with_pagination=True)
        for artifact in response.body:
            artifacts.append(artifact)
        page = response.next_page
        if page:
            logger.debug('Fetching page {} of artifacts.'.format(page))

    return artifacts


def make_path_safe(string: str) -> str:
    safe_characters = "".join(c if c.isalnum() or c in ['-', '_'] else '-' for c in string).strip()
    reduced = safe_characters[:75]
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


class Downloader:

    _timer: Optional[Timer] = None

    def download_artifacts(self, buildkite: Buildkite,
                           org: str, pipeline: str, build_number: int, artifacts: List[Dict],
                           path_safe_job_names: Dict[str, str], path: str) -> (List[str], List[str]):

        # download only the new and finished artifacts
        # sometimes artifacts are stuck in new state but can be downloaded just fine
        artifacts = [artifact
                     for artifact in artifacts
                     if artifact['state'] in ['new', 'finished']]

        logger.info('Downloading {} artifact{} from build {}.'.format(
            len(artifacts),
            '' if len(artifacts) == 1 else 's',
            build_number
        ))

        attempt = 1
        max_attempts = 5
        progress_interval = 20
        retry_artifact_ids = set()
        failed_artifact_ids = set()
        root_path = os.path.abspath(path)
        downloded_bytes = []

        def download_artifact(artifact_id: str, job_id: str, file_path: str):
            path_safe_job_name = path_safe_job_names.get(job_id, job_id)
            local_path = os.path.abspath(os.path.join(path, path_safe_job_name, file_path))
            if not local_path.startswith(root_path):
                raise RuntimeError("Cannot write artifact to '{}' as output path is '{}'".format(local_path, root_path))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            try:
                artifact = buildkite.artifacts().download_artifact(org, pipeline, build_number, job_id, artifact_id)

                logger.debug('Writing {} bytes to {}.'.format(len(artifact), local_path))
                with open(local_path, 'bw') as f:
                    f.write(artifact)
                downloded_bytes.append(len(artifact))

                return local_path
            except HTTPError as e:
                logger.debug(f'Downloading artifact {artifact_id} to {local_path} failed.', exc_info=e)
                if 500 <= e.response.status_code < 600:
                    retry_artifact_ids.add(artifact_id)
                else:
                    failed_artifact_ids.add(artifact_id)

        def get_progress_timer():
            timer = Timer(progress_interval, log_progress)
            timer.setDaemon(daemonic=True)
            timer.start()
            return timer

        def log_progress():
            logger.info('Downloaded {} artifact{} and {} so far ({:.1f}%).'.format(
                len(downloaded_files),
                '' if len(downloaded_files) == 1 else 's',
                humanize.naturalsize(sum(downloded_bytes), binary=True),
                len(downloaded_files) / max(len(artifacts), 1) * 100
            ))
            self._timer = get_progress_timer()

        downloaded_files = []
        while artifacts and attempt <= max_attempts:
            # start to log progress
            self._timer = get_progress_timer()

            for artifact in artifacts:
                file = download_artifact(artifact['id'], artifact['job_id'], artifact['path'])

                # memorize all successful download files
                if file is not None:
                    downloaded_files.append(file)

            # stop progress logging
            self._timer.cancel()

            # move failed artifacts that are in new state into retry
            failed_new_state_artifacts_ids = [artifact['id']
                                              for artifact in artifacts
                                              if artifact['id'] in failed_artifact_ids
                                              and artifact['state'] == 'new']
            retry_artifact_ids.update(failed_new_state_artifacts_ids)
            failed_artifact_ids.difference_update(failed_new_state_artifacts_ids)

            # prepare next attempt
            artifacts = [artifact
                         for artifact in artifacts
                         if artifact['id'] in retry_artifact_ids]
            retry_artifact_ids.clear()

            # compute delay to next attempt
            retry = attempt - 1
            wait = timedelta(seconds=5 * 4 ** retry)

            # log next attempt
            attempt += 1
            if artifacts and attempt <= max_attempts:
                logger.info('Download of {} artifact{} failed, retrying in {}.'.format(
                    len(artifacts),
                    '' if len(artifacts) == 1 else 's',
                    humanize.naturaldelta(wait)
                ))
                time.sleep(wait.seconds)
            elif artifacts:
                logger.warning('Download of {} artifact{} failed, giving up.'.format(
                    len(artifacts),
                    '' if len(artifacts) == 1 else 's'
                ))
                logger.debug('Failed artifacts:')
                for artifact in artifacts:
                    logger.debug(artifact)
                failed_artifact_ids.update([artifact['id'] for artifact in artifacts])

        logger.info('Downloaded {} artifact{} and {}{}.'.format(
            len(downloaded_files),
            '' if len(downloaded_files) == 1 else 's',
            humanize.naturalsize(sum(downloded_bytes)),
            ', {} artifact{} failed'.format(
                len(failed_artifact_ids),
                '' if len(failed_artifact_ids) == 1 else 's'
            ) if failed_artifact_ids else ''
        ))

        return downloaded_files, failed_artifact_ids


def main(github_api_url: str, github_token: str, repo: str,
         buildkite: Buildkite, buildkite_url: str,
         ignore_build_states: List[str], ignore_job_states: List[str],
         commit: str, output_path: str) -> bool:

    if buildkite_url is None:
        # get the Buildkite url from github
        logger.debug('Waiting {}s before contacting GitHub API the first time.'.format(INITIAL_DELAY))

        start = time.time()
        time.sleep(INITIAL_DELAY)
        while True:
            buildkite_builds = get_buildkite_builds_from_github(github_api_url, github_token, repo, commit)
            if len(buildkite_builds) > 0:
                break

            if time.time() - start >= WAIT_ON_GITHUB_CHECK:
                logger.warning('Waited {} for a BuildKite check to appear on commit {}, giving up.'.format(
                    humanize.naturaldelta(timedelta(seconds=WAIT_ON_GITHUB_CHECK)), commit
                ))
                return False

            logger.debug('Waiting {}s before contacting GitHub API again'.format(POLL_SLEEP))
            time.sleep(POLL_SLEEP)

        if not logger.isEnabledFor(logging.DEBUG):
            logger.info('Found {} status{}.'.format(len(buildkite_builds), '' if len(buildkite_builds) == 1 else 'es'))
    else:
        buildkite_builds = [buildkite_url]

    # downloads only the first non-skipped build
    for url in buildkite_builds:
        org, pipeline, build_number = parse_buildkite_url(url)
        print('::set-output name=build-number::{}'.format(build_number))
        logger.info('Waiting for build {} to finish.'.format(build_number))

        # wait until the Buildkite build terminates
        last_log = 0
        last_state = None
        while True:
            build = get_build(buildkite, org, pipeline, build_number)
            state = build['state']
            if state != last_state:
                logger.info('Build is in ''{}'' state.'.format(state))
                last_state = state
            if state not in ['running', 'scheduled', 'canceling']:
                break
            if time.time() - last_log >= LOG_EVERY_SECONDS:
                logger.debug('{} for build {} to finish.'.format(
                    'Still waiting' if last_log > 0 else 'Waiting',
                    build_number
                ))
                last_log = time.time()
            time.sleep(POLL_SLEEP)

        # set build state output
        state = build['state']
        print('::set-output name=build-state::{}'.format(state))
        if state in ignore_build_states:
            logger.info('Ignoring {} build.'.format(state))
            print('::set-output name=download-state::skipped'.format(state))
            print('::set-output name=download-paths::[]')
            print('::set-output name=download-files::0')
            continue

        # get a job-id -> name mapping from build
        job_names = dict([(job.get('id'), job.get('name'))
                          for job in build.get('jobs', [])
                          if 'name' in job])
        path_safe_job_names = make_dict_path_safe(job_names)

        # get job-id -> state mapping from build
        job_states = dict([(job.get('id'), job.get('state'))
                           for job in build.get('jobs', [])
                           if 'state' in job])

        # get all artifacts for that build
        artifacts = get_build_artifacts(buildkite, org, pipeline, build_number)
        logger.info('Found {} artifact{}.'.format(len(artifacts), '' if len(artifacts) == 1 else 's'))

        new_artifacts = [artifact for artifact in artifacts if artifact['state'] == 'new']
        if any(new_artifacts):
            logger.debug('{} artifacts still in new state.'.format(len(new_artifacts)))
            for artifact in new_artifacts:
                logger.debug('New artifact: {}.'.format(artifact))

        for ignore_job_state in ignore_job_states:
            ignore_artifacts = [artifact
                                for artifact in artifacts
                                if job_states.get(artifact['job_id']) == ignore_job_state]

            if any(ignore_artifacts):
                artifacts = [artifact for artifact in artifacts if artifact not in ignore_artifacts]
                logger.info('Ignoring {} artifact{} of {} jobs.'.format(
                    len(ignore_artifacts),
                    '' if len(ignore_artifacts) == 1 else 's',
                    ignore_job_state
                ))
                for artifact in ignore_artifacts:
                    logger.debug('Ignored artifact: {}'.format(artifact))

        # download the Buildkite artifacts
        downloaded_paths, failed_ids = Downloader().download_artifacts(
            buildkite, org, pipeline, build_number, artifacts, path_safe_job_names, output_path
        )

        # indicate success or failure as output
        print('::set-output name=download-state::{}'.format('success' if len(failed_ids) == 0 else 'failure'))

        # provide downloaded paths
        print('::set-output name=download-paths::{}'.format(downloaded_paths))

        # provide downloaded files
        print('::set-output name=download-files::{}'.format(len(downloaded_paths)))

        return len(failed_ids) == 0


def get_commit_sha(event: dict, event_name: str):
    logger.debug("Action triggered by '{}' event.".format(event_name))

    # https://developer.github.com/webhooks/event-payloads/
    if event_name.startswith('pull_request'):
        return event.get('pull_request', {}).get('head', {}).get('sha')

    # https://docs.github.com/en/free-pro-team@latest/actions/reference/events-that-trigger-workflows
    return os.environ.get('GITHUB_SHA')


if __name__ == "__main__":
    def get_var(name: str) -> str:
        return os.environ.get('INPUT_{}'.format(name)) or os.environ.get(name)

    logging.root.level = logging.INFO
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)5s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S %z')
    log_level = get_var('LOG_LEVEL') or 'INFO'
    logger.level = logging.getLevelName(log_level)

    github_api_url = os.environ.get('GITHUB_API_URL') or DEFAULT_GITHUB_BASE_URL
    github_token = get_var('GITHUB_TOKEN')
    github_repo = get_var('GITHUB_REPOSITORY')
    buildkite_token = get_var('BUILDKITE_TOKEN')
    buildkite_url = get_var('BUILDKITE_BUILD_URL')
    ignore_build_states = get_var('IGNORE_BUILD_STATES')
    ignore_build_states = ignore_build_states.split(',') if ignore_build_states else []
    ignore_job_states = get_var('IGNORE_JOB_STATES')
    ignore_job_states = ignore_job_states.split(',') if ignore_job_states else []

    def check_var(var: str, name: str, label: str) -> None:
        if var is None:
            raise RuntimeError('{} must be provided via action input or environment variable {}'.format(label, name))

    event = get_var('GITHUB_EVENT_PATH')
    event_name = get_var('GITHUB_EVENT_NAME')
    check_var(event, 'GITHUB_EVENT_PATH', 'GitHub event file path')
    check_var(event_name, 'GITHUB_EVENT_NAME', 'GitHub event name')
    with open(event, 'r') as f:
        event = json.load(f)

    commit = get_var('COMMIT') or get_commit_sha(event, event_name)
    output_path = get_var('OUTPUT_PATH') or '.'

    check_var(github_token, 'GITHUB_TOKEN', 'GitHub token')
    check_var(github_repo, 'GITHUB_REPOSITORY', 'GitHub repository')
    check_var(buildkite_token, 'BUILDKITE_TOKEN', 'BuildKite token')
    check_var(commit, 'COMMIT', 'Commit')

    buildkite = Buildkite()
    buildkite.set_access_token(buildkite_token)

    if not main(github_api_url, github_token, github_repo,
                buildkite, buildkite_url,
                ignore_build_states, ignore_job_states,
                commit, output_path):
        sys.exit(1)
