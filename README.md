# Phonics Oral Reading Assessment PoC

FastAPI demo app for assessing student oral reading audio with Azure Speech Pronunciation Assessment.

The app hosts both the API and the browser UI from one container. The UI supports either uploading an audio file or recording audio in the browser before submitting.

## Prerequisites

- Docker
- Azure Speech resource
- Azure Speech key and region

## Environment Variables

Create a local `.env` file from the example:

```bash
cp .env.example .env
```

Fill in:

```env
AZURE_SPEECH_KEY=your-azure-speech-key
AZURE_SPEECH_REGION=eastus
```

The region must match the Azure Speech resource region exactly.

## Build The Docker Image

```bash
make docker-build
```

Equivalent Docker command:

```bash
docker build -t phonics-poc:local .
```

## Run The Demo Container

```bash
make docker-run
```

Equivalent Docker command:

```bash
docker run --rm -p 8000:8000 --env-file .env phonics-poc:local
```

Open the demo UI:

```text
http://localhost:8000/
```

## Local Development Run

If dependencies are installed locally, run:

```bash
make start
```

Equivalent command:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## Demo Flow

1. Open `http://localhost:8000/`.
2. Enter student ID, assessment ID, reference text, and time limit.
3. Choose either `Upload file` or `Record audio`.
4. If recording, click `Start Recording`; recording auto-stops at the selected time limit.
5. Click `Submit`.
6. Review highlighted expected text, word-level playback, full recording playback, and the collapsed API response.

## Audio Conversion

The container includes `ffmpeg`.

Uploaded or browser-recorded non-WAV audio is converted server-side to WAV before being sent to Azure Speech. WAV uploads pass through directly.

## Outputs

Raw Azure alignment payloads are written to:

```text
outputs/{student_id}_{assessment_id}.json
```

In the Docker container this path is ephemeral unless you mount a volume.

Example with persisted outputs:

```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/outputs:/app/outputs" \
  phonics-poc:local
```

## Troubleshooting

If Azure returns `ResultReason.Canceled`, common causes are:

- Missing `AZURE_SPEECH_KEY` or `AZURE_SPEECH_REGION` in the container.
- Region does not match the Azure Speech resource.
- Invalid or expired Azure key.
- Container cannot reach Azure Speech over the network.
- Audio is silent, too short, or unreadable after conversion.

Confirm env vars are passed with `--env-file .env` or `make docker-run`.
