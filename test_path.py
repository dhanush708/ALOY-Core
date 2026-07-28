import sys
import importlib.metadata
print("sys._MEIPASS:", getattr(sys, '_MEIPASS', 'Not found'))
print("sys.path:", sys.path)
try:
    print("email-validator version:", importlib.metadata.version('email-validator'))
except Exception as e:
    print("Error:", repr(e))
