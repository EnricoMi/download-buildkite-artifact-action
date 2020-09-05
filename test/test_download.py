import unittest

from download_artifacts import *


class DownloadTest(unittest.TestCase):
    def test_make_path_safe(self):
        self.assertEqual('', make_path_safe(''))
        self.assertEqual('abc', make_path_safe('abc'))
        self.assertEqual('abc-123-DEF', make_path_safe('abc 123  DEF'))
        self.assertEqual('some-paths', make_path_safe('some/paths/..'))
        self.assertEqual('some-characters', make_path_safe('some ⚡⚠✔✗ characters'))

    def test_make_dict_path_safe(self):
        self.assertEqual(dict(), make_dict_path_safe(dict()))
        self.assertEqual(dict(id='name'), make_dict_path_safe(dict(id='name')))
        self.assertEqual(dict(id1='name1', id2='name2'), make_dict_path_safe(dict(id1='name1', id2='name2')))
        self.assertEqual(dict(id1='name', id2='name_2', id3='name3'), make_dict_path_safe(dict(id1='name', id2='name', id3='name3')))
        self.assertEqual(dict(id1='unsafe-name', id2='unsafe-name_2', id3='name3'), make_dict_path_safe(dict(id1='unsafe name', id2=' unsafe name', id3='name3')))
