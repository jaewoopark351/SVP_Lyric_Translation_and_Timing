"""Keep original lyric tokens while preparing model-supported alignment text."""

import re
import unicodedata

from .model_catalog import ENGLISH_MODEL, MULTILINGUAL_MODEL, QWEN_MODEL, WORD_OBSERVATION_MODELS, resolve_model
_QUOTES = str.maketrans({'’': "'", '‘': "'", 'ʼ': "'", '＇': "'"})


def copy_words(words):
    if isinstance(words, (str, bytes)):
        raise ValueError('가사 단어 목록이 필요합니다.')
    result = []
    for index, word in enumerate(words):
        word = {'source': word} if isinstance(word, str) else dict(word)
        if not isinstance(word.get('source'), str):
            raise ValueError('각 가사 단어에는 원문 source 문자열이 필요합니다.')
        result.append({**word, 'word_index': index})
    if not result:
        raise ValueError('정렬할 가사 단어가 없습니다.')
    return result


def select_model(words, language='auto', model_choice='auto'):
    return resolve_model(words, language, model_choice)


def clean_qwen_token(text):
    text = unicodedata.normalize('NFKC', text).translate(_QUOTES)
    return ''.join(character for character in text if character.isalnum() or character == "'").lower().strip("'")


def normalize_words(words, model_id, language='auto'):
    """Return original tokens plus explicit normalization/unsupported reasons."""
    words = copy_words(words)
    romanizer = None
    if model_id == MULTILINGUAL_MODEL:
        try:
            from uroman import Uroman
        except ImportError as error:
            raise RuntimeError('다국어 음성 정렬에는 uroman 패키지가 필요합니다.') from error
        romanizer = Uroman()
    normalized = []
    for word in words:
        text = unicodedata.normalize('NFKC', word['source']).translate(_QUOTES)
        if model_id in WORD_OBSERVATION_MODELS:
            text = clean_qwen_token(text)
            reason = '' if any(character.isalpha() for character in text) else '숫자·기호만 있는 토큰은 발음을 확정할 수 없습니다.'
            normalized.append({**word, 'normalized': '' if reason else text,
                               'status': 'UNKNOWN' if reason else 'AUTO', 'reason': reason})
            continue
        if romanizer is not None:
            options = {} if language in ('auto', None, '') else {'lcode': language}
            text = romanizer.romanize_string(text, **options)
        unsupported = any(character.isalpha() and not character.isascii() for character in text)
        text = re.sub("[^a-z']", '', text.lower()).strip("'")
        reason = ('모델 문자로 변환할 수 없는 원문 토큰입니다.' if unsupported else
                  '숫자·기호만 있는 토큰은 발음을 확정할 수 없습니다.' if not text else '')
        normalized.append({**word, 'normalized': '' if reason else text,
                           'status': 'UNKNOWN' if reason else 'AUTO', 'reason': reason})
    if not any(word['normalized'] for word in normalized):
        raise ValueError('음성 정렬 모델이 읽을 수 있는 가사 단어가 없습니다.')
    return normalized
