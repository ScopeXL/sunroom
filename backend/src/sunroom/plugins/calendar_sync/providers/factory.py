"""The factory the engine makes providers with: an account and its secrets → its provider."""

from __future__ import annotations

import json
from typing import Any

from sunroom.plugins.calendar_sync.models import Provider, SyncAccount
from sunroom.plugins.calendar_sync.providers.base import CalendarProvider, ErrorKind, SyncError
from sunroom.plugins.calendar_sync.providers.fake import FAKE_REMOTES, FakeProvider, FakeRemote
from sunroom.plugins.calendar_sync.providers.holidays import HolidaysProvider
from sunroom.plugins.calendar_sync.providers.ics import IcsProvider
from sunroom.plugins.context import PluginContext


def make_factory(ctx: PluginContext, extra: dict[str, Any] | None = None) -> Any:
    """The engine's ProviderFactory: an account and its secrets → its provider."""
    more = extra or {}

    async def household_language() -> str:
        return (await ctx.household.get()).language

    def make(account: SyncAccount, secrets: dict[str, Any]) -> CalendarProvider:
        config: dict[str, Any] = json.loads(account.config_json or "{}")
        http = ctx.http(allow_private=account.allow_private)
        if account.provider == Provider.ICS:
            if "url" not in secrets:
                raise SyncError(ErrorKind.AUTH, "api.sync.paste_address_again")
            return IcsProvider(http, str(secrets["url"]), account.label, ctx.zone)
        if account.provider == Provider.HOLIDAYS:
            return HolidaysProvider(
                str(config.get("country", "")),
                config.get("subdivision"),
                ctx.now,
                language_of=household_language,
            )
        if account.provider == Provider.FAKE and ctx.test_mode:
            return FakeProvider(FAKE_REMOTES.setdefault(account.id, FakeRemote()))
        if account.provider in more:
            return more[account.provider](account, secrets, config, http)
        raise SyncError(ErrorKind.BAD_DATA, "api.sync.unknown_kind")

    return make
