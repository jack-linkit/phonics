# Production Architecture

```mermaid
flowchart TD
  A[Student Browser] --> B[FastAPI App]

  A -->|Upload file or MediaRecorder recording| B
  B --> C[S3 Original Audio]
  C --> D[FFmpeg Lambda]
  D --> E[S3 Normalized WAV]

  E --> F[FastAPI App Fetches/Uses WAV]
  F --> G[Azure Pronunciation Assessment]

  G --> H[Raw Azure Alignment Payload]
  H --> I[FastAPI Parses Results]

  I --> J[Expected Word Results]
  I --> K[Derived Metrics]
  I --> L[Raw Provider Payload]

  J --> M[Assessment UI]
  K --> M
  L --> M

  M --> N[Highlighted Expected Text]
  M --> O[Word-Level Playback]
  M --> P[Full Recording Playback]
  M --> Q[Collapsed Full API Response]

  I --> R[(Production DB)]
  R --> S[AssessmentAttempt]
  R --> T[AssessmentWordResult]

  H --> U[S3 Raw Payload Archive]
```

## Processing Flow

```mermaid
sequenceDiagram
  participant Browser as Student Browser
  participant API as FastAPI API
  participant S3 as S3
  participant Lambda as FFmpeg Lambda
  participant Azure as Azure Speech
  participant DB as Database

  Browser->>API: Submit assessment metadata + audio
  API->>S3: Upload original audio
  API->>Lambda: Invoke conversion job
  Lambda->>S3: Read original audio
  Lambda->>Lambda: Convert/remux to WAV with ffmpeg
  Lambda->>S3: Write normalized WAV
  Lambda-->>API: Return converted WAV S3 key

  API->>S3: Read normalized WAV
  API->>Azure: Submit WAV + reference text
  Azure-->>API: Return pronunciation assessment JSON

  API->>DB: Store AssessmentAttempt
  API->>DB: Store AssessmentWordResult rows
  API->>S3: Archive raw Azure payload

  API-->>Browser: Return metrics + word alignment + payload path
  Browser->>Browser: Render highlighted words
  Browser->>Browser: Play full/word-level audio from local recording
```

## Components

- Student Browser: records or uploads student audio.
- FastAPI App: accepts assessment metadata and coordinates processing.
- S3 Original Audio: stores uploaded source audio.
- FFmpeg Lambda: converts browser/uploaded audio to normalized WAV.
- S3 Normalized WAV: stores converted audio for assessment.
- Azure Pronunciation Assessment: returns pronunciation and alignment data.
- Production DB: stores attempt-level and word-level results.
- S3 Raw Payload Archive: stores raw Azure responses for audit/debug.
