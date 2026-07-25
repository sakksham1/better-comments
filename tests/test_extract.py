from pathlib import Path

from commenttool.extract import extract_comments
from commenttool.models import AttachmentKind

PY_SOURCE = b'''
# loop through users
for user in users:
    process(user)

x = 5  # cap retries externally

def f():
    pass
    # trailing internal comment
'''


def test_leading_attachment():
    comments = extract_comments(Path("sample.py"), PY_SOURCE)
    leading = [c for c in comments if c.attachment == AttachmentKind.LEADING]
    assert any("loop through users" in c.text for c in leading)


def test_trailing_attachment():
    comments = extract_comments(Path("sample.py"), PY_SOURCE)
    trailing = [c for c in comments if c.attachment == AttachmentKind.TRAILING]
    assert any("cap retries externally" in c.text for c in trailing)


def test_unsupported_extension_returns_empty():
    assert extract_comments(Path("sample.unknown"), b"whatever") == []
