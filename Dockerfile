FROM python:3.8-slim

LABEL repository="https://github.com/EnricoMi/download-buildkite-artifact-action"
LABEL homepage="https://github.com/EnricoMi/download-buildkite-artifact-action"
LABEL maintainer="Enrico Minack <github@Enrico.Minack.dev>"

LABEL com.github.actions.name="Download Buildkite Artifact"
LABEL com.github.actions.description="A GitHub Action to download artifacts from a Buildkite pipeline"
LABEL com.github.actions.icon="download-cloud"
LABEL com.github.actions.color="green"

COPY requirements.txt /action/
RUN pip install --upgrade --force --no-cache-dir pip && pip install --upgrade --force --no-cache-dir -r /action/requirements.txt

COPY download_artifacts.py github_action.py /action/

ENTRYPOINT ["python", "/action/download_artifacts.py"]
