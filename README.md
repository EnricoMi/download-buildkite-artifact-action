# GitHub Action to download Buildkite Artifacts

![Ubuntu Linux](https://badgen.net/badge/icon/Ubuntu?icon=terminal&label)
![macOS](https://badgen.net/badge/icon/macOS?icon=apple&label)
![Windows](https://badgen.net/badge/icon/Windows?icon=windows&label)

This [GitHub Action](https://github.com/actions) downloads artifacts from
a [Buildkite](https://buildkite.com/) pipeline that builds the respective commit.

The action picks up a Buildkite build from the commit status that is set by
[Buildkite integration with Github](https://buildkite.com/docs/integrations/github#connecting-buildkite-and-github),
which looks like this:

![Github commit status set by Buildkite](github-buildkite-check.png)

After termination of the Buildkite build, the action downloads finished artifacts into your GitHub workflow
where you can use them in other steps and jobs.

You can add this action to your GitHub workflow for ![Ubuntu Linux](https://badgen.net/badge/icon/Ubuntu?icon=terminal&label) (e.g. `runs-on: ubuntu-latest`) runners:

```yaml
- name: Buildkite Artifacts
  uses: EnricoMi/download-buildkite-artifact-action@v1
  with:
    buildkite_token: ${{ secrets.BUILDKITE_TOKEN }}
    output_path: artifacts
```

Use this for ![macOS](https://badgen.net/badge/icon/macOS?icon=apple&label) (e.g. `runs-on: macos-latest`)
and ![Windows](https://badgen.net/badge/icon/Windows?icon=windows&label) (e.g. `runs-on: windows-latest`) runners:

```yaml
- name: Buildkite Artifacts
  uses: EnricoMi/download-buildkite-artifact-action/composite@v1
  with:
    buildkite_token: ${{ secrets.BUILDKITE_TOKEN }}
    output_path: artifacts
```

### Trigger a build and download its artifacts
You can trigger a Buildkite build with the [buildkite/trigger-pipeline-action](https://github.com/buildkite/trigger-pipeline-action) action
and then download the artifacts from that build:

```yaml
steps:
- name: Trigger Buildkite Pipeline
  id: build
  uses: buildkite/trigger-pipeline-action@v1.3.1
  env:
    PIPELINE: "<org-slug>/<pipeline-slug>"
    BUILDKITE_API_ACCESS_TOKEN: ${{ secrets.BUILDKITE_TOKEN }}

- name: Download Buildkite Artifacts
  uses: EnricoMi/download-buildkite-artifact-action@v1
  with:
    buildkite_token: ${{ secrets.BUILDKITE_TOKEN }}
    buildkite_build_url: ${{ steps.build.outputs.url }}
    ignore_build_states: blocked,canceled,skipped,not_run
    ignore_job_states: timed_out,failed
    output_path: artifacts
```

## Permissions
It is generally good practice to [restrict permissions for actions in your workflows and jobs](https://docs.github.com/en/actions/using-jobs/assigning-permissions-to-jobs) to the required minimum.

When `buildkite_build_url` is provided, no permissions are needed by this action at all:
```yaml
permissions: {}
```

When `buildkite_build_url` is **not** provided, the action picks up any Buildkite check created by
[Buildkite integration with Github](https://buildkite.com/docs/integrations/github#connecting-buildkite-and-github).
Then, the following permissions are required:
```yaml
permissions:
  metadata: read
  contents: read
  statuses: read
```


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

## Outputs
The action provides the following outputs:

|output        |description                      |
|--------------|---------------------------------|
|`build-number`|The number of the Buildkite build|
|`build-state`|The state of the Buildkite build: `passed`, `failed`, `blocked`, `canceled`, `skipped`, `not_run` |
|`download-state`|The outcome of downloading artifacts: `skipped`, `success`, `failure`|
|`download-paths`|The paths of the downloaded artifacts as a Json array of strings|
|`download-files`|The number of downloaded files|
