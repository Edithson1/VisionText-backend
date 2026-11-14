"""Return unused libc heap pages after large inference allocations on Linux."""
import ctypes
import sys

_trim = None
if sys.platform.startswith("linux"):
    try:
        _trim = ctypes.CDLL(None).malloc_trim
        _trim.argtypes = [ctypes.c_size_t]
        _trim.restype = ctypes.c_int
    except AttributeError:
        pass


def release_unused_memory():
    if _trim is not None:
        _trim(0)
