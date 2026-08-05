from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError


def test_shieldfont_error_exposes_stable_diagnostics() -> None:
    error = ShieldFontError(
        "Invalid input",
        code=ErrorCode.INVALID_INPUT,
        exit_code=ExitCode.INVALID_INPUT,
        stage="config.load",
        details={"field": "schema"},
    )

    assert str(error) == "Invalid input"
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.exit_code is ExitCode.INVALID_INPUT
    assert error.stage == "config.load"
    assert error.details == {"field": "schema"}
