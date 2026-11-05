class LoaderError(Exception):
    """The file cannot be read at all (corrupt, encrypted, unsupported, missing engine)."""
