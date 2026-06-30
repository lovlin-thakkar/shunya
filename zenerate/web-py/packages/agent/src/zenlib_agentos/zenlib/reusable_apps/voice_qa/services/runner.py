import logging
import uuid

from django.utils import timezone

from ..models import TestRun, TestResult, JudgeScore
from .caller import get_caller
from .judge import score_transcript
from zenlib.reusable_apps.multitenant import context

logger = logging.getLogger(__name__)


def run_scenario(test_run_id: str):
    try:
        run = TestRun.objects.select_related("agent", "scenario").get(id=test_run_id)
    except TestRun.DoesNotExist:
        logger.error(f"TestRun {test_run_id} not found")
        return

    run.status = TestRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    caller = get_caller(run.mode, run.agent)
    conversation_id = str(uuid.uuid4())
    transcript_turns = []

    try:
        # Both AudioCaller (Pipecat/Daily) and RemoteAudioCaller (ElevenLabs WS)
        # expose run_scenario; turn-by-turn TextCaller does not. Keying off the
        # capability lets remote ElevenLabs agents take the audio path even when
        # the run's mode is "text".
        if hasattr(caller, "run_scenario"):
            # Give the during-call judge sub-agent the scenario's rubric.
            if hasattr(caller, "rubric"):
                caller.rubric = run.scenario.rubric
            caller._connect()
            if caller.observer_url:
                run.observer_url = caller.observer_url
                run.save(update_fields=["observer_url"])
                logger.info(f"Observer URL for run {test_run_id}: {caller.observer_url}")
            transcript_turns = caller.run_scenario(
                run.scenario.steps, conversation_id, recording_id=str(run.id)
            )
            # Remote agent may have hung up mid-call — record why for the run page.
            reason = getattr(caller, "disconnect_reason", "")
            if reason:
                run.disconnect_reason = reason
                run.save(update_fields=["disconnect_reason"])
                logger.warning(f"TestRun {test_run_id} agent disconnected: {reason}")
        else:
            if getattr(run.agent, "greeting", ""):
                transcript_turns.append({"speaker": "agent", "text": run.agent.greeting, "ts_ms": 0, "quirks": []})
            for step in run.scenario.steps:
                raw_text = step.get("raw", step.get("text", ""))
                clean_text = step.get("text", raw_text)
                quirks = [q.get("tag") for q in step.get("quirks", [])]
                transcript_turns.append({"speaker": "caller", "text": clean_text, "raw": raw_text, "ts_ms": 0, "quirks": quirks})
                result = caller.send(raw_text, conversation_id)
                transcript_turns.append({"speaker": "agent", "text": result["response"], "ts_ms": result.get("ts_ms", 0), "quirks": []})

        assertion_results = _evaluate_assertions(run.scenario.assertions, transcript_turns, run.agent)
        # Skip None (semantic assertions pending LLM evaluation) — treat as neutral.
        # all() on an empty sequence returns True, correct when all assertions are semantic.
        assertions_passed = all(
            a["passed"] for a in assertion_results if a["passed"] is not None
        )

        test_result = TestResult.objects.create(
            test_run=run, passed=assertions_passed,
            transcript=transcript_turns, assertion_results=assertion_results,
        )

        _promote_live_scores(run, test_result)
        _post_call_score(run, test_result)

        run.status = TestRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        logger.info(f"TestRun {test_run_id} completed. Assertions passed: {assertions_passed}")

    except TestRun.DoesNotExist:
        logger.warning(f"TestRun {test_run_id} was deleted before results could be saved — discarding")
        return
    except Exception as e:
        import httpx
        # Transient capacity/overload errors from pipecat — re-raise so the
        # Celery task can retry with backoff instead of permanently failing the run.
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (429, 502, 503):
            logger.warning(f"TestRun {test_run_id} got transient {e.response.status_code} from pipecat — will retry")
            try:
                run.status = TestRun.Status.QUEUED
                run.started_at = None
                run.save(update_fields=["status", "started_at"])
            except Exception:
                pass
            raise
        logger.exception(f"TestRun {test_run_id} failed: {e}")
        try:
            run.status = TestRun.Status.FAILED
            run.completed_at = timezone.now()
            run.error_message = str(e)
            run.save(update_fields=["status", "completed_at", "error_message"])
        except Exception:
            pass  # run may have been deleted; nothing to do


def _promote_live_scores(run: TestRun, test_result: TestResult):
    """Promote the final live scores (Sonnet, written during the call) to
    permanent JudgeScore rows on the TestResult.

    live_scores is refreshed from the DB to ensure we get the last batch
    written by the eval agent after the final agent turn. If no scores exist
    (text mode, or live scoring not wired up) this is a no-op.
    """
    run.refresh_from_db(fields=["live_scores"])
    raw_scores = (run.live_scores or {}).get("scores") or []
    if not raw_scores:
        return

    tenant = context.current_tenant.get()
    rubric = run.scenario.rubric or {}

    judge_scores = []
    for s in raw_scores:
        field = s.get("field", "")
        if not field:
            continue
        try:
            score = max(0.0, min(1.0, float(s.get("score", 0.0))))
        except (TypeError, ValueError):
            continue
        judge_scores.append(JudgeScore(
            test_result=test_result,
            field=field,
            score=round(score, 2),
            reasoning=str(s.get("reasoning", ""))[:500],
            passed=bool(s.get("passed", score >= 0.7)),
            tenant=tenant,
        ))

    if not judge_scores:
        return

    JudgeScore.objects.bulk_create(judge_scores, ignore_conflicts=True)

    weights = [rubric.get(js.field, 1.0) for js in judge_scores]
    total_weight = sum(weights) or 1.0
    weighted_avg = sum(js.score * w for js, w in zip(judge_scores, weights)) / total_weight
    test_result.passed = test_result.passed and weighted_avg >= 0.7
    test_result.save(update_fields=["passed"])

    logger.info(
        "Promoted %d live scores to JudgeScore rows for TestResult %s (weighted avg %.2f)",
        len(judge_scores), test_result.id, weighted_avg,
    )


def _post_call_score(run: TestRun, test_result: TestResult):
    """Score the full transcript with Claude Sonnet after the call ends.

    Only runs for text mode — remote mode already has scores from live scoring
    promoted by _promote_live_scores(). Runs synchronously inside run_scenario_task
    so scores are ready before the task completes.
    """
    run.refresh_from_db(fields=["live_scores"])
    if (run.live_scores or {}).get("scores"):
        return  # remote mode: live scores already promoted, nothing to do

    rubric = run.scenario.rubric or {}
    scores = score_transcript(test_result.transcript, rubric)
    if not scores:
        return

    tenant = context.current_tenant.get()
    judge_scores = [
        JudgeScore(
            test_result=test_result,
            field=s["field"],
            score=s["score"],
            reasoning=s["reasoning"],
            passed=s["passed"],
            tenant=tenant,
        )
        for s in scores
    ]
    JudgeScore.objects.bulk_create(judge_scores, ignore_conflicts=True)

    weights = [rubric.get(js.field, 1.0) for js in judge_scores]
    total_weight = sum(weights) or 1.0
    weighted_avg = sum(js.score * w for js, w in zip(judge_scores, weights)) / total_weight
    test_result.passed = test_result.passed and weighted_avg >= 0.7
    test_result.save(update_fields=["passed"])

    logger.info(
        "Post-call scored %d fields for TestResult %s (weighted avg %.2f)",
        len(judge_scores), test_result.id, weighted_avg,
    )


# Assertions evaluated by fast regex/counter checks on the transcript.
HEURISTIC_ASSERTIONS = frozenset({
    "resolved_within_5_turns",
    "resolved_within_6_turns",
    "agent_acknowledges_frustration",
    "appointment_confirmed",
    "correct_date_time_captured",
    "contact_details_collected",
    "agent_provides_confirmation_number_or_summary",
    "agent_asks_for_clarification_when_unclear",
})

def _evaluate_assertions(assertions, transcript, agent):
    agent_turns = [t["text"].lower() for t in transcript if t["speaker"] == "agent"]
    full_text = " ".join(agent_turns)
    return [
        {"assertion": a, "passed": _check_assertion(a, transcript, full_text), "semantic": False}
        for a in assertions
    ]


def _check_assertion(assertion, transcript, full_agent_text):
    agent_turns = [t for t in transcript if t["speaker"] == "agent"]
    caller_turns = [t for t in transcript if t["speaker"] == "caller"]
    agent_count = len(agent_turns)
    all_text = " ".join(t["text"].lower() for t in transcript)

    if assertion == "resolved_within_5_turns":
        return agent_count <= 5
    if assertion == "resolved_within_6_turns":
        return agent_count <= 6
    if assertion == "agent_acknowledges_frustration":
        return any(w in full_agent_text for w in ["sorry", "understand", "apologize", "frustrat", "hear you", "i see"])
    if assertion == "appointment_confirmed":
        return any(w in full_agent_text for w in ["confirmed", "booked", "scheduled", "appointment", "see you"])
    if assertion == "correct_date_time_captured":
        import re
        time_pattern = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\btuesday\b|\bwednesday\b|\bmonday\b|\bthursday\b|\bfriday\b")
        return bool(time_pattern.search(full_agent_text))
    if assertion == "contact_details_collected":
        # Check if the agent repeated back any name, email, or phone number from the transcript
        caller_text = " ".join(t["text"].lower() for t in caller_turns)
        import re
        phone = re.search(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", caller_text)
        email = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+", caller_text)
        if phone and phone.group() in full_agent_text:
            return True
        if email and email.group().lower() in full_agent_text:
            return True
        # Fall back to checking if agent acknowledged receiving details
        return any(w in full_agent_text for w in ["got it", "noted", "i have your", "i've noted", "thank you"]) and agent_count >= 2
    if assertion == "agent_provides_confirmation_number_or_summary":
        return any(w in full_agent_text for w in ["confirm", "reference", "summary", "to recap", "to confirm", "number"])
    if assertion == "agent_asks_for_clarification_when_unclear":
        return any(w in full_agent_text for w in ["could you", "can you", "please repeat", "clarif", "say that again", "didn't catch"])
    # Unknown assertion — default pass, semantic evaluation not configured
    return True
