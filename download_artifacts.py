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


POLL_SLEEP = 30


def get_buildkite_builds_from_github(token: str, repo: str, owner: str, commit: str) -> List[Tuple[str, str]]:
    from github import Github

    gh = Github(token)
    commit = gh.get_user(owner).get_repo(repo).get_commit(commit)
    status = commit.get_combined_status()
    logging.info('found {} statuses'.format(status.total_count))
    for s in status.statuses:
        logging.debug('- {} - {}'.format(s, s.target_url))

    return list([(status.state, status.target_url)
                 for status in status.statuses
                 if status.context.startswith('buildkite/')])


def parse_buildkite_url(url) -> (str, str, int):
    import re

    m = re.match('^http[s]?://buildkite.com/([^/]+)/([^/]+)/builds/([0-9]+)', url)
    if m:
        return m.group(1), m.group(2), int(m.group(3))

    return None


def get_build_artifacts(token: str, org: str, pipeline: str, build: int) -> List[Dict]:
    from pybuildkite.buildkite import Buildkite

    buildkite = Buildkite()
    buildkite.set_access_token(token)

    artifacts = buildkite.artifacts().list_artifacts_for_build(org, pipeline, build)
    logger.info('found {} artifacts'.format(len(artifacts)))
    for artifact in artifacts:
        logging.debug('- {}'.format(artifact))

    return artifacts


def download_artifacts(token: str, org: str, pipeline: str, build: int, artifacts: List[Dict], path: str) -> List[str]:
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

        artifact = buildkite.artifacts().download_artifact(org, pipeline, build, job_id, artifact_id)

        logger.info('writing {}'.format(local_path))
        with open(local_path, 'bw') as f:
            f.write(artifact)

        return local_path

    return list([download_artifact(artifact['id'], artifact['job_id'], artifact['path'])
                 for artifact in artifacts])


def main(github_token: str, repo: str, repo_owner: str,
         buildkite_token: str, commit: str, output_path: str):
    while True:
        buildkite_builds = get_buildkite_builds_from_github(github_token, repo, repo_owner, commit)
        if len(buildkite_builds) > 0 and \
                len([1 for state, url in buildkite_builds if state == 'pending']) == 0:
            break
        time.sleep(POLL_SLEEP)

    for state, url in buildkite_builds:
        org, pipeline, build = parse_buildkite_url(url)

        while True:
            artifacts = get_build_artifacts(buildkite_token, org, pipeline, build)
            if len(artifacts) > 0 and \
                    len([1 for artifact in artifacts if artifact['state'] == 'new']) == 0:
                break
            time.sleep(POLL_SLEEP)

        download_artifacts(buildkite_token, org, pipeline, build, artifacts, output_path)


if __name__ == "__main__":
    log_level = os.environ.get('LOG_LEVEL') or 'INFO'
    logger = logging.getLogger()
    logger.level = logging.getLevelName(log_level)

    def get_var(name: str) -> str:
        return os.environ.get('INPUT_{}'.format(name)) or os.environ.get(name)

    github_token = get_var('GITHUB_TOKEN')
    github_repo = get_var('GITHUB_REPOSITORY')
    github_repo_owner = get_var('GITHUB_REPOSITORY_OWNER')
    buildkite_token = get_var('BUILDKITE_TOKEN')
    commit = get_var('COMMIT') or os.environ.get('GITHUB_SHA')
    output_path = get_var('OUTPUT_PATH') or '.'

    def check_var(var: str, name: str, label: str) -> None:
        if var is None:
            raise RuntimeError('{} must be provided via action input or environment variable {}'.format(label, name))

    check_var(github_token, 'GITHUB_TOKEN', 'GitHub token')
    check_var(github_repo, 'GITHUB_REPOSITORY', 'GitHub repository')
    check_var(github_repo_owner, 'GITHUB_REPOSITORY_OWNER', 'GitHub repository owner')
    check_var(buildkite_token, 'BUILDKITE_TOKEN', 'BuildKite token')
    check_var(commit, 'COMMIT', 'Commit')

    main(github_token, github_repo, github_repo_owner, buildkite_token, commit, output_path)
