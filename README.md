# GitHub Action to download Buildkite Artifacts

This [GitHub Action](https://github.com/actions) downloads artifacts from
a [Buildkite](https://buildkite.com/) pipeline that builds the respective commit.

The action picks up a Buildkite build from the commit status that is set by
[Buildkite integration with Github](https://buildkite.com/docs/integrations/github#connecting-buildkite-and-github),
which looks like this:

![Github commit status set by Buildkite](github-buildkite-check.png)

After termination of the Buildkite build, the action downloads finished artifacts into your GitHub workflow
where you can use them by other steps.

You can add this action to your GitHub workflow and configure it as follows:

```yaml
- name: Buildkite Artifacts
  uses: EnricoMi/download-buildkite-artifact-action@v1.6
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    buildkite_token: ${{ secrets.BUILDKITE_TOKEN }}
    output_path: artifacts
    log_level: DEBUG
```

## Using pre-build Docker images

You can use a pre-built docker image from [GitHub Container Registry](https://docs.github.com/en/free-pro-team@latest/packages/getting-started-with-github-container-registry/about-github-container-registry) (Beta).
This way, the action is not build for every run of your workflow, and you are guaranteed to get the exact same action build:
```yaml
  uses: docker://ghcr.io/enricomi/download-buildkite-artifact-action:v1.6
```

**Note:** GitHub Container Registry is currently in [beta phase](https://docs.github.com/en/free-pro-team@latest/packages/getting-started-with-github-container-registry/about-github-container-registry).
This action may abandon GitHub Container Registry support when GitHub changes its conditions.

## Configuration
The `output_path` and `log_level` variables are optional. Their default values are `.` (current directory) and `INFO`, respectively. The Python logging module defines the [available log levels](https://docs.python.org/3/library/logging.html#logging-levels).

You have to provide a [Buildkite API Access Token](https://buildkite.com/docs/apis/managing-api-tokens) via `buildkite_token` to be stored in your [GitHub secrets](https://docs.github.com/en/actions/configuring-and-managing-workflows/creating-and-storing-encrypted-secrets).
This Buildkite token requires `read_artifacts` and `read_builds` scopes:

![Buildkite token scopes](buildkite-token-scopes.png)

Artifacts are stored under the following path: `{output_path}/{job_name}/{artifact_path}`

- The `output_path` is a configured above or defaults to the current directory.
- The `job_name` avoids conflicts between artifacts that have the same `artifact_path` in different jobs.
- The `artifact_path` is the path and filename for the artifact as displayed on the Buildkite build page:

![Buildkite artifacts](buildkite-artifact.png)


The action provides the following outputs:

|output        |description                      |
|--------------|---------------------------------|
|`build-number`|The number of the Buildkite build|
|`build-state`|The state of the Buildkite build  |
|`download-state`|The outcome of downloading artifacts: `skipped`, `success`, `failure`|
|`download-paths`|The paths of the downloaded artifacts as a Json array of strings|
|`download-files`|The number of downloaded files|
