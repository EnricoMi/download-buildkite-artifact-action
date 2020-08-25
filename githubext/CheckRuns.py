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

import github.GithubObject
from github.Commit import Commit


class CheckRuns(github.GithubObject.CompletableGithubObject):
    """
    This class represents check runs of a Commit. The reference can be found here http://developer.github.com/v3/checks/runs/
    """

    @property
    def total_count(self):
        """
        :type: integer
        """
        self._completeIfNotSet(self._total_count)
        return self._total_count.value

    @property
    def check_runs(self):
        """
        :type: list of :class:`CheckRun`
        """
        self._completeIfNotSet(self._check_runs)
        return self._check_runs.value

    @property
    def url(self):
        """
        :type: string
        """
        self._completeIfNotSet(self._url)
        return self._url.value

    def _initAttributes(self):
        self._total_count = github.GithubObject.NotSet
        self._check_runs = github.GithubObject.NotSet
        self._url = github.GithubObject.NotSet

    def _useAttributes(self, attributes):
        if "total_count" in attributes:  # pragma no branch
            self._total_count = self._makeIntAttribute(attributes["total_count"])
        if "check_runs" in attributes:  # pragma no branch
            self._check_runs = self._makeListOfClassesAttribute(
                CheckRun, attributes["check_runs"]
            )
        if "url" in attributes:  # pragma no branch
            self._url = self._makeStringAttribute(attributes["url"])


class CheckRun(github.GithubObject.CompletableGithubObject):
    """
    This class represents a check run of a Commit. The reference can be found here http://developer.github.com/v3/checks/runs/
    """

    def __repr__(self):
        return self.get__repr__({"id": self._id.value})

    @property
    def id(self):
        """
        :type: integer
        """
        self._completeIfNotSet(self._id)
        return self._id.value

    @property
    def name(self):
        """
        :type: string
        """
        self._completeIfNotSet(self._name)
        return self._name.value

    @property
    def status(self):
        """
        :type: string
        """
        self._completeIfNotSet(self._status)
        return self._status.value

    @property
    def conclusion(self):
        """
        :type: string
        """
        self._completeIfNotSet(self._conclusion)
        return self._conclusion.value

    @property
    def details_url(self):
        """
        :type: string
        """
        self._completeIfNotSet(self._details_url)
        return self._details_url.value

    @property
    def url(self):
        """
        :type: string
        """
        self._completeIfNotSet(self._url)
        return self._url.value

    def _initAttributes(self):
        self._id = github.GithubObject.NotSet
        self._name = github.GithubObject.NotSet
        self._status = github.GithubObject.NotSet
        self._conclusion = github.GithubObject.NotSet
        self._details_url = github.GithubObject.NotSet
        self._url = github.GithubObject.NotSet

    def _useAttributes(self, attributes):
        if "id" in attributes:  # pragma no branch
            self._id = self._makeIntAttribute(attributes["id"])
        if "name" in attributes:  # pragma no branch
            self._name = self._makeStringAttribute(attributes["name"])
        if "status" in attributes:  # pragma no branch
            self._status = self._makeStringAttribute(attributes["status"])
        if "conclusion" in attributes:  # pragma no branch
            self._conclusion = self._makeStringAttribute(attributes["conclusion"])
        if "details_url" in attributes:  # pragma no branch
            self._details_url = self._makeStringAttribute(attributes["details_url"])
        if "url" in attributes:  # pragma no branch
            self._url = self._makeStringAttribute(attributes["url"])


def get_check_runs(self: Commit):
    headers, data = self._requester.requestJsonAndCheck(
        'GET', self.url + '/check-runs', headers={'Accept': 'application/vnd.github.antiope-preview+json'}
    )
    print(data)
    return CheckRuns(self._requester, headers, data, completed=True)


Commit.get_check_runs = get_check_runs
