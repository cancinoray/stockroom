"""The Stockroom alert poller (T7.1, issue #61).

``make oncall-poll`` runs this script in the foreground. Each poll reads the
local Prometheus alert list, writes exactly one evidence packet for the first
observation of each firing episode, and then waits the configured interval.
Pull, not push: P6 ships Prometheus rules but no Alertmanager.

``--once`` performs one poll and exits. The poll loop is single-threaded and
sleeps only after a poll completes, so polls never overlap. The clock, the
sleep and the HTTP transport are injectable; tests never wait an interval.

Exit codes: ``0`` success (including "another poller holds the lock"), ``2`` a
configuration or Prometheus failure. A failed Prometheus read leaves the state
file untouched, so de-duplication cannot be advanced by a poll that saw nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from collect_evidence import Collector, PrometheusUnavailable
from config import Config, ConfigError
from packet import (
    ALERT_NAME_LABEL,
    build_packet,
    fingerprint,
    incident_id,
    missing_required_label,
    render,
)
from state import StateStore, write_atomic

LOGGER = logging.getLogger("stockroom.oncall.poller")

EXIT_OK = 0
EXIT_FAILED = 2


def _log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """One structured JSON line; the packet is the artifact, this is the trail."""
    logger.log(level, json.dumps({"event": event, **fields}, sort_keys=True))


def run_once(
    config: Config,
    *,
    clock: Callable[[], float] = time.time,
    client: Any = None,
    state_store: StateStore | None = None,
    logger: logging.Logger = LOGGER,
) -> int:
    """Take the lock and perform one poll."""
    store = state_store or StateStore(config.state_dir)
    with store.locked() as acquired:
        if not acquired:
            _log_event(
                logger,
                logging.INFO,
                "state_locked",
                message="another poller holds the state lock; exiting without writing",
            )
            return EXIT_OK
        return _poll(config, clock=clock, client=client, store=store, logger=logger)


def run_loop(
    config: Config,
    *,
    clock: Callable[[], float] = time.time,
    client: Any = None,
    sleep: Callable[[float], None] = time.sleep,
    once: bool = False,
    state_store: StateStore | None = None,
    logger: logging.Logger = LOGGER,
) -> int:
    """Poll, then wait the configured interval; ``once`` returns after one poll.

    The lock is held for the lifetime of the loop, including the wait, so a
    second poller started while this one sleeps exits immediately instead of
    polling between intervals.
    """
    store = state_store or StateStore(config.state_dir)
    with store.locked() as acquired:
        if not acquired:
            _log_event(
                logger,
                logging.INFO,
                "state_locked",
                message="another poller holds the state lock; exiting without writing",
            )
            return EXIT_OK
        while True:
            code = _poll(config, clock=clock, client=client, store=store, logger=logger)
            if once:
                return code
            sleep(config.poll_interval_seconds)


def _poll(
    config: Config,
    *,
    clock: Callable[[], float],
    client: Any,
    store: StateStore,
    logger: logging.Logger,
) -> int:
    state = store.load()
    collector = Collector(config, clock=clock, client=client, logger=logger)
    try:
        try:
            alerts = collector.fetch_alerts()
        except PrometheusUnavailable as exc:
            _log_event(
                logger, logging.ERROR, "prometheus_unavailable", source="alerts", error=str(exc)
            )
            return EXIT_FAILED

        firing = [alert for alert in alerts if alert.get("state") == "firing"]
        rules: dict[str, dict[str, Any]] = {}
        if firing:
            try:
                rules = collector.fetch_rules()
            except PrometheusUnavailable as exc:
                _log_event(
                    logger,
                    logging.ERROR,
                    "prometheus_unavailable",
                    source="rules",
                    error=str(exc),
                )
                return EXIT_FAILED

        now = int(clock())
        episodes: dict[str, dict[str, Any]] = state["episodes"]
        seen: set[str] = set()

        for alert in firing:
            labels = alert.get("labels") if isinstance(alert.get("labels"), Mapping) else {}
            name = labels.get(ALERT_NAME_LABEL)
            alert_fingerprint = fingerprint(labels)

            if not isinstance(name, str) or not name.strip():
                _log_event(
                    logger,
                    logging.ERROR,
                    "missing_required_label",
                    alert=None,
                    missing_label=ALERT_NAME_LABEL,
                    fingerprint=alert_fingerprint,
                )
                continue

            missing = missing_required_label(labels)
            if missing is not None:
                _log_event(
                    logger,
                    logging.ERROR,
                    "missing_required_label",
                    alert=name,
                    missing_label=missing,
                    fingerprint=alert_fingerprint,
                )
                continue

            seen.add(alert_fingerprint)
            existing = episodes.get(alert_fingerprint)
            if existing is not None:
                existing["last_seen"] = now
                existing["missing_polls"] = 0
                continue

            incident = incident_id(labels, now)
            observations = collector.collect(alert, now)
            document = build_packet(alert, rules.get(name), observations, config, now)
            try:
                write_atomic(
                    config.evidence_dir / f"{incident}.json",
                    render(document).decode("utf-8"),
                )
            except OSError as exc:
                _log_event(
                    logger,
                    logging.ERROR,
                    "packet_write_failed",
                    incident_id=incident,
                    error=type(exc).__name__,
                )
                continue

            episodes[alert_fingerprint] = {
                "incident_id": incident,
                "alert": name,
                "first_seen": now,
                "last_seen": now,
                "missing_polls": 0,
            }
            _log_event(
                logger,
                logging.INFO,
                "packet_written",
                alert=name,
                incident_id=incident,
                packet=f"{incident}.json",
            )

        for episode_fingerprint, episode in list(episodes.items()):
            if episode_fingerprint in seen:
                continue
            missing_polls = int(episode.get("missing_polls", 0)) + 1
            episode["missing_polls"] = missing_polls
            if missing_polls >= config.resolve_grace_polls:
                del episodes[episode_fingerprint]
                _log_event(
                    logger,
                    logging.INFO,
                    "incident_resolved",
                    alert=episode.get("alert"),
                    incident_id=episode.get("incident_id"),
                    missing_polls=missing_polls,
                )

        try:
            store.save(state)
        except OSError as exc:
            _log_event(logger, logging.ERROR, "state_write_failed", error=type(exc).__name__)
            return EXIT_FAILED
        return EXIT_OK
    finally:
        collector.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Poll the local Prometheus and write one evidence packet per incident."
    )
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    arguments = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # The collector's query text and the local URLs are not secrets, but a line
    # per request buries the poller's own events. Keep the trail to this tool.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = Config.from_env()
    except ConfigError as exc:
        _log_event(LOGGER, logging.ERROR, "config_invalid", error=str(exc))
        return EXIT_FAILED

    try:
        return run_loop(config, once=arguments.once)
    except KeyboardInterrupt:
        _log_event(LOGGER, logging.INFO, "stopped")
        return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
