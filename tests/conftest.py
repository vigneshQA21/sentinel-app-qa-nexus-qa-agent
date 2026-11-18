import os; os.environ.setdefault("NEXUS_NO_AUTO_UPLOAD", "1")
import os

os.environ["NEXUS_NO_SEND_GATE"] = "1"      # the cross-process send gate must not wait or touch state/ in tests
