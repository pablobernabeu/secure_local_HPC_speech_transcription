# Speaker diarisation setup

Speaker diarisation, which this workflow calls speaker attribution, is
the step that decides who spoke when in a recording. It uses the
pyannote.audio pipeline `pyannote/speaker-diarization-3.1`. Model names
keep pyannote's American spelling, and the documentation uses the British
"diarisation". The terms are defined in [docs/glossary.md](docs/glossary.md).

## Privacy and where the model comes from

The privacy guarantee of this project is that audio recordings and
transcriptions stay within the workflow. They never leave the institution
under which the recording was made, are never transmitted to a remote
service, and are never used to train any model or shared in any other
way.

Downloading model weights is a separate matter. It is an outbound-only
operation that carries no user data, so it is not subject to that
constraint and needs no flag of its own. With `--speaker-attribution`,
`transcription.py` loads the diarisation pipeline in this order:

1. `--diarization-config PATH` (or `--diarisation-config`): a local pyannote
   YAML configuration that refers to segmentation and embedding
   checkpoints on disk, for fully air-gapped operation.
2. `--diarization-model-path PATH` (or `--diarisation-model-path`): a local
   pipeline, given either as its `config.yaml` or as a directory holding
   one, such as a downloaded snapshot.
3. The HuggingFace loader for `pyannote/speaker-diarization-3.1`, which
   uses the local cache and downloads from the Hub only when the weights
   are absent. That needs a HuggingFace token whose account has accepted
   the model's terms. With `HF_HUB_OFFLINE=1` or `TRANSFORMERS_OFFLINE=1`
   set, it reads the cache only and never downloads.

If you name a local pipeline with the first or second option and it
cannot be loaded, the Hub model is not tried in its place, because that
would diarise with a model you did not choose. The transcript is written
without speaker labels and the run reports itself incomplete. The desktop
application's "Diarisation model path" field passes its value as
`--diarization-model-path`.

A run with speaker attribution also writes the timestamped JSON, and
records the route taken in its `pipeline` block: `diarization_model_source` (`local_config`,
`local_path`, `hf_loader`, `hf_loader_offline` or `unavailable`),
`diarization_model_id`, `diarization_model_path`,
`diarization_offline_mode`, and `diarization_error` when loading failed.
The same labels are listed in [docs/glossary.md](docs/glossary.md).
The block also names the snapshots that were loaded.
`diarization_model_revision` is the Hub commit of the pipeline, and
`diarization_sub_model_revisions` gives the commit of each segmentation
and embedding model the pipeline names, since the pipeline holds no
weights of its own. They are read back from pyannote's cache (see
"Download the models" below) after loading, and the load is not pinned
to them, so a machine whose cache holds another snapshot still runs and
records which one it used. A value is `null` where the cache cannot say,
and the pipeline's is `null` for a local pipeline. The run manifest
holds the same values under `diarization_settings`.

HPC compute nodes generally have no outbound network access, so the
weights must be in the cache before a job runs (see the HPC section
below).

## Quick setup

`setup/install_requirements.py` offers to run the setup wizard at the end
of the installation, and the wizard can be run on its own at any time:

```bash
# On ARC, activate the project environment first
source activate_project_env_arc.sh

python setup/setup_pyannote.py
```

The wizard checks that pyannote.audio is installed, and offers to install
it if not. It asks for your HuggingFace token and saves it to
`hf_token.txt` in the repository root, checks that the token can reach
the model, downloads and caches the pipeline, and runs it on a short test
signal.

## Manual setup

### Install pyannote.audio

```bash
pip install "pyannote.audio>=3.1,<4"
```

Quote the requirement: unquoted, the shell reads `>=3.1` as a redirection
to a file. The published results were produced with pyannote.audio 3.4.0,
the version recorded in `output/evaluation/der_summary.json`, and 4.x is
not supported. Check the installed version with:

```bash
python -c "import pyannote.audio; print(pyannote.audio.__version__)"
```

### Get a HuggingFace token

Create a "Read" token at https://huggingface.co/settings/tokens. With the
same account, open both of these pages and accept the terms, because the
diarisation pipeline depends on the segmentation model:

- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0

### Make the token available

Every part of the workflow finds the token through the same lookup
(`preflight.resolve_hf_token`). It tries the environment variables
`HF_TOKEN`, `HUGGINGFACE_TOKEN` and `HUGGING_FACE_HUB_TOKEN`, then
`hf_token.txt` in the repository root, then `hf_token.txt` in the current
directory, then `$HF_TOKEN_PATH`, the token file under `HF_HOME` (where
`huggingface-cli login` stores it) and the legacy
`~/.huggingface/token`. The simplest choice is the file in the
repository root:

```bash
printf '%s' 'hf_your_actual_token_here' > hf_token.txt
```

Save the token as plain ASCII or UTF-8 text with no byte-order mark, as
`printf '%s'` does. Every part of the workflow strips the whitespace
around the token when it reads the file, so a trailing newline from
`echo`, or a Windows `\r\n`, does no harm there. Both readers, the Python
lookup and `arc_load_hf_token` in `hpc/common/arc_common.sh`, which the
HPC jobs call, also read a file that begins with a UTF-8 byte-order mark
or is saved as UTF-16; the HPC jobs convert UTF-16 with `iconv` and stop
with a message where it is missing. A check run by hand can still trip on
a Windows line ending. In the `curl` check
in [ARC_USAGE_GUIDE.md](ARC_USAGE_GUIDE.md#speaker-diarisation-on-arc),
`$(cat hf_token.txt)` drops a final `\n` but keeps a `\r`, and the `\r`
then reaches the request header with the token and can make the check
fail. On Windows, an editor or the `>` of Windows PowerShell can save the
file with a byte-order mark or as UTF-16, so write it with:

```powershell
Set-Content -NoNewline -Encoding ascii hf_token.txt 'hf_your_actual_token_here'
```

With these options, `Set-Content` writes the same bytes as `printf`, in
Windows PowerShell and in PowerShell 7 alike. `hf_token.txt` is ignored by git.

### Download the models

`setup/cache_pyannote_arc.py` downloads the pipeline, its segmentation
model and its speaker-embedding model into the directory pyannote.audio
3.x loads them from: `$PYANNOTE_CACHE`, or `~/.cache/torch/pyannote` when
that is not set. pyannote 3.x does not read the Hugging Face hub cache
(`$HF_HOME/hub`). Despite its name the script works on any machine with
network access:

```bash
python setup/cache_pyannote_arc.py
```

It also stores the token in `$HF_HOME/token` with owner-only permissions,
unless you pass `--no-save-token`.

### Check it works

```bash
python -m preflight --diarisation-required
```

This reports whether pyannote.audio imports, whether any cached pipeline
configuration is intact and whether a token was found. When none was, it
also reports whether the pipeline is cached. Each failure comes with a
remedy.

## HPC setup

Activate the project environment before installing or downloading
anything, so that packages and model weights go to project storage and
not to your home quota:

```bash
source activate_project_env_arc.sh
python setup/setup_pyannote.py
```

`pip show pyannote.audio | grep Location` shows where a package went,
which on ARC should be under `$DATA/speech_transcription_env`.

Fetch the weights on the login node, which has network access, before
submitting any job that uses speaker attribution:

```bash
source ~/paper_speech_transcription/activate_project_env_arc.sh
python ~/paper_speech_transcription/setup/cache_pyannote_arc.py
```

The compute node then finds the weights in the shared cache. If they are
missing, the job does not fail silently. For a gated model it cannot
fetch, pyannote 3.x returns no pipeline, which the workflow treats as a
failed load: it writes the transcript without speaker labels and reports
the run as incomplete. [ARC_USAGE_GUIDE.md](ARC_USAGE_GUIDE.md#speaker-diarisation-on-arc)
gives the ARC details, including how to check a token with `curl`.

To diarise a batch on the cluster:

```bash
hpc/submit_transcription.sh --speaker-attribution --language english
```

The recordings are read from `$TRANSCRIPTION_AUDIO_DIR`, or
`$DATA/speech_transcription_env/audio_input` by default, and the
transcripts written to `output/transcripts/`.

## Common problems

### "401 Unauthorized" or access denied

The token is invalid, or its account has not accepted the terms of both
models above. Check that the token starts with `hf_` and was not
truncated, accept the terms on both pages, and try again after a few
minutes. To test the token from Python:

```bash
python -c "
from huggingface_hub import HfApi
from preflight import resolve_hf_token
token, source = resolve_hf_token()
print('token from', source)
HfApi().model_info('pyannote/speaker-diarization-3.1', token=token)
print('Access granted.')
"
```

The older `https://huggingface.co/api/whoami` endpoint returns 401 for
some accounts even when the token is valid, so use `/api/whoami-v2` for a
`curl` check.

### "No module named 'pyannote'"

Install it into the active environment with the quoted requirement
above. If dependency conflicts stop the install, create a fresh virtual
environment and install `requirements.txt` into it.

### Running out of GPU memory

The workflow runs diarisation on the GPU when one is available and on the
CPU otherwise. If the GPU runs out of memory, run on a machine or job
without one. The HPC transcription jobs already run on CPU.

### SSL or proxy errors during download

A firewall is blocking the Hub. Set your institution's proxy
(`HTTPS_PROXY`) or certificate bundle before downloading, or run
`setup/cache_pyannote_arc.py` on another machine and copy the directory it
reports as its pyannote cache to this machine's (`$PYANNOTE_CACHE`, or
`~/.cache/torch/pyannote`).

### The models download again every time

The cache is not where pyannote looks. pyannote.audio 3.x reads
`$PYANNOTE_CACHE`, or `~/.cache/torch/pyannote` when that is not set, and
ignores `HF_HOME`. `setup/cache_pyannote_arc.py` downloads into the same
directory. Use the same `PYANNOTE_CACHE` for the download and for the
runs. No job sets it, so on ARC both use `~/.cache/torch/pyannote`. The
pipeline should be there under `models--pyannote--speaker-diarization-3.1`,
beside its segmentation and embedding models, and
`python -c "from preflight import pyannote_cache_dir; print(pyannote_cache_dir())"`
prints the directory a run will read. `HF_HOME` holds the Whisper weights
and the token. On ARC, the activation script sets it to
`$DATA/speech_transcription_env/.huggingface_cache`. `TRANSFORMERS_CACHE`
is deprecated and the HPC jobs unset it.

### No speakers, or one speaker, in the output

Check that the recording is not silent or very quiet, and that it holds
more than one voice. `--num-speakers`, `--min-speakers` and
`--max-speakers` constrain the count when you know it, but read the
caveats in
[docs/advanced_usage.md](docs/advanced_usage.md#constraining-the-number-of-speakers)
before relying on them.

## Usage

```bash
python transcription.py input.wav --speaker-attribution --language english

python transcription.py input.wav --speaker-attribution \
    --mask-personal-names --fix-spurious-repetitions --language english
```

A run with speaker attribution writes two transcripts: the base one,
without speaker labels, and a `_with_speakers` one that labels each
speaker's turn:

```
[SPEAKER_00] Hello everyone, welcome to our meeting.
[SPEAKER_01] Thank you for joining us today.
[SPEAKER_00] Let's start with the first agenda item...
```

[docs/advanced_usage.md](docs/advanced_usage.md#accuracy-and-when-to-use-it)
shows both, says what the labels do and do not identify, and describes
the recordings on which diarisation works best. The measured diarisation
error on the AMI meeting corpus is reported in the manuscript.

## Further reading

The upstream project and the model card:

- pyannote.audio: https://github.com/pyannote/pyannote-audio
- Model card: https://huggingface.co/pyannote/speaker-diarization-3.1
