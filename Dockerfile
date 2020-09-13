FROM python:3.6-alpine

LABEL repository="https://github.com/EnricoMi/download-buildkite-artifact-action"
LABEL homepage="https://github.com/EnricoMi/download-buildkite-artifact-action"
LABEL maintainer="Enrico Minack <github@Enrico.Minack.dev>"

LABEL com.github.actions.name="Download Buildkite Artifact"
LABEL com.github.actions.description="A GitHub Action to download artifacts from a Buildkite pipeline"
LABEL com.github.actions.icon="download-cloud"
LABEL com.github.actions.color="green"

RUN pip install -U --force pip pybuildkite PyGithub

COPY githubext /action/githubext
COPY download_artifacts.py /action/

ENTRYPOINT ["python", "/action/download_artifacts.py"]
