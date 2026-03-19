import sys
print("sys information:")
print(sys.version)        # full version string, e.g. "3.11.4 (main, …)"
print(sys.version_info)   # a tuple-like object, e.g. (3, 11, 4, 'final', 0)
print(sys.executable)

# or check for a minimum version
if sys.version_info < (3, 8):
    raise RuntimeError("Python 3.8 or newer is required")

# alternatively:
import platform
print("\nplatform information:")
print(platform.python_version())      # e.g. "3.11.4"import sys

print("\npython executable:", sys.executable)      # e.g. /usr/bin/python3
print("\nsys.path list:", sys.path)               # module search paths

import yfinance as yf

print("\nyfinance version:", yf.__version__)