"""Send Feedback without an account (UX §4 Support Sunroom, ADR 0042): ``POST /api/feedback``
posts what a family wrote, as Discord's webhook body (core/feedback.py), to the project's relay,
which keeps the webhook itself: a secret, never in this repo, the image or a log. Nothing but the
words, the version and the install is sent.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints

from sunroom.auth.deps import ActorDep
from sunroom.core import feedback
from sunroom.core.config import Settings
from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.core.netguard import OutboundError
from sunroom.core.version import build_info
from sunroom.state import StateDep

FEEDBACK_URL = ""
"""The project's relay, filled in by the owner before a release, as `support.ts`'s Patreon link
is. Empty: Send Feedback opens GitHub's new-issue page instead. ``SUNROOM_FEEDBACK_URL`` wins
when it's set, and set empty it turns feedback off."""

ANSWER_MAX_BYTES = 64 * 1024

router = APIRouter(prefix="/api", tags=["meta"])
log = get_logger(__name__)


class FeedbackIn(BaseModel):
    kind: feedback.FeedbackKind
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)] = ""
    contact: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


def address(settings: Settings) -> str | None:
    """Where feedback goes, or None when it's off on this server."""
    configured = settings.sunroom_feedback_url
    url = FEEDBACK_URL if configured is None else configured.get_secret_value()
    return url.strip() or None


@router.post("/feedback", status_code=204)
async def send_feedback(body: FeedbackIn, state: StateDep, actor: ActorDep) -> None:
    """Any signed-in device or paired screen, at most five times an hour for the whole server.
    The test server keeps what it would have sent (``GET /api/_test/feedback``) and posts
    nothing, as it makes up the update check's answer."""
    url = address(state.settings)
    if url is None:
        raise AppError(409, "feedback_off", "Feedback isn't set up on this Sunroom.")
    if not state.feedback.take(state.clock.now()):
        raise AppError(
            429, "too_much_feedback", "That's all Sunroom sends in an hour. Try again later."
        )
    sent = feedback.message(
        kind=body.kind,
        title=body.title,
        words=body.body,
        contact=body.contact,
        version=build_info().version,
        install=feedback.INSTALL_WORDS[state.settings.sunroom_install_kind],
    )
    if state.settings.sunroom_test_mode:
        state.feedback.kept.append(sent)
        log.info("feedback.kept", kind=body.kind)
        return
    # Never the address in a log: a server's own may hold a Discord webhook's token.
    try:
        answer = await state.http.request(
            "POST",
            url,
            headers={"Content-Type": "application/json"},
            content=json.dumps(sent).encode(),
            max_bytes=ANSWER_MAX_BYTES,
            follow_redirects=False,
        )
    except OutboundError as exc:
        log.warning("feedback.unreachable", reason=exc.code)
        raise AppError(502, "feedback_failed", "Couldn't send it. Try again in a moment.") from exc
    if not answer.ok:
        log.warning("feedback.refused", status=answer.status)
        raise AppError(502, "feedback_failed", "Couldn't send it. Try again in a moment.")
    log.info("feedback.sent", kind=body.kind)
