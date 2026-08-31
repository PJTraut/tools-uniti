"""Qt-independent resource and worker services for UNITI."""

from .cancel import CancellationToken, WorkCancelled

__all__ = ["CancellationToken", "WorkCancelled"]
