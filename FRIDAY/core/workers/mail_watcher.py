import asyncio
import imaplib
import re
from email.header import decode_header
from email.parser import BytesParser
from email import policy

from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event

SNIPPET_MAX_CHARS = 120


class MailWatcherWorker(BaseWorker):
    """Polls an IMAP inbox (Gmail App Password) and announces NEW_EMAIL events.

    Anti-flood: the first successful poll marks all currently-unseen mail as
    seen silently; only mail arriving after startup is announced.
    """

    def __init__(
        self,
        event_bus: EventBus,
        host: str = "imap.gmail.com",
        user: str = "",
        password: str = "",
        poll_interval_seconds: float = 60.0,
    ):
        super().__init__("mail_watcher", event_bus)
        self._host = host
        self._user = user
        self._password = password
        self._poll_interval_seconds = poll_interval_seconds
        self._seen_uids: set[str] = set()
        self._first_poll_done = False

    async def work(self) -> None:
        if not self._user or not self._password:
            self.logger.warning("mail_watcher_missing_credentials")
            return
        while not self.should_stop:
            try:
                messages = await asyncio.to_thread(self._fetch_unread_sync)
                for uid, sender, subject, snippet in messages:
                    if uid in self._seen_uids:
                        continue
                    self._seen_uids.add(uid)
                    if self._first_poll_done:
                        await self.event_bus.publish(Event.create(
                            EventType.NEW_EMAIL,
                            {"subject": subject, "sender": sender, "snippet": snippet},
                            self.name,
                        ))
                if messages:
                    self._first_poll_done = True
            except Exception:
                self.logger.warning("mail_poll_failed", exc_info=True)
            self.heartbeat(f"mail [seen={len(self._seen_uids)}]")
            await asyncio.sleep(self._poll_interval_seconds)

    def _fetch_unread_sync(self) -> list[tuple[str, str, str, str]]:
        """One connection per poll: login, fetch unseen headers+snippet, logout."""
        client = imaplib.IMAP4_SSL(self._host)
        try:
            client.login(self._user, self._password)
            client.select("INBOX", readonly=True)
            status, data = client.uid("search", None, "UNSEEN")
            if status != "OK":
                return []
            uids = data[0].split() if data and data[0] else []
            messages: list[tuple[str, str, str, str]] = []
            for uid in uids:
                status, fetch_data = client.uid(
                    "fetch", uid,
                    "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT]<0.400>)",
                )
                if status != "OK" or not fetch_data or not fetch_data[0]:
                    continue
                # imaplib returns per-literal tuples: (meta, payload); match by metadata.
                header_raw = b""
                text_part = b""
                for item in fetch_data:
                    if isinstance(item, tuple) and len(item) >= 2:
                        meta, payload = item[0], item[1]
                        if b"HEADER" in meta:
                            header_raw = payload
                        elif b"BODY[" in meta:
                            text_part = payload
                sender, subject = self._parse_headers(header_raw)
                snippet = self._clean_snippet(text_part)
                messages.append((uid.decode(), sender, subject, snippet))
            return messages
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _parse_headers(self, raw: bytes) -> tuple[str, str]:
        try:
            parsed = BytesParser(policy=policy.default).parsebytes(raw)
            sender = self._decodeHeaderValue(parsed.get("From", ""))
            subject = self._decodeHeaderValue(parsed.get("Subject", ""))
            return sender.strip() or "unknown", subject.strip() or "(no subject)"
        except Exception:
            return "unknown", "(no subject)"

    def _decodeHeaderValue(self, value) -> str:
        try:
            parts = decode_header(str(value))
            decoded = "".join(
                frag.decode(charset or "utf-8", errors="replace") if isinstance(frag, bytes) else frag
                for frag, charset in parts
            )
            return decoded
        except Exception:
            return str(value)

    def _clean_snippet(self, raw: bytes) -> str:
        try:
            text = raw.decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", text)
            text = " ".join(text.split())
            return text[:SNIPPET_MAX_CHARS]
        except Exception:
            return ""
