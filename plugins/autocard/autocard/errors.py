class AutocardError(Exception):
    """Base user-facing error."""


class InvalidWorkbookError(AutocardError):
    """The uploaded file is not a safe readable OOXML workbook."""


class UnsupportedTemplateError(AutocardError):
    """The workbook does not match a supported character-sheet template."""


class DownloadRejectedError(AutocardError):
    """A remote workbook URL violated the downloader security policy."""
