import json
import logging

from shieldfont.infrastructure.logging import (
    JsonEventFormatter,
    LogFormat,
    resolve_log_settings,
)


def test_json_formatter_emits_structured_event() -> None:
    record = logging.LogRecord(
        name="shieldfont.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg="Target collision",
        args=(),
        exc_info=None,
    )
    record.code = "SF-DICT-TARGET-COLLISION"
    record.stage = "dictionary.validate"
    record.details = {"scope": "latin-en"}

    event = json.loads(JsonEventFormatter().format(record))

    assert event["level"] == "error"
    assert event["code"] == "SF-DICT-TARGET-COLLISION"
    assert event["stage"] == "dictionary.validate"
    assert event["details"] == {"scope": "latin-en"}


def test_verbose_flag_enables_debug_logging() -> None:
    settings = resolve_log_settings(log_format=LogFormat.JSON, verbose=True)

    assert settings.level == logging.DEBUG
    assert settings.format is LogFormat.JSON
    assert settings.enabled is True
