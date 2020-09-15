FROM python:3.6-slim

LABEL repository="https://github.com/EnricoMi/download-buildkite-artifact-action"
LABEL homepage="https://github.com/EnricoMi/download-buildkite-artifact-action"
LABEL maintainer="Enrico Minack <github@Enrico.Minack.dev>"

LABEL com.github.actions.name="Download Buildkite Artifact"
LABEL com.github.actions.description="A GitHub Action to download artifacts from a Buildkite pipeline"
LABEL com.github.actions.icon="download-cloud"
LABEL com.github.actions.color="green"

RUN apk add --no-cache git

COPY requirements.txt /action/
RUN pip install --upgrade --force --no-cache-dir pip && pip install --upgrade --force --no-cache-dir -r /action/requirements.txt

COPY githubext /action/githubext
COPY download_artifacts.py /action/

ENTRYPOINT ["python", "/action/download_artifacts.py"]
