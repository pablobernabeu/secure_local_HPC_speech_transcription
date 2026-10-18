# shellcheck shell=bash
# =============================================================================
# hpc/common/arc_common.sh  -  helpers shared by the hpc/ job scripts
#
# Sourced, never executed. Every job script starts the same way:
#
#   REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
#   # shellcheck source=common/arc_common.sh
#   source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
#   arc_activate "$REPO_DIR" --cuda || exit 1    # --cuda for GPU jobs only
#   arc_require_gpu || exit 2                    # CPU jobs: arc_preflight || exit 2
#   arc_load_hf_token "$REPO_DIR" || exit 1      # jobs that need a token
#   ...
#   arc_record_env "$REPORT_DIR" NAME=value ...
#
# Sourcing only defines functions. It runs nothing, reads no variable and
# changes no shell option, so it cannot alter the behaviour of a job that
# sources it until one of the functions is called.
#
# The functions return non-zero on failure instead of exiting, so each
# script chooses and documents its own exit status. Note that bash ignores
# `set -e` inside a function called from an `||` list, which is why every
# step below checks its own status explicitly.
#
# What the helpers never do: install, upgrade, uninstall or repair a
# package. The jobs used to (a `pip install` whenever an import failed, and
# a force-reinstall of torch from the cu121 index whenever CUDA looked
# missing), which changed the shared environment that produces the results
# while sibling array tasks were importing from it (audit findings DEPS-03,
# SHELL-01, SHELL-06, SHELL-10). The environment is now fixed by
# requirements-lock.txt, and a job whose environment fails the preflight
# stops before any GPU time is spent.
# =============================================================================

# arc_activate <repo_dir> [--cuda] [--module <name>] ...
#
# Load the site modules, activate the project environment and move into the
# repository, the steps every job script used to carry its own copy of in
# three drifting variants.
#
# The module versions are pinned to what the unversioned `module load
# Anaconda3` and `module load CUDA` resolved to on ARC for every committed
# job (the highest installed versions: Anaconda3/2025.06-1, modulefile dated
# 2025-10-16, and CUDA/13.0.2, dated 2026-03-13), so pinning changes nothing
# for today's jobs and stops a new site default from changing tomorrow's.
# torch runs on the CUDA 12.1 runtime bundled in its cu121 wheels, not on
# the CUDA module; the module is loaded only so the GPU jobs' library path
# stays as it was when the committed results were produced.
# ARC_ANACONDA_MODULE and ARC_CUDA_MODULE override the pins (for another
# cluster); arc_record_env writes the modules actually loaded.
#
# Parameters:
#   repo_dir         the repository root (the scripts pass SLURM_SUBMIT_DIR)
#   --cuda           also load the CUDA module (GPU jobs)
#   --module <name>  also load this module, before the environment is
#                    activated so the environment's bin stays first on the
#                    PATH (the transcription worker loads FFmpeg this way)
#
# Side effects: `module purge` and `module load`; sources
# activate_project_env_arc.sh (which exports PROJECT_DIR, HF_HOME, PATH and
# the other variables it documents); changes directory to repo_dir; unsets
# TRANSFORMERS_CACHE, which is deprecated and would override HF_HOME.
#
# Returns 0 when the environment is active, 1 otherwise (missing argument,
# missing or failing activation script, unreadable repository).
arc_activate() {
    local repo_dir="${1:-}"
    if [[ -z "$repo_dir" ]]; then
        echo "arc_activate: no repository directory given" >&2
        return 1
    fi
    shift
    local want_cuda=0
    local extra_modules=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --cuda) want_cuda=1; shift ;;
            --module)
                if [[ -z "${2:-}" ]]; then
                    echo "arc_activate: --module needs a module name" >&2
                    return 1
                fi
                extra_modules+=("$2"); shift 2 ;;
            *) echo "arc_activate: unknown argument $1" >&2; return 1 ;;
        esac
    done

    if command -v module >/dev/null 2>&1; then
        module purge
        arc_load_module "${ARC_ANACONDA_MODULE:-Anaconda3/2025.06-1}"
        if (( want_cuda )); then
            arc_load_module "${ARC_CUDA_MODULE:-CUDA/13.0.2}"
        fi
        local extra
        # The ${a[@]+...} form keeps an empty array safe under `set -u` in
        # bash older than 4.4.
        for extra in ${extra_modules[@]+"${extra_modules[@]}"}; do
            arc_load_module "$extra"
        done
    else
        echo "arc_activate: no module command; using the Python on the PATH" >&2
    fi

    local activation="$repo_dir/activate_project_env_arc.sh"
    if [[ ! -f "$activation" ]]; then
        echo "Activation script not found at $activation" >&2
        echo "Submit the job from the repository root." >&2
        return 1
    fi
    # shellcheck source=/dev/null
    if ! source "$activation"; then
        echo "Activating the project environment failed ($activation)" >&2
        return 1
    fi
    if ! cd "$repo_dir"; then
        echo "Cannot change to the repository at $repo_dir" >&2
        return 1
    fi
    unset TRANSFORMERS_CACHE
    return 0
}

# arc_load_module <name/version>
#
# Load one module, and say so on stderr when it cannot be loaded instead of
# stopping: the preflight that follows is the gate on whether the job can
# run, and a cluster without this module name may still provide what it
# needs on the PATH.
#
# Side effects: `module load`. Returns 0 always.
arc_load_module() {
    if ! module load "$1" >/dev/null 2>&1; then
        echo "arc_load_module: could not load $1; continuing with the PATH as it is" >&2
    fi
    return 0
}

# arc_preflight [preflight options ...]
#
# Run `python -m preflight` with the given options and report a failure in
# the job's own terms.
#
# Parameters: passed to preflight unchanged (for example --gpu-required,
# --diarisation-required, --lock requirements-lock.txt).
#
# Side effects: prints the preflight report. Installs nothing.
#
# Returns preflight's status: 0 when usable, non-zero when any check FAILs.
arc_preflight() {
    echo "Preflight: python -m preflight $*"
    if python -m preflight "$@"; then
        return 0
    fi
    echo "Preflight failed: the job stops before doing any work." >&2
    echo "Jobs never install or repair packages. The environment behind the" >&2
    echo "results is pinned in requirements-lock.txt; fix it from a login node" >&2
    echo "(the report above names each remedy) and resubmit." >&2
    return 1
}

# arc_require_gpu [preflight options ...]
#
# The GPU gate: print the GPU Slurm allocated, then run the preflight with
# --gpu-required, so that a node or environment without a usable CUDA
# device aborts in seconds and never falls back to the CPU inside a GPU
# allocation (audit finding SHELL-05).
#
# Parameters: further preflight options, such as --diarisation-required
# for the jobs whose point is speaker attribution.
#
# Side effects: runs nvidia-smi and the preflight, both read-only.
#
# Returns 0 when the preflight passes, non-zero otherwise.
arc_require_gpu() {
    echo "GPU: CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-(not set by Slurm)}"
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 || true
    else
        echo "(nvidia-smi not found on this node)"
    fi
    arc_preflight --gpu-required "$@"
}

# arc_load_hf_token <repo_dir>
#
# Export the HuggingFace token the gated pyannote models and the AMI
# download need. hf_token.txt in the repository root wins over an HF_TOKEN
# already in the environment, as in every script this replaces; whitespace
# (a trailing newline, a Windows line ending) is stripped from the file.
#
# Parameters:
#   repo_dir   the repository root holding hf_token.txt
#
# Side effects: exports HF_TOKEN. Prints where the token came from, never
# the token itself.
#
# Returns 0 when a non-empty token is exported, 1 otherwise.
arc_load_hf_token() {
    local token_file="${1:-.}/hf_token.txt"
    local token=""
    if [[ -f "$token_file" ]]; then
        # Assigned apart from `export`: `export VAR="$(...)"` returns
        # export's status and hides a failed read (the old finetune copy).
        if ! token="$(tr -d '[:space:]' < "$token_file")"; then
            echo "Cannot read $token_file" >&2
            return 1
        fi
    fi
    if [[ -n "$token" ]]; then
        HF_TOKEN="$token"
        export HF_TOKEN
        echo "HuggingFace token: from $token_file"
        return 0
    fi
    if [[ -n "${HF_TOKEN:-}" ]]; then
        export HF_TOKEN
        echo "HuggingFace token: from the HF_TOKEN environment variable"
        return 0
    fi
    echo "No HuggingFace token: set HF_TOKEN or create $token_file." >&2
    echo "The gated pyannote models and the AMI download need one." >&2
    return 1
}

# arc_record_env <dest_dir> [NAME=value ...]
#
# Write a plain-text record of the software and hardware a job ran on, so that
# every result directory carries its own environment rather than relying on
# the environment still being the same when someone looks later. The shared
# ARC environment has been modified in place during the project, so the
# environment at result time cannot be reconstructed afterwards.
#
# Parameters:
#   dest_dir      directory the job writes its results to; the record goes in
#                 its environment/ subdirectory
#   NAME=value    effective job parameters to record alongside (optional)
#
# Side effects: creates <dest_dir>/environment/ and writes one file there,
# named <job name>_<job id>[_<array task>].txt. Runs `python`, `pip list`,
# `git`, `module list` and `nvidia-smi` read-only; nothing is installed.
# `git status` runs with --no-optional-locks (git >= 2.15), because a plain
# `git status` refreshes and rewrites .git/index under index.lock when file
# stat data is stale, which from array tasks starting together in one clone
# can make the author's own `git pull` or `git commit` fail on the lock.
#
# Returns 0 whatever happens. A failure to record must never fail or alter the
# job, so every probe is allowed to fail and the error text is kept in the
# record instead. All variables are read with defaults so the function is safe
# under `set -u`.
arc_record_env() {
    local dest_dir="${1:-}"
    if [[ -z "$dest_dir" ]]; then
        echo "arc_record_env: no destination directory given; nothing recorded" >&2
        return 0
    fi
    shift

    local job_name="${SLURM_JOB_NAME:-local}"
    local tag="${SLURM_JOB_ID:-nojob}"
    if [[ -n "${SLURM_ARRAY_TASK_ID:-}" ]]; then
        tag="${SLURM_ARRAY_JOB_ID:-$tag}_${SLURM_ARRAY_TASK_ID}"
    fi
    local record_dir="$dest_dir/environment"
    local record="$record_dir/${job_name}_${tag}.txt"

    if ! mkdir -p "$record_dir" 2>/dev/null; then
        echo "arc_record_env: cannot create $record_dir; nothing recorded" >&2
        return 0
    fi

    {
        echo "# Environment record written by hpc/common/arc_common.sh"
        echo "date:            $(date '+%Y-%m-%dT%H:%M:%S%z')"
        echo "host:            $(hostname 2>/dev/null || echo unknown)"
        echo "slurm_job_id:    ${SLURM_JOB_ID:-}"
        echo "slurm_array:     ${SLURM_ARRAY_JOB_ID:-}${SLURM_ARRAY_TASK_ID:+_${SLURM_ARRAY_TASK_ID}}"
        echo "slurm_job_name:  ${SLURM_JOB_NAME:-}"
        echo "slurm_cluster:   ${SLURM_CLUSTER_NAME:-}"
        echo "slurm_partition: ${SLURM_JOB_PARTITION:-}"
        echo "slurm_account:   ${SLURM_JOB_ACCOUNT:-}"
        echo "working_dir:     $(pwd)"
        echo "git_commit:      $(git rev-parse HEAD 2>/dev/null || echo unknown)"
        # Modified tracked files mean the commit alone does not identify the
        # code that ran, so they are counted and the first 20 listed.
        # Untracked files (logs, outputs) are not counted, and neither are
        # tracked results and documents under output/, example_output/ and
        # manuscript/: a re-run that rewrites a tracked result says nothing
        # about the code (audit finding SHELL-R4). A failed probe is
        # recorded as unknown, not as 0.
        local git_changes
        if git_changes="$(git --no-optional-locks status --porcelain \
                --untracked-files=no -- ':(top)' ':(top,exclude)output' \
                ':(top,exclude)example_output' ':(top,exclude)manuscript' 2>&1)"; then
            echo "git_modified_tracked_files: $(printf '%s' "$git_changes" | grep -c .)"
            if [[ -n "$git_changes" ]]; then
                printf '%s\n' "$git_changes" | head -n 20 | sed 's/^/    /'
            fi
        else
            echo "git_modified_tracked_files: unknown ($(printf '%s' "$git_changes" | head -n 1))"
        fi

        echo ""
        echo "## Effective parameters"
        local kv
        for kv in "$@"; do
            echo "$kv"
        done

        echo ""
        echo "## Loaded modules"
        if command -v module >/dev/null 2>&1 || declare -F module >/dev/null 2>&1; then
            module list 2>&1
        else
            echo "(module command not available)"
        fi

        echo ""
        echo "## GPU"
        if command -v nvidia-smi >/dev/null 2>&1; then
            nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1
            nvidia-smi 2>&1 | head -n 4
        else
            echo "(nvidia-smi not available)"
        fi

        echo ""
        echo "## Python stack as the job imports it"
        # Versions *and* file locations: a package imported from a user site
        # rather than from the environment has the right name and the wrong
        # build, and only its path shows that.
        python - <<'PY' 2>&1
import importlib, site, sys
print("python:", sys.version.replace("\n", " "))
print("executable:", sys.executable)
print("prefix:", sys.prefix)
print("user_site_enabled:", site.ENABLE_USER_SITE)
print("user_site:", site.getusersitepackages())
for name in ("torch", "torchaudio", "transformers", "pyannote.audio",
             "jiwer", "datasets", "numpy"):
    try:
        mod = importlib.import_module(name)
    except Exception as exc:  # record, never fail
        print(f"{name}: not importable ({type(exc).__name__}: {exc})")
        continue
    print(f"{name}: {getattr(mod, '__version__', '?')}  {getattr(mod, '__file__', '?')}")
try:
    import torch
    print("torch.version.cuda:", torch.version.cuda)
    print("cuda_available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("cuda_device:", torch.cuda.get_device_name(0))
    print("cudnn:", torch.backends.cudnn.version())
except Exception as exc:
    print("torch probe failed:", exc)
PY

        echo ""
        echo "## pip list --format=freeze"
        python -m pip list --format=freeze --disable-pip-version-check 2>&1
    } > "$record" 2>&1 || true

    echo "Environment recorded in $record"
    return 0
}
