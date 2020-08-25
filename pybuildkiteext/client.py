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

from pybuildkite.client import Client
import requests


def request(
        self,
        method,
        url,
        query_params=None,
        body=None,
        headers={},
        with_pagination=False,
):
    """
    Make a request to the API

    The request will be authorised if the access token is set

    :param method: HTTP method to use
    :param url: URL to call
    :param query_params: Query parameters to use
    :param body: Body of the request
    :param headers: Dictionary of headers to use in HTTP request
    :param with_pagination: Bool to return a response with pagination attributes
    :return: If headers are set response text is returned, otherwise parsed response is returned
    """
    if headers is None:
        raise ValueError("headers cannot be None")

    if self.access_token:
        headers["Authorization"] = "Bearer {}".format(self.access_token)

    if body:
        body = self._clean_query_params(body)

    query_params = self._clean_query_params(query_params or {})
    query_params["per_page"] = "100"

    query_params = self._convert_query_params_to_string_for_bytes(query_params)
    response = requests.request(
        method, url, headers=headers, params=str.encode(query_params), json=body
    )

    response.raise_for_status()

    if with_pagination:
        response = self._get_paginated_response(response)
        return response
    if (
            method == "DELETE"
            or response.status_code == 204
            or response.headers.get("content-type") is None
    ):
        return response.ok
    if headers.get("Accept") is None or headers.get("Accept") == "application/json":
        return response.json()
    else:
        return response.content


Client.request = request
