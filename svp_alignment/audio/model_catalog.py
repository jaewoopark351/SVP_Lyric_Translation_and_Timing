"""Lightweight acoustic model identities and explicit selection policy."""

ENGLISH_MODEL = 'WAV2VEC2_ASR_BASE_960H'
LARGE_ENGLISH_MODEL = 'WAV2VEC2_ASR_LARGE_LV60K_960H'
MULTILINGUAL_MODEL = 'MMS_FA'
QWEN_MODEL = 'Qwen/Qwen3-ForcedAligner-0.6B'
HEAVY_MODEL = 'Qwen/Qwen3-ASR-1.7B+ForcedAligner-0.6B'
CACHED_MODEL_CHOICE = 'cached_counting_stars'
DEFAULT_MODEL_CHOICE = 'auto'
MODEL_CHOICES = [
    ('자동 · 영어 Large / 지원 언어 Qwen', DEFAULT_MODEL_CHOICE),
    ('Wav2Vec2 Large LV60K · 영어', LARGE_ENGLISH_MODEL),
    ('Qwen3 ForcedAligner 0.6B · 다국어', QWEN_MODEL),
    ('Qwen3 ASR 1.7B + ForcedAligner 0.6B · 인식 대조', HEAVY_MODEL),
    ('MMS FA · 다국어', MULTILINGUAL_MODEL),
    ('Wav2Vec2 Base · 영어', ENGLISH_MODEL),
    ('Counting Stars 기존 분석 자료', CACHED_MODEL_CHOICE),
]
MODEL_IDS = frozenset((ENGLISH_MODEL, LARGE_ENGLISH_MODEL, MULTILINGUAL_MODEL, QWEN_MODEL, HEAVY_MODEL))
ENGLISH_MODELS = frozenset((ENGLISH_MODEL, LARGE_ENGLISH_MODEL))
WORD_OBSERVATION_MODELS = frozenset((QWEN_MODEL, HEAVY_MODEL))
QWEN_LANGUAGES = {
    'eng': 'English', 'kor': 'Korean', 'jpn': 'Japanese', 'zho': 'Chinese',
    'fra': 'French', 'deu': 'German', 'spa': 'Spanish', 'rus': 'Russian',
    'ita': 'Italian', 'por': 'Portuguese', 'yue': 'Cantonese',
}
_ALIASES = {'en': 'eng', 'english': 'eng', 'ko': 'kor', 'korean': 'kor',
            'ja': 'jpn', 'japanese': 'jpn', 'zh': 'zho', 'chinese': 'zho',
            'fr': 'fra', 'french': 'fra', 'de': 'deu', 'german': 'deu',
            'es': 'spa', 'spanish': 'spa', 'ru': 'rus', 'russian': 'rus',
            'it': 'ita', 'italian': 'ita', 'pt': 'por', 'portuguese': 'por',
            'cantonese': 'yue'}


def language_code(language):
    language = str(language or 'auto').strip().lower()
    return _ALIASES.get(language, language)


def ascii_lyrics(words):
    return all(character.isascii() for word in words for character in word['source']
               if character.isalpha())


def resolve_model(words, language='auto', model_choice=DEFAULT_MODEL_CHOICE):
    language = language_code(language)
    choice = str(model_choice or DEFAULT_MODEL_CHOICE)
    if choice == CACHED_MODEL_CHOICE:
        raise ValueError('Counting Stars 기존 자료는 음성 모델로 실행할 수 없습니다.')
    if choice == DEFAULT_MODEL_CHOICE:
        if language == 'eng' or (language == 'auto' and ascii_lyrics(words)):
            return LARGE_ENGLISH_MODEL
        return QWEN_MODEL if language in QWEN_LANGUAGES else MULTILINGUAL_MODEL
    if choice not in MODEL_IDS:
        raise ValueError('지원하지 않는 음성 정렬 모델입니다.')
    if choice in ENGLISH_MODELS and language not in ('auto', 'eng'):
        raise ValueError('Wav2Vec2 영어 모델은 영어 가사에 사용하세요. 다국어 모델을 선택할 수 있습니다.')
    if choice in WORD_OBSERVATION_MODELS:
        qwen_language(words, language)
    return choice


def qwen_language(words, language):
    code = language_code(language)
    if code == 'auto' and ascii_lyrics(words):
        code = 'eng'
    if code not in QWEN_LANGUAGES:
        raise ValueError('Qwen 모델은 지원하는 가사 언어를 명시해서 선택하세요. 기타 언어는 MMS FA를 사용하세요.')
    return QWEN_LANGUAGES[code]


def saved_model_choice(summary, provenance=None):
    """Restore old jobs without silently recomputing them with a new default."""
    summary = summary or {}
    explicit = summary.get('model_choice')
    if explicit in MODEL_IDS or explicit in (DEFAULT_MODEL_CHOICE, CACHED_MODEL_CHOICE):
        return explicit
    if summary.get('mode', 'counting_stars') == 'counting_stars':
        return CACHED_MODEL_CHOICE
    model_id = (provenance or {}).get('model_id') or summary.get('model_id')
    if model_id in MODEL_IDS:
        return model_id
    return (DEFAULT_MODEL_CHOICE if language_code(summary.get('language')) in ('auto', 'eng')
            else MULTILINGUAL_MODEL)
