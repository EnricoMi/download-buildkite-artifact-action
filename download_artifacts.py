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
import time

from typing import List, Tuple, Dict


logger = logging.getLogger('download-buildkite-artifact')

INITIAL_DELAY = 5  # action initially delays accessing GitHub API for this number of seconds
POLL_SLEEP = 30    # action polls GitHub API and Buildkite API every this number of seconds


def get_buildkite_builds_from_github(token: str, repo: str, commit: str) -> List[Tuple[str, str]]:
    from github import Github

    gh = Github(token)
    commit = gh.get_repo(repo).get_commit(commit)
    status = commit.get_combined_status()
    logger.info('found {} statuses'.format(status.total_count))
    for s in status.statuses:
        logger.debug('{} - {}'.format(s, s.target_url))

    return list([(status.state, status.target_url)
                 for status in status.statuses
                 if status.context.startswith('buildkite/')])


def parse_buildkite_url(url) -> (str, str, int):
    import re

    m = re.match('^http[s]?://buildkite.com/([^/]+)/([^/]+)/builds/([0-9]+)', url)
    if m:
        return m.group(1), m.group(2), int(m.group(3))

    return None


def get_build(token: str, org: str, pipeline: str, build_number: int) -> Dict:
    from pybuildkite.buildkite import Buildkite

    buildkite = Buildkite()
    buildkite.set_access_token(token)

    return buildkite.builds().get_build_by_number(org, pipeline, build_number)


def get_build_artifacts(token: str, org: str, pipeline: str, build_number: int) -> List[Dict]:
    from pybuildkite.buildkite import Buildkite

    buildkite = Buildkite()
    buildkite.set_access_token(token)

    artifacts = buildkite.artifacts().list_artifacts_for_build(org, pipeline, build_number)
    logger.info('found {} artifacts'.format(len(artifacts)))
    for artifact in artifacts:
        logger.debug('{} artifact: {}'.format(artifact['state'], artifact))

    return artifacts


def download_artifacts(token: str, org: str, pipeline: str, build_number: int, artifacts: List[Dict], path: str) -> List[str]:
    from pybuildkite.buildkite import Buildkite
    from pybuildkiteext import artifacts as atf

    buildkite = Buildkite()
    buildkite.set_access_token(token)

    root_path = os.path.abspath(path)

    def download_artifact(artifact_id: str, job_id: str, file_path: str):
        local_path = os.path.abspath(os.path.join(path, job_id, file_path))
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


def main(github_token: str, repo: str, buildkite_token: str, commit: str, output_path: str):
    # get the Buildkite context from github
    logger.debug('waiting {}s before contacting GitHub API the first time'.format(INITIAL_DELAY))
    time.sleep(INITIAL_DELAY)
    while True:
        buildkite_builds = get_buildkite_builds_from_github(github_token, repo, commit)
        if len(buildkite_builds) > 0:
            break
        logger.debug('waiting {}s before contacting GitHub API the next time'.format(POLL_SLEEP))
        time.sleep(POLL_SLEEP)

    for state, url in buildkite_builds:
        org, pipeline, build_number = parse_buildkite_url(url)

        # wait until the Buildkite build terminates
        while True:
            build = get_build(buildkite_token, org, pipeline, build_number)
            if build['state'] not in ['running, scheduled, canceling']:
                logger.info('build is in ''{}'' state'.format(build['state']))
                break
            logger.debug('waiting {}s before contacting Buildkite API the next time'.format(POLL_SLEEP))
            time.sleep(POLL_SLEEP)

        # wait until the Buildkite all artifacts terminate
        while True:
            artifacts = get_build_artifacts(buildkite_token, org, pipeline, build_number)
            if len(artifacts) > 0 and \
                    len([1 for artifact in artifacts if artifact['state'] == 'new']) == 0:
                break
            logger.debug('waiting {}s before contacting Buildkite API the next time'.format(POLL_SLEEP))
            time.sleep(POLL_SLEEP)

        # download the Buildkite artifacts
        download_artifacts(buildkite_token, org, pipeline, build_number, artifacts, output_path)


if __name__ == "__main__":
    def get_var(name: str) -> str:
        return os.environ.get('INPUT_{}'.format(name)) or os.environ.get(name)

    logging.root.level = logging.INFO
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S %z')
    log_level = get_var('LOG_LEVEL') or 'INFO'
    logger.level = logging.getLevelName(log_level)

    github_token = get_var('GITHUB_TOKEN')
    github_repo = get_var('GITHUB_REPOSITORY')
    buildkite_token = get_var('BUILDKITE_TOKEN')
    commit = get_var('COMMIT') or os.environ.get('GITHUB_SHA')
    output_path = get_var('OUTPUT_PATH') or '.'

    def check_var(var: str, name: str, label: str) -> None:
        if var is None:
            raise RuntimeError('{} must be provided via action input or environment variable {}'.format(label, name))

    check_var(github_token, 'GITHUB_TOKEN', 'GitHub token')
    check_var(github_repo, 'GITHUB_REPOSITORY', 'GitHub repository')
    check_var(buildkite_token, 'BUILDKITE_TOKEN', 'BuildKite token')
    check_var(commit, 'COMMIT', 'Commit')

    main(github_token, github_repo, buildkite_token, commit, output_path)
