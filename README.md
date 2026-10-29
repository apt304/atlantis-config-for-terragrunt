# Atlantis Config For Terragrunt

This script generates an `atlantis.yaml` file for [Atlantis](https://runatlantis.io). This script reads the JSON output of `terragrunt find` and prints the appropriate Atlantis config for the repository.

## How it works

1. The script reads the JSON output of `terragrunt find --json --dependencies --include --reading`.
2. It keeps only Terragrunt units, dropping stacks and anything under `terragrunt-units/`.
3. It calculates an `execution_order_group` for each unit, so Atlantis applies each unit after its dependencies.
4. It builds the `when_modified` patterns for each unit. Atlantis plans a unit when one of these files changes.
5. It prints the config as JSON. JSON is a valid subset of YAML, so the output works as `atlantis.yaml`.

The script has no Python dependencies and runs with uv via its `uv run --script` shebang.

## Usage

1. Run `terragrunt find` and pipe the output to the script.

   ```sh
   terragrunt find --json --dependencies --include --reading | ./atlantis-config-for-terragrunt.py > atlantis.yaml
   ```

2. Commit the resulting `atlantis.yaml` to the infrastructure repository.

The script also accepts a JSON file as the first argument:

```sh
./atlantis-config-for-terragrunt.py terragrunt-find-output.json > atlantis.yaml
```


## Vendoring

Vendor this script into your infrastructure setup. There are two options.

### Option 1: Build it into the Atlantis image

1. Add an `ADD` step to the user's Atlantis Dockerfile. It can pull the script from this repository directly.

   ```dockerfile
   FROM runatlantis/atlantis:v0.48.0
   COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
   ADD --chmod=0755 https://raw.githubusercontent.com/apt304/atlantis-config-for-terragrunt/main/atlantis-config-for-terragrunt.py /atlantis-config-for-terragrunt.py
   ```

2. Build the image.
3. Run the script inside the container to regenerate `atlantis.yaml` when the repository layout changes.

### Option 2: Pull it in during `initConfig` with uv

The [Atlantis Helm chart](https://github.com/runatlantis/helm-charts/blob/main/charts/atlantis/values.yaml) supports an `initConfig` init container. It runs a script before the Atlantis pod starts. The script writes files to a shared directory (the `INIT_SHARED_DIR` variable, `/plugins` by default). The chart adds that directory to the `PATH` of the Atlantis pod. This script installs a pinned version of [Terragrunt](https://github.com/gruntwork-io/terragrunt) and [uv](https://docs.astral.sh/uv/) into that directory, along with the config script. No custom container needed.

```yaml
initConfig:
  enabled: true
  script: |
    #!/bin/sh
    set -eux

    # terragrunt
    TG_VERSION="1.2.1"
    TG_SHA256SUM="f2f6238ad2348855a4e876b90fd31f3f5d106bb234794202a00b2bcc139fa753"
    TG_FILE="$INIT_SHARED_DIR/terragrunt"
    wget "https://github.com/gruntwork-io/terragrunt/releases/download/v$TG_VERSION/terragrunt_linux_amd64" -O "$TG_FILE"
    echo "$TG_SHA256SUM  $TG_FILE" | sha256sum -c
    chmod 755 "$TG_FILE"
    "$TG_FILE" -v

    # uv
    UV_VERSION="0.13.6"
    UV_SHA256SUM="5d61f26b6c7213779eda90edc6971ea6b0b796bfb8d49a574c8ad69b59838548"
    UV_TARBALL="uv-x86_64-unknown-linux-musl.tar.gz"
    wget "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$UV_TARBALL" -O /tmp/$UV_TARBALL
    echo "$UV_SHA256SUM  /tmp/$UV_TARBALL" | sha256sum -c
    tar xf /tmp/$UV_TARBALL -C /tmp
    install /tmp/uv-*/uv "$INIT_SHARED_DIR"
    install /tmp/uv-*/uvx "$INIT_SHARED_DIR"
    "$INIT_SHARED_DIR/uv" --version

    # config script
    wget "https://raw.githubusercontent.com/apt304/atlantis-config-for-terragrunt/main/atlantis-config-for-terragrunt.py" -O "$INIT_SHARED_DIR/atlantis-config-for-terragrunt.py"
    chmod 755 "$INIT_SHARED_DIR/atlantis-config-for-terragrunt.py"
```

The `pre_workflow_hooks` step runs the script:

```sh
terragrunt find --json --dependencies --include --reading | /plugins/atlantis-config-for-terragrunt.py > atlantis.yaml
```

If the Atlantis container has no Python, uv downloads one on first use.

## Example values.yaml

A complete example lives in [`example-atlantis-chart-values.yaml`](./example-atlantis-chart-values.yaml). It installs Terragrunt, uv, and the config script in `initConfig`, and regenerates `atlantis.yaml` on every Atlantis workflow run. It also defines a Terragrunt workflow for plan and apply.

## Prior art

[terragrunt-atlantis-config](https://github.com/transcend-io/terragrunt-atlantis-config) also generates `atlantis.yaml` for a Terragrunt repository. It uses Terragrunt as a library to discover units and dependencies. It hasn't seen updates in a long time, so it misses new Terragrunt features. It's also slow, which adds time to every CI run. This script uses the output of `terragrunt find` as the source of truth for units, stacks, and dependencies.
