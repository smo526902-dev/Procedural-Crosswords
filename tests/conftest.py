import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossword.generate import default_wordlist  # noqa: E402


@pytest.fixture(scope="session")
def wordlist():
    return default_wordlist()
