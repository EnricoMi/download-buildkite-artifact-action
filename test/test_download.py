import tempfile
import unittest
from typing import Set, Mapping

import mock
from requests import Response

from download_artifacts import *


class DownloadTest(unittest.TestCase):

    def test_make_path_safe(self):
        self.assertEqual('', make_path_safe(''))
        self.assertEqual('abc', make_path_safe('abc'))
        self.assertEqual('abc-123-DEF', make_path_safe('abc 123  DEF'))
        self.assertEqual('some-paths', make_path_safe('some/paths/..'))
        self.assertEqual('some-characters', make_path_safe('some ⚡⚠✔✗ characters'))
        self.assertEqual('this-is-a-very-very-very-very-very-very-very-very-very-very-very-very-long',
                         make_path_safe('this is a very very very very very very very very very very very very long path'))

    def test_make_dict_path_safe(self):
        self.assertEqual(dict(), make_dict_path_safe(dict()))
        self.assertEqual(dict(id='name'), make_dict_path_safe(dict(id='name')))
        self.assertEqual(dict(id1='name1', id2='name2'), make_dict_path_safe(dict(id1='name1', id2='name2')))
        self.assertEqual(dict(id1='name', id2='name_2', id3='name3'), make_dict_path_safe(dict(id1='name', id2='name', id3='name3')))
        self.assertEqual(dict(id1='unsafe-name', id2='unsafe-name_2', id3='name3'), make_dict_path_safe(dict(id1='unsafe name', id2=' unsafe name', id3='name3')))
        self.assertEqual(
            dict(
                id1='this-is-a-very-very-very-very-very-very-very-very-very-very-very-very-long',
                id2='this-is-a-very-very-very-very-very-very-very-very-very-very-very-very-long_2'
            ),
            make_dict_path_safe(
                dict(
                    id1='this is a very very very very very very very very very very very very long path',
                    id2='this is a very very very very very very very very very very very very long path '
                )
            ))

    @staticmethod
    def error(code: int, message: str) -> HTTPError:
        response = Response()
        response.status_code = code
        response.reason = message
        return HTTPError('Exception', response=response)

    http404 = error.__func__(404, 'Not Found')
    http500 = error.__func__(500, 'Internal Server Error')

    def create_buildkite_mock(self,
                              artifact_ids: Set[str],
                              errors: Mapping[str, List[HTTPError]]=None):
        if errors is None:
            errors = dict()

        def download(org, pipeline, build_number, job_id, artifact_id):
            if artifact_id in errors:
                error = errors[artifact_id].pop()
                if len(errors[artifact_id]) == 0:
                    del errors[artifact_id]
                raise error
            elif artifact_id in artifact_ids:
                return str(artifact_id).encode('utf8')
            else:
                raise self.http404

        return mock.Mock(artifacts=mock.Mock(return_value=mock.Mock(download_artifact=mock.Mock(side_effect=download))))

    org = 'org'
    pipeline = 'pipeline'
    build_number = 12345

    def test_download_artifacts(self):
        buildkite = self.create_buildkite_mock(
            {'id1', 'id2', 'id3', 'id4', 'id5'},
            {'id6': [self.http404]}
        )
        artifacts = [
            {'id': 'id1', 'job_id': 'jid1', 'path': 'path1', 'state': 'unknown'},
            {'id': 'id2', 'job_id': 'jid2', 'path': 'path2', 'state': 'new'},
            {'id': 'id3', 'job_id': 'jid3', 'path': 'path3', 'state': 'error'},
            {'id': 'id4', 'job_id': 'jid4', 'path': 'path4', 'state': 'finished'},
            {'id': 'id5', 'job_id': 'jid5', 'path': 'path5', 'state': 'finished'},
            {'id': 'id6', 'job_id': 'jid6', 'path': 'path6', 'state': 'finished'},
        ]
        job_names = {artifact['id']: f'file-{artifact["id"]}' for artifact in artifacts}

        with tempfile.TemporaryDirectory() as path, \
                mock.patch('download_artifacts.logger') as logger, \
                mock.patch('download_artifacts.time.sleep') as time:

            download_artifacts(buildkite, self.org, self.pipeline, self.build_number, artifacts, job_names, path)
            for file in os.listdir(path):
                print(file)

            self.assertEqual([], time.mock_calls)

            self.assertEqual(
                [mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid4', 'id4'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid5', 'id5'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid6', 'id6')],
                buildkite.artifacts.return_value.download_artifact.mock_calls
            )

            self.assertEqual(
                [mock.call.info('Downloading 6 artifacts from build 12345'),
                 mock.call.debug(f'writing 3 bytes to {path}/jid2/path2'),
                 mock.call.debug(f'writing 3 bytes to {path}/jid4/path4'),
                 mock.call.debug(f'writing 3 bytes to {path}/jid5/path5'),
                 mock.call.debug(f'Downloading artifact id6 to {path}/jid6/path6 failed.', exc_info=self.http404)],
                logger.mock_calls
            )

    def test_download_artifacts_retry(self):
        buildkite = self.create_buildkite_mock(
            {'id1', 'id2', 'id3'},
            {'id2': [self.http500], 'id3': [self.http500, self.http500]}
        )
        artifacts = [
            {'id': 'id1', 'job_id': 'jid1', 'path': 'path1', 'state': 'finished'},
            {'id': 'id2', 'job_id': 'jid2', 'path': 'path2', 'state': 'finished'},
            {'id': 'id3', 'job_id': 'jid3', 'path': 'path3', 'state': 'finished'},
        ]
        job_names = {artifact['id']: f'file-{artifact["id"]}' for artifact in artifacts}

        with tempfile.TemporaryDirectory() as path, \
                mock.patch('download_artifacts.logger') as logger, \
                mock.patch('download_artifacts.time.sleep') as time:

            download_artifacts(buildkite, self.org, self.pipeline, self.build_number, artifacts, job_names, path)
            for file in os.listdir(path):
                print(file)

            self.assertEqual([mock.call(5), mock.call(20)], time.mock_calls)

            self.assertEqual(
                [mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid3', 'id3'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid3', 'id3'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid3', 'id3')],
                buildkite.artifacts.return_value.download_artifact.mock_calls
            )

            self.assertEqual(
                [mock.call.info('Downloading 3 artifacts from build 12345'),
                 mock.call.debug(f'writing 3 bytes to {path}/jid1/path1'),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id3 to {path}/jid3/path3 failed.', exc_info=self.http500),
                 mock.call.info('Download of 2 artifacts failed, retrying in 0:00:05.'),
                 mock.call.debug(f'writing 3 bytes to {path}/jid2/path2'),
                 mock.call.debug(f'Downloading artifact id3 to {path}/jid3/path3 failed.', exc_info=self.http500),
                 mock.call.info('Download of 1 artifact failed, retrying in 0:00:20.'),
                 mock.call.debug(f'writing 3 bytes to {path}/jid3/path3')],
                logger.mock_calls
            )

    def test_download_artifacts_retry_exceeds(self):
        buildkite = self.create_buildkite_mock(
            {'id1'}, {'id1': [self.http500] * 5}
        )
        artifacts = [
            {'id': 'id1', 'job_id': 'jid1', 'path': 'path1', 'state': 'finished'},
        ]
        job_names = {artifact['id']: f'file-{artifact["id"]}' for artifact in artifacts}

        with tempfile.TemporaryDirectory() as path, \
                mock.patch('download_artifacts.logger') as logger, \
                mock.patch('download_artifacts.time.sleep') as time:

            download_artifacts(buildkite, self.org, self.pipeline, self.build_number, artifacts, job_names, path)
            for file in os.listdir(path):
                print(file)

            self.assertEqual(
                [mock.call(5), mock.call(20), mock.call(80), mock.call(320)],
                time.mock_calls
            )

            self.assertEqual(
                [mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1')],
                buildkite.artifacts.return_value.download_artifact.mock_calls
            )

            self.assertEqual(
                [mock.call.info('Downloading 1 artifact from build 12345'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.info('Download of 1 artifact failed, retrying in 0:00:05.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.info('Download of 1 artifact failed, retrying in 0:00:20.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.info('Download of 1 artifact failed, retrying in 0:01:20.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                mock.call.info('Download of 1 artifact failed, retrying in 0:05:20.'),
                mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500)],
                logger.mock_calls
            )
