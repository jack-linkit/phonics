"""
pip install fastapi uvicorn python-multipart azure-cognitiveservices-speech

export AZURE_SPEECH_KEY="..."
export AZURE_SPEECH_REGION="eastus"

Run:
  uvicorn app:app --reload

Call:
  curl -X POST http://localhost:8000/assess-reading \
    -F student_id=123 \
    -F reference_text="The dog ran fast down the hill." \
    -F time_limit_seconds=60 \
    -F audio=@student.wav
"""

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import azure.cognitiveservices.speech as speechsdk
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(title="Navi Grading Oral Reading PoC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse("index.html")


class WordMetric(BaseModel):
    word: str
    offset_seconds: float | None = None
    duration_seconds: float | None = None
    accuracy_score: float | None = None
    error_type: str | None = None


class ExpectedWordResult(BaseModel):
    expected_word: str
    spoken_word: str | None = None
    result_type: str
    accuracy_score: float | None = None
    offset_seconds: float | None = None
    duration_seconds: float | None = None


class DerivedMetrics(BaseModel):
    words_read: int
    words_correct: int
    omissions: int
    insertions: int
    mispronunciations: int
    accuracy_percent: float
    duration_seconds: float
    wcpm: float


class AssessmentResponse(BaseModel):
    student_id: str
    provider: str
    raw_alignment_path: str
    provider_scores: dict[str, Any]
    derived_metrics: DerivedMetrics
    expected_word_results: list[ExpectedWordResult]
    words: list[WordMetric]
    raw_provider_payload: dict[str, Any]


@dataclass
class AzureConfig:
    key: str
    region: str
    language: str = "en-US"


def ticks_to_seconds(value: int | float | None) -> float | None:
    """
    Azure speech offsets/durations are commonly returned in 100-nanosecond ticks.
    10,000,000 ticks = 1 second.
    """
    if value is None:
        return None
    return round(float(value) / 10_000_000, 3)


def extract_best_nbest(raw: dict[str, Any]) -> dict[str, Any]:
    nbest = raw.get("NBest") or []
    if not nbest:
        return {}
    return nbest[0]


def extract_words(raw: dict[str, Any]) -> list[WordMetric]:
    best = extract_best_nbest(raw)
    words = best.get("Words") or []

    parsed: list[WordMetric] = []

    for item in words:
        pa = item.get("PronunciationAssessment") or {}

        parsed.append(
            WordMetric(
                word=item.get("Word", ""),
                offset_seconds=ticks_to_seconds(item.get("Offset")),
                duration_seconds=ticks_to_seconds(item.get("Duration")),
                accuracy_score=pa.get("AccuracyScore"),
                error_type=pa.get("ErrorType"),
            )
        )

    return parsed


def build_expected_word_results(
    reference_text: str,
    words: list[WordMetric],
) -> list[ExpectedWordResult]:
    aligned_words = [word for word in words if word.error_type != "Insertion"]
    results: list[ExpectedWordResult] = []

    for index, expected_word in enumerate(reference_text.split()):
        aligned_word = aligned_words[index] if index < len(aligned_words) else None

        if aligned_word is None:
            results.append(
                ExpectedWordResult(
                    expected_word=expected_word,
                    result_type="Missing",
                )
            )
            continue

        error_type = aligned_word.error_type or "Correct"
        spoken_word = None if error_type == "Omission" else aligned_word.word

        results.append(
            ExpectedWordResult(
                expected_word=expected_word,
                spoken_word=spoken_word,
                result_type=error_type,
                accuracy_score=aligned_word.accuracy_score,
                offset_seconds=aligned_word.offset_seconds,
                duration_seconds=aligned_word.duration_seconds,
            )
        )

    return results


def derive_metrics(
    words: list[WordMetric],
    reference_text: str,
    time_limit_seconds: int | None,
) -> DerivedMetrics:
    """
    This is intentionally simple for the PoC.

    Azure may return ErrorType values such as:
      - None
      - Omission
      - Insertion
      - Mispronunciation

    For v1, I would count:
      Words Read      = spoken/aligned words excluding omissions
      Words Correct   = words without Omission/Insertion/Mispronunciation
      Omissions       = expected words not read
      Insertions      = extra spoken words
      Mispronunciations = aligned but poorly pronounced words

    Depending on your scoring policy, insertions may or may not reduce Words Correct.
    """

    omissions = sum(1 for w in words if w.error_type == "Omission")
    insertions = sum(1 for w in words if w.error_type == "Insertion")
    mispronunciations = sum(1 for w in words if w.error_type == "Mispronunciation")

    words_read = sum(1 for w in words if w.error_type != "Omission")

    words_correct = sum(1 for w in words if w.error_type in (None, "", "None"))

    expected_word_count = len(reference_text.split())

    accuracy_percent = (
        round((words_correct / expected_word_count) * 100, 2)
        if expected_word_count
        else 0.0
    )

    spoken_word_end_times = [
        (w.offset_seconds or 0) + (w.duration_seconds or 0)
        for w in words
        if w.error_type != "Omission"
    ]

    observed_duration_seconds = (
        max(spoken_word_end_times) if spoken_word_end_times else 0.0
    )

    # For benchmark-style oral reading fluency, you may want fixed 60s.
    # For full-passage fluency, use observed duration.
    duration_seconds = float(time_limit_seconds or observed_duration_seconds or 1.0)

    wcpm = round(words_correct / (duration_seconds / 60), 2)

    return DerivedMetrics(
        words_read=words_read,
        words_correct=words_correct,
        omissions=omissions,
        insertions=insertions,
        mispronunciations=mispronunciations,
        accuracy_percent=accuracy_percent,
        duration_seconds=round(duration_seconds, 3),
        wcpm=wcpm,
    )


def assess_with_azure(
    audio_path: str,
    reference_text: str,
    config: AzureConfig,
) -> dict[str, Any]:
    speech_config = speechsdk.SpeechConfig(
        subscription=config.key,
        region=config.region,
    )
    speech_config.speech_recognition_language = config.language

    audio_config = speechsdk.audio.AudioConfig(filename=audio_path)

    pronunciation_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
        enable_miscue=True,
    )

    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    pronunciation_config.apply_to(recognizer)

    result = recognizer.recognize_once_async().get()

    assert result is not None

    if result.reason != speechsdk.ResultReason.RecognizedSpeech:
        raise RuntimeError(f"Azure recognition failed: {result.reason}")

    raw_json = result.properties.get(
        speechsdk.PropertyId.SpeechServiceResponse_JsonResult
    )

    if not raw_json:
        raise RuntimeError("Azure did not return detailed JSON result.")

    return json.loads(raw_json)


def persist_raw_alignment(
    raw: dict[str, Any],
    student_id: str,
) -> str:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    output_path = output_dir / f"{student_id}_{timestamp}.json"
    output_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    return str(output_path)


def convert_to_wav_if_needed(input_path: str, suffix: str) -> str:
    if suffix.lower() == ".wav":
        return input_path

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        output_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                output_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        try:
            os.remove(output_path)
        except OSError:
            pass
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"ffmpeg audio conversion failed: {detail}") from exc

    return output_path


@app.post("/assess-reading", response_model=AssessmentResponse)
async def assess_reading(
    student_id: str = Form(...),
    reference_text: str = Form(...),
    time_limit_seconds: int | None = Form(None),
    audio: UploadFile = File(...),
):
    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")

    if not key or not region:
        raise HTTPException(
            status_code=500,
            detail="Missing AZURE_SPEECH_KEY or AZURE_SPEECH_REGION.",
        )

    suffix = os.path.splitext(audio.filename or "")[1] or ".wav"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name
    audio_path = tmp_path

    try:
        audio_path = convert_to_wav_if_needed(tmp_path, suffix)
        raw = assess_with_azure(
            audio_path=audio_path,
            reference_text=reference_text,
            config=AzureConfig(key=key, region=region),
        )
        raw_alignment_path = persist_raw_alignment(
            raw=raw,
            student_id=student_id,
        )

        words = extract_words(raw)
        expected_word_results = build_expected_word_results(
            reference_text=reference_text,
            words=words,
        )
        metrics = derive_metrics(
            words=words,
            reference_text=reference_text,
            time_limit_seconds=time_limit_seconds,
        )

        best = extract_best_nbest(raw)
        provider_scores = best.get("PronunciationAssessment") or {}

        return AssessmentResponse(
            student_id=student_id,
            provider="azure_pronunciation_assessment",
            raw_alignment_path=raw_alignment_path,
            provider_scores=provider_scores,
            derived_metrics=metrics,
            expected_word_results=expected_word_results,
            words=words,
            raw_provider_payload=raw,
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if audio_path != tmp_path:
            try:
                os.remove(audio_path)
            except OSError:
                pass
