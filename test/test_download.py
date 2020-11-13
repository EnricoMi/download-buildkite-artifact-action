import tempfile
import unittest
from glob import glob
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
        return HTTPError(f'Exception {code} {message}', response=response)

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
        downloader = Downloader()
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

            downloaded_paths, failed_ids = downloader.download_artifacts(
                buildkite, self.org, self.pipeline, self.build_number, artifacts, job_names, path
            )

            self.assertEqual(
                [mock.call.info('Downloading 4 artifacts from build 12345.'),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid2/path2.'),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid4/path4.'),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid5/path5.'),
                 mock.call.debug(f'Downloading artifact id6 to {path}/jid6/path6 failed.', exc_info=self.http404),
                 mock.call.info('Downloaded 3 artifacts and 9 Bytes, 1 artifact failed.')],
                logger.mock_calls
            )

            self.assertEqual(
                [mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid4', 'id4'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid5', 'id5'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid6', 'id6')],
                buildkite.artifacts.return_value.download_artifact.mock_calls
            )

            self.assertEqual(
                ['/',
                 '/jid2', '/jid2/path2',
                 '/jid4', '/jid4/path4',
                 '/jid5', '/jid5/path5',
                 '/jid6'],
                sorted([file[file.startswith(path) and len(path):]
                        for file in glob(os.path.join(path, '**'), recursive=True)])
            )

            self.assertEqual([], time.mock_calls)
            self.assertEqual(['/jid2/path2', '/jid4/path4', '/jid5/path5'],
                             [downloaded_path[downloaded_path.startswith(path) and len(path):]
                              for downloaded_path in downloaded_paths])
            self.assertEqual({'id6'}, failed_ids)

    def test_download_artifacts_retry(self):
        buildkite = self.create_buildkite_mock(
            {'id1', 'id2', 'id3', 'id4', 'id5'},
            {
                'id2': [self.http500],
                'id3': [self.http500, self.http500],
                'id4': [self.http404],
                'id5': [self.http404]
            }
        )
        artifacts = [
            # this succeeds first try
            {'id': 'id1', 'job_id': 'jid1', 'path': 'path1', 'state': 'finished'},
            # this fails once, succeeds second try
            {'id': 'id2', 'job_id': 'jid2', 'path': 'path2', 'state': 'finished'},
            # this fails twice, succeeds third try
            {'id': 'id3', 'job_id': 'jid3', 'path': 'path3', 'state': 'finished'},
            # this fails once with 404, but it is in new state so gets retried as well
            {'id': 'id4', 'job_id': 'jid4', 'path': 'path4', 'state': 'new'},
            # this fails once with 404, but it is in finished state so it is not retried
            {'id': 'id5', 'job_id': 'jid5', 'path': 'path5', 'state': 'finished'},
        ]
        job_names = {artifact['id']: f'file-{artifact["id"]}' for artifact in artifacts}

        downloader = Downloader()
        with tempfile.TemporaryDirectory() as path, \
                mock.patch('download_artifacts.logger') as logger, \
                mock.patch('download_artifacts.time.sleep') as time:

            downloaded_paths, failed_ids = downloader.download_artifacts(
                buildkite, self.org, self.pipeline, self.build_number, artifacts, job_names, path
            )

            self.assertEqual(
                [mock.call.info('Downloading 5 artifacts from build 12345.'),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid1/path1.'),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id3 to {path}/jid3/path3 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id4 to {path}/jid4/path4 failed.', exc_info=self.http404),
                 mock.call.debug(f'Downloading artifact id5 to {path}/jid5/path5 failed.', exc_info=self.http404),
                 mock.call.info('Download of 3 artifacts failed, retrying in 5 seconds.'),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid2/path2.'),
                 mock.call.debug(f'Downloading artifact id3 to {path}/jid3/path3 failed.', exc_info=self.http500),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid4/path4.'),
                 mock.call.info('Download of 1 artifact failed, retrying in 20 seconds.'),
                 mock.call.debug(f'Writing 3 bytes to {path}/jid3/path3.'),
                 mock.call.info('Downloaded 4 artifacts and 12 Bytes, 1 artifact failed.')],
                logger.mock_calls
            )

            self.assertEqual(
                [mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid3', 'id3'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid4', 'id4'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid5', 'id5'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid3', 'id3'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid4', 'id4'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid3', 'id3')],
                buildkite.artifacts.return_value.download_artifact.mock_calls
            )

            self.assertEqual(
                ['/',
                 '/jid1', '/jid1/path1',
                 '/jid2', '/jid2/path2',
                 '/jid3', '/jid3/path3',
                 '/jid4', '/jid4/path4',
                 '/jid5'],
                sorted([file[file.startswith(path) and len(path):]
                        for file in glob(os.path.join(path, '**'), recursive=True)])
            )

            self.assertEqual([mock.call(5), mock.call(20)], time.mock_calls)
            self.assertEqual(['/jid1/path1', '/jid2/path2', '/jid4/path4', '/jid3/path3'],
                             [downloaded_path[downloaded_path.startswith(path) and len(path):]
                              for downloaded_path in downloaded_paths])
            self.assertEqual({'id5'}, failed_ids)

    def test_download_artifacts_retry_exceeds(self):
        buildkite = self.create_buildkite_mock(
            {'id1', 'id2'}, {'id1': [self.http500] * 5, 'id2': [self.http404] * 5}
        )
        downloader = Downloader()
        artifacts = [
            {'id': 'id1', 'job_id': 'jid1', 'path': 'path1', 'state': 'finished'},
            {'id': 'id2', 'job_id': 'jid2', 'path': 'path2', 'state': 'new'},
        ]
        job_names = {artifact['id']: f'file-{artifact["id"]}' for artifact in artifacts}

        with tempfile.TemporaryDirectory() as path, \
                mock.patch('download_artifacts.logger') as logger, \
                mock.patch('download_artifacts.time.sleep') as time:

            downloaded_paths, failed_ids = downloader.download_artifacts(buildkite, self.org, self.pipeline, self.build_number, artifacts, job_names, path)

            self.assertEqual(
                [mock.call.info('Downloading 2 artifacts from build 12345.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http404),
                 mock.call.info('Download of 2 artifacts failed, retrying in 5 seconds.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http404),
                 mock.call.info('Download of 2 artifacts failed, retrying in 20 seconds.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http404),
                 mock.call.info('Download of 2 artifacts failed, retrying in a minute.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http404),
                 mock.call.info('Download of 2 artifacts failed, retrying in 5 minutes.'),
                 mock.call.debug(f'Downloading artifact id1 to {path}/jid1/path1 failed.', exc_info=self.http500),
                 mock.call.debug(f'Downloading artifact id2 to {path}/jid2/path2 failed.', exc_info=self.http404),
                 mock.call.warning('Download of 2 artifacts failed, giving up.'),
                 mock.call.debug('Failed artifacts:'),
                 mock.call.debug({'id': 'id1', 'job_id': 'jid1', 'path': 'path1', 'state': 'finished'}),
                 mock.call.debug({'id': 'id2', 'job_id': 'jid2', 'path': 'path2', 'state': 'new'}),
                 mock.call.info('Downloaded 0 artifacts and 0 Bytes, 2 artifacts failed.')],
                logger.mock_calls
            )

            self.assertEqual(
                [mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid1', 'id1'),
                 mock.call(self.org, self.pipeline, self.build_number, 'jid2', 'id2')],
                buildkite.artifacts.return_value.download_artifact.mock_calls
            )

            self.assertEqual(
                ['/', '/jid1', '/jid2'],
                [file[file.startswith(path) and len(path):]
                 for file in glob(os.path.join(path, '**'), recursive=True)]
            )

            self.assertEqual([mock.call(5), mock.call(20), mock.call(80), mock.call(320)], time.mock_calls)
            self.assertEqual([], downloaded_paths)
            self.assertEqual({'id1', 'id2'}, failed_ids)
