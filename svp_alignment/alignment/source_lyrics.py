"""Read immutable lyric text and preserve each token's source position."""

import unicodedata
from pathlib import Path


def _token_spans(text):
    index = 0
    while index < len(text):
        if not text[index].isalnum():
            index += 1
            continue
        start = index
        index += 1
        while index < len(text):
            char = text[index]
            if char.isalnum() or unicodedata.category(char).startswith('M'):
                index += 1
            elif char in "'’-‐‑" and index + 1 < len(text) and text[index + 1].isalnum():
                index += 1
            else:
                break
        yield start, text[start:index]


def parse_words(text):
    words = []
    for line, source in enumerate(text.splitlines(), 1):
        for start, token in _token_spans(source):
            words.append(dict(word_index=len(words), line=line,
                              column=start + 1, source=token))
    if not words:
        raise ValueError('TXT에서 배치할 가사 단어를 찾을 수 없습니다.')
    return words


def read_words(path):
    """Read UTF-8 or Korean Windows TXT without changing the original file."""
    data = Path(path).read_bytes()
    encodings = ('utf-16',) if data.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'cp949')
    for encoding in encodings:
        try:
            return parse_words(data.decode(encoding))
        except UnicodeError:
            continue
    raise ValueError('TXT 인코딩을 읽을 수 없습니다. UTF-8 TXT를 사용하세요.')
