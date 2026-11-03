"""Conservative admission checks, not a guarantee against native allocation failure."""
import ctypes
import os


def available_memory_bytes():
    if os.name == 'nt':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    'total_phys', 'avail_phys', 'total_page', 'avail_page',
                    'total_virtual', 'avail_virtual', 'avail_extended')]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.avail_phys
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError):
        return None


def require_memory(estimated_bytes, action='analyze this image'):
    available = available_memory_bytes()
    if available is not None and estimated_bytes + 256 * 1024**2 > available:
        raise MemoryError(
            f'Not enough available memory to {action}. Close other applications or '
            'crop the source image into smaller images and try again.')
