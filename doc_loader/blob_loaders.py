"""Blob loaders: where document content comes from.

Only a local folder for now. A document management system (DMS) would be another
``BlobLoader`` yielding ``Blob.from_data(...)``; the parsers stay the same.
"""

from collections.abc import Iterable, Iterator
from pathlib import Path

from langchain_core.document_loaders import Blob, BlobLoader

from doc_loader.parsers import SUPPORTED_EXTENSIONS


class FolderBlobLoader(BlobLoader):
    """A blob per supported file under ``folder`` (recursive), in path order."""

    def __init__(self, folder: Path, suffixes: Iterable[str] = SUPPORTED_EXTENSIONS) -> None:
        self.folder = Path(folder)
        self.suffixes = {s.lower() for s in suffixes}

    def yield_blobs(self) -> Iterator[Blob]:
        for path in sorted(self.folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in self.suffixes:
                yield Blob.from_path(path)
