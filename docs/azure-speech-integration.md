# Azure Speech Pronunciation Assessment Integration

## Purpose

This proof of concept uses the Azure Speech SDK's Pronunciation Assessment capability to assess a student reading a known passage. Azure receives the normalized audio and the expected passage text, then returns word-level alignment, error classifications, scores, and timing. The application derives oral-reading metrics from that response.

This is not a general speech-to-text integration. It is a reference-text assessment: the passage must be known before the recording is submitted.

## Services And Endpoints

| Endpoint or service | Method | Purpose |
| --- | --- | --- |
| `POST /assess-reading` | `POST` | Application endpoint that accepts the student, passage, optional time limit, and audio; calls Azure; and returns parsed results. |
| `GET /` | `GET` | Serves the proof-of-concept browser UI. |
| Azure Speech Pronunciation Assessment | SDK call | The server uses `azure-cognitiveservices-speech`, not a hand-built REST request. `SpeechConfig(subscription, region)` selects the Azure Speech resource and the SDK manages the authenticated regional Speech service connection. |

For a platform integration, keep the Azure key on the server. The browser must submit audio to the platform API and must not receive Azure credentials.

## Azure Resource Configuration

Create an Azure AI Speech resource and provide its credentials to the service runtime:

```env
AZURE_SPEECH_KEY=<Azure Speech resource key>
AZURE_SPEECH_REGION=<resource region, for example eastus>
```

`AZURE_SPEECH_REGION` must exactly match the region of the Speech resource. The demo reads these variables for every assessment request and returns HTTP 500 if either is absent.

The current SDK setup is in `assess_with_azure` in `app.py`:

| Setting | Current value | Effect |
| --- | --- | --- |
| Authentication | Speech subscription key and region | Authenticates the server to the Azure Speech resource. |
| Recognition language | `en-US` | Selects US English recognition and assessment behavior. This is currently hard-coded through `AzureConfig.language`. |
| Reference text | Request `reference_text` | The expected passage used to align the student's spoken words. |
| Grading system | `HundredMark` | Returns scores on a 0-100 scale. |
| Granularity | `Phoneme` | Requests phoneme-level detail in the raw Azure result, in addition to word data. |
| Miscue detection | `True` | Requests omission, insertion, and mispronunciation detection. |
| Recognition method | `recognize_once_async()` | Processes one recognition result for the submitted audio. |

The integration uses the Speech SDK rather than exposing Azure's underlying Speech service URLs as an application contract. If the platform uses an Azure REST or WebSocket integration instead, it must implement the equivalent Pronunciation Assessment configuration and regional resource routing supported by Azure for the selected API version.

## Application Assessment Contract

### Request

`POST /assess-reading` accepts `multipart/form-data`:

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `student_id` | Yes | string | Identifier used in the response and raw-payload file name. |
| `reference_text` | Yes | string | Exact passage the student is expected to read. |
| `time_limit_seconds` | No | integer | Intended assessment-window duration. It is used for the derived WCPM denominator; it is not sent to Azure and does not stop server-side assessment processing. |
| `audio` | Yes | file | Student recording. WAV is passed through; other extensions are converted before Azure submission. |

Example:

```bash
curl -X POST http://localhost:8000/assess-reading \
  -F student_id=123 \
  -F reference_text="The dog ran fast down the hill." \
  -F time_limit_seconds=60 \
  -F audio=@student.wav
```

### Audio Handling

The demo passes `.wav` files to Azure unchanged. Other uploads are converted with `ffmpeg` to mono, 16 kHz WAV (`-ac 1 -ar 16000`). A production service should define and validate its accepted audio formats, maximum file size and duration, and whether audio is retained after processing.

### Response

The successful response contains:

| Field | Source | Use |
| --- | --- | --- |
| `provider` | Application constant | `azure_pronunciation_assessment`. |
| `provider_scores` | `NBest[0].PronunciationAssessment` | Azure's passage-level accuracy, fluency, completeness, and pronunciation scores when returned. |
| `words` | `NBest[0].Words` | Recognized/aligned words with score, error type, offset, and duration. |
| `expected_word_results` | Application mapping | One row per whitespace-separated expected word for display and scoring. |
| `derived_metrics` | Application calculation | Words read, correct words, omissions, insertions, mispronunciations, accuracy percent, duration, and WCPM. |
| `raw_provider_payload` | Azure SDK detailed JSON | Original Azure response for audit and future reprocessing. |
| `raw_alignment_path` | Application storage path | Demo-local location of the saved raw JSON. |

Azure offsets and durations are in 100-nanosecond ticks in the raw JSON. The application converts them to seconds by dividing by `10,000,000`.

## Word Classification And Derived Metrics

The application consumes Azure word `PronunciationAssessment.ErrorType` values. The observed and documented values are `None`, `Omission`, `Insertion`, and `Mispronunciation`.

| Metric | Current calculation |
| --- | --- |
| Words read | All returned words except omissions. |
| Words correct | Returned words whose error type is empty, `None`, or absent. |
| Omissions | Returned words with `Omission`. |
| Insertions | Returned words with `Insertion`. |
| Mispronunciations | Returned words with `Mispronunciation`. |
| Accuracy percent | `words_correct / number of whitespace-separated expected words * 100`. |
| WCPM | `words_correct / (duration_seconds / 60)`. The supplied `time_limit_seconds` takes precedence; otherwise the end time of the last non-omitted word is used. |

These are PoC business rules, not Azure-defined assessment rules. Requirements should explicitly decide how punctuation and tokenization work, whether insertions reduce a score, which Azure score is authoritative, and whether WCPM uses a fixed benchmark window or observed reading duration.

## Important Production Decisions

1. Use an authenticated platform endpoint and authorize each student, assessor, passage, and attempt. The demo allows all CORS origins and has no application authentication.
2. Store Azure keys in the platform's secret manager, rotate them, and restrict outbound access to Azure Speech as required by network policy.
3. Use a stable passage identifier and persist the exact passage version with every attempt. Do not rely on client-provided text alone for high-stakes assessment.
4. Define a recording-duration strategy. The current one-shot SDK call is appropriate for a short, single utterance. Longer passage reads should be designed and tested with Azure's supported continuous/streaming recognition pattern and a clear end-of-recording rule.
5. Persist original audio, normalized audio, raw Azure payload, derived results, Azure region, SDK/API version, and assessment configuration when auditability or rescoring is required.
6. Establish scoring validation with representative student recordings before treating Azure error types or scores as instructional or high-stakes decisions.
7. Handle Azure cancellation, timeout, malformed audio, no-match, and transient service failures as distinct, user-safe outcomes. The demo maps all processing failures to HTTP 500.
8. Set retention, access-control, encryption, and deletion requirements for student voice recordings and assessment data.

## Current PoC Limitations

- `reference_text.split()` is used for expected-word mapping, so punctuation, contractions, and tokenization may not align with Azure's word segmentation in every passage.
- The raw response and full raw payload are returned to the browser. A production API should return only the fields needed by the client and keep the raw payload server-side.
- Raw results are written to local `outputs/{student_id}_{timestamp}.json`; container storage is ephemeral unless a volume is mounted.
- The language is fixed to `en-US`; a production design needs an approved language/locale policy per assessment or passage.
- The optional time limit affects only WCPM calculation in the API. The browser recording UI may use it to stop recording, but Azure itself does not receive a time-limit setting.

## Azure References

- [Azure Speech Pronunciation Assessment overview](https://learn.microsoft.com/azure/ai-services/speech-service/pronunciation-assessment)
- [Azure Speech SDK for Python](https://learn.microsoft.com/python/api/overview/azure/cognitiveservices/speech-readme)
- [Speech service regions](https://learn.microsoft.com/azure/ai-services/speech-service/regions)
