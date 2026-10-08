import os

# No background noise in tests: its random errors would make them flaky.
os.environ["BACKGROUND_NOISE"] = "off"
