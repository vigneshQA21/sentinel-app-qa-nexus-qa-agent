import os

os.environ["NEXUS_NO_SEND_GATE"] = "1"      # the cross-process send gate must not wait or touch state/ in tests
