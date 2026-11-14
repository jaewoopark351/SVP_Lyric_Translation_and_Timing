"""Validated Counting Stars input profile and song-specific alignment policy."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
PROJECT = 'OneRepublic - Counting Stars 여자 커버.svp'
TARGET = 'OneRepublic - Counting Stars 여자 커버_TIMING_FIXED.svp'
NOTES = 'Counting Stars - Note comparison.csv'
LYRICS = 'Counting Stars - Lyric verification.csv'
REPORT = 'Counting Stars - Verification.md'
LEGACY_INPUT_NAMES = (PROJECT, 'OneRepublic - Counting Stars.txt',
                      '1_OneRepublic - Counting Stars_(Vocals).wav')
CONTRACT_INPUT_NAMES = ('OneRepublic - Counting Stars 여자 커버(1).svp',
                        'OneRepublic - Counting Stars(1).txt',
                        '1_OneRepublic - Counting Stars_(Vocals)(1).wav')
SOURCE_HASHES = (
    '5a5a89cf05140ad42f39aaaa1837bd4fee634b5a1f1ca6559394e2d761f8c82a',
    '077027714e053f328a86c41ef481441bf8c613486508a4a1b2f0d351607bb366',
    'f17de82652e85baaf7a7ac08d774c8dbcdc7fcc692d207e0c99e94e7ce986456',
)

EVIDENCE_HASHES = {
    'work/acoustic/en_ctc_words.json': '1617aa87be4b284fcec9f1232ea63652252234d1d71c363d9a290ed3d4b44e89',
    'work/acoustic/mms_ctc_words.json': '7985a8f2558083bad528bc422e39a1784e0ea33ac2bb3b27bf5bae375cb63112',
    'work/pitch/pitch_boundary_candidates.csv': '43372e398d9676affaa32317a596d38cb04f94200cc93f6953e440cd06bd690b',
    'work/pitch/source_frames.csv': '5bd33339635d8de6d4aeadde2de6f21484321d35d9edb78a3071c64e7a514b6d',
}
EXPECTED_NOTE_COUNT = 715
EXPECTED_WORD_COUNT = 527
EXPECTED_LINE_COUNT = 81
EXPECTED_DURATION = 262.56
EXPECTED_BPM = 120
EXPECTED_SAMPLE_RATE = 44100
EXPECTED_CHANNELS = 2


def default_input_paths(folder=SOURCE):
    """Prefer existing contract names; contents still require explicit hash validation."""
    folder = Path(folder)
    return tuple(folder / (current if (folder / current).is_file() else legacy)
                 for current, legacy in zip(CONTRACT_INPUT_NAMES, LEGACY_INPUT_NAMES))


# Original spelling is carried separately. These splits index the grapheme
# evidence and describe the expected sung syllables for this song.
MULTISYLLABLE = {
    'about': ('a', 'bout'), 'across': ('a', 'cross'), 'alive': ('a', 'live'),
    'baby': ('ba', 'by'), "couldn't": ('could', "n't"), 'counting': ('count', 'ing'),
    'doing': ('do', 'ing'), 'dollars': ('dol', 'lars'), 'dreaming': ('dream', 'ing'),
    'every': ('ev', 'ery'), 'everything': ('ev', 'ery', 'thing'),
    'faces': ('fa', 'ces'), 'flashing': ('flash', 'ing'), 'lately': ('late', 'ly'),
    'lessons': ('les', 'sons'), 'letter': ('let', 'ter'), 'losing': ('los', 'ing'),
    'money': ('mon', 'ey'), 'morecounting': ('more', 'count', 'ing'),
    "prayin'": ('pray', "in'"), 'river': ('riv', 'er'),
    'something': ('some', 'thing'), 'swinging': ('swing', 'ing'), 'wanna': ('wan', 'na'),
}

NUCLEUS = {'ery': 'y', 'late': 'a', 'dream': 'e', 'we\'ll': 'e',
           'been': 'e', 'sleep': 'e', 'count': 'o', 'bout': 'o', 'could': 'o',
           'couldn\'t': 'o', "n't": 'n', 'money': 'o', 'more': 'o', 'ey': 'e',
           'pray': 'a', 'you': 'o', 'alive': 'i', 'learned': 'e'}

# Same lead performance sampled in multiple choruses, measured from the WAV.
REPEATS = ((22, 44, 64), (27, 49, 69))
REPEAT_OFFSETS = {22: 0, 44: 70.82038, 64: 128.85387,
                  27: 0, 49: 70.82063, 69: 128.85400}


# First existing note of each TXT line, located from the CTC, WAV and score.
# Values here are 1-based and match the comparison table.
LINE_STARTS = (
    1, 11, 22, 34, 42, 47, 54, 63, 70, 77, 85, 92, 98, 105, 114, 125, 131,
    145, 152, 163, 170, 176, 186, 196, 208, 215, 220, 232, 244, 254, 261,
    274, 283, 290, 297, 304, 310, 316, 324, 334, 348, 355, 367, 378, 387,
    397, 406, 413, 418, 430, 442, 455, 462, 475, 483, 492, 500, 509, 517,
    526, 535, 543, 551, 556, 567, 578, 586, 593, 598, 608, 620, 631, 638,
    645, 653, 663, 671, 680, 688, 699, 707, 716,
)

# Bounds for notes with pitched fills before the next TXT line.
LINE_STOPS = {31: 270, 53: 471}

# Voice evidence in these words/syllables supersedes a forced grapheme start
# that arrives mid-vowel, jumps to the tail of a hold, or tracks another layer.
# Map (line, word, syllable, occurrence) to its first existing note.
LANDMARKS = {
    (1, 'I', 0, 0): 3, (1, 'been', 0, 0): 4, (1, 'I', 0, 1): 6,
    (2, 'be', 0, 0): 21,
    (3, 'baby', 0, 0): 23, (3, 'baby', 1, 0): 24, (3, 'I', 0, 0): 26,
    (6, 'stars', 0, 0): 52,
    (10, 'it', 0, 0): 79, (10, 'out', 0, 0): 79,
    (13, 'And', 0, 0): 98, (13, 'I', 0, 0): 98, (13, "don't", 0, 0): 99,
    (15, 'I', 0, 0): 114, (15, 'feel', 0, 0): 119, (15, 'something', 0, 0): 121,
    (17, 'I', 0, 0): 132, (17, 'feel', 0, 0): 139, (17, 'something', 0, 0): 140,
    (18, 'At', 0, 0): 145, (18, 'doing', 0, 0): 145, (18, 'doing', 1, 0): 146,
    (20, 'Everything', 0, 0): 163, (20, 'Everything', 1, 0): 164,
    (20, 'Everything', 2, 0): 165, (22, 'Lately', 1, 0): 178,
    (27, 'Lately', 1, 0): 222, (27, 'I', 0, 0): 223,
    (28, 'about', 0, 0): 234, (28, 'about', 1, 0): 235,
    (32, 'And', 0, 0): 279, (32, 'I', 0, 1): 279, (32, 'feel', 0, 1): 280,
    (32, 'it', 0, 0): 280,
    (38, 'And', 0, 0): 316, (38, 'I', 0, 0): 316,
    (40, 'And', 0, 0): 334, (40, 'I', 0, 0): 335, (40, 'feel', 0, 0): 342,
    (40, 'something', 0, 0): 343,
    (41, 'At', 0, 0): 348, (41, 'doing', 0, 0): 348, (41, 'doing', 1, 0): 349,
    (43, 'Everything', 0, 0): 367, (43, 'Everything', 1, 0): 368,
    (43, 'Everything', 2, 0): 369,
    (44, 'Lately', 1, 0): 379, (44, 'I', 0, 0): 380,
    (45, 'about', 0, 0): 389, (45, 'about', 1, 0): 389,
    (46, 'baby', 0, 0): 397,
    (46, 'baby', 1, 0): 398, (46, 'I', 0, 0): 399,
    (49, 'Lately', 0, 0): 418, (49, 'Lately', 1, 0): 420, (49, 'I', 0, 0): 421,
    (49, 'losing', 1, 0): 427, (49, 'sleep', 0, 0): 428,
    (50, 'about', 0, 0): 432, (50, 'about', 1, 0): 433,
    (61, 'lessons', 1, 0): 540, (61, 'I', 0, 0): 541,
    (62, 'Everything', 0, 0): 543, (62, 'Everything', 1, 0): 544,
    (62, 'Everything', 2, 0): 545, (62, 'me', 0, 0): 548,
    (64, 'Lately', 0, 0): 556, (64, 'Lately', 1, 0): 557, (64, 'I', 0, 0): 559,
    (65, 'about', 0, 0): 569, (65, 'about', 1, 0): 569,
    (66, 'baby', 0, 0): 578,
    (66, 'baby', 1, 0): 579, (66, 'I', 0, 0): 580,
    (69, 'Lately', 1, 0): 599, (69, 'I', 0, 0): 600,
    (70, 'about', 0, 0): 610, (70, 'about', 1, 0): 611,
    (73, "we'll", 0, 1): 641, (73, 'counting', 0, 0): 643,
    (73, 'counting', 1, 0): 643, (73, 'stars', 0, 0): 644,
}

UNPLACED = {
    (36, 'but'): (125.798, 125.925, '1절 반복의 동일 파형과 MIDI 56 유성음이 있으나 2절 원본은 해당 시간에 음표가 없음'),
    (37, 'but'): (127.778, 127.905, '1절 반복의 동일 파형과 MIDI 56 유성음이 있으나 2절 원본은 해당 시간에 음표가 없음'),
    (46, 'But'): (156.245, 156.340, '대응 후렴에서 예상되는 시각의 에너지가 낮고 유성 피치와 독립 음표가 없음'),
    (54, 'And'): (184.85, 184.93, '독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지'),
    (56, 'And'): (188.77, 188.85, '독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지'),
    (58, 'And'): (192.69, 192.78, '독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지'),
    (60, 'And'): (196.59, 196.69, '독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지'),
    (66, 'But'): (214.270, 214.350, '대응 후렴에서 예상되는 시각의 에너지가 낮고 유성 피치와 독립 음표가 없음'),
    (74, 'And'): (238.89, 239.03, '두 CTC 모델 모두 접속사를 생략한 전사가 더 적합. 아웃트로는 보컬 레이어가 겹침'),
    (76, 'And'): (242.81, 242.95, '두 CTC 모델 모두 접속사를 생략한 전사가 더 적합. 아웃트로는 보컬 레이어가 겹침'),
    (78, 'And'): (246.75, 246.89, '두 CTC 모델 모두 접속사를 생략한 전사가 더 적합. 아웃트로는 보컬 레이어가 겹침'),
    (80, 'And'): (250.59, 250.82, '독립 인식은 엇갈리며 두 CTC 모델 모두 접속사를 생략한 전사가 더 적합'),
}

UNPLACED_NOTES = {131: 'TXT 밖의 And 후보. +70.8205초 반복 파형 및 독립 인식으로 확인',
                  207: 'hard와 455 ms 떨어져 있고 Said 자음/모음과의 연결 근거 부족',
                  **dict.fromkeys(range(270, 274), 'TXT 밖의 Hey 계열 유성 발음 후보'),
                  **dict.fromkeys(range(471, 475), 'TXT 밖의 Oh 계열 유성 발음 후보')}

REVIEW_NOTES = {
    36: 'TXT의 결합 철자 morecounting 보존. 음절 후보 more/count/ing, 실제 합성 발음 미확인',
    72: 'faces와 face is는 음원에서 경계가 비슷함. TXT 철자 유지',
    114: '54.72–56.72초의 긴 I 후보. 국소 Whisper 및 feel 자음 직전 파형과 일치하나 I의 시작은 미확정',
    125: 'TXT At 유지. 독립 인식은 but/by 등으로 엇갈림',
    132: '앞 And 후보 이후 긴 I의 유성 지속, 자음·모음의 경계 미확정',
    145: 'TXT At 유지. 동일 반복의 독립 인식과 가사 경계가 엇갈림',
    335: '긴 I의 유성 지속, 자음·모음의 경계 미확정',
    348: 'TXT At 유지. 동일 반복의 독립 인식과 가사 경계가 엇갈림',
    644: '별도 stars 시작 237.95–238.09초 후보, 같은 피치에서 다음 구절과 겹침',
}


# Measured waveform boundaries that warrant overriding a grapheme model's
# timing. Note numbers are the 1-based ordinals in the original note group.
ONSET_LANDMARKS = {1: (.455, '두 WAV의 첫 가사 자음 L과 파형, 유성 전조는 약 0.373초'),
                   22: (9.225, 'But 유성 피치/에너지 상승. 앞 음표와 기존 피치 순서 유지'),
                   234: (98.240, '약 98.24초 피치 진입, 98.36초 에너지 상승은 후속 발음 후보'),
                   280: (118.165, 'feel의 안정 MIDI 56 진입, 두 CTC의 F는 118.11–118.13초')}
END_LANDMARKS = {22: (9.405, 'But의 모음 뒤 감쇠와 baby 전 구간의 파형'),
                 53: (22.760, '첫 구간 stars의 마지막 유성 프레임'),
                 550: (204.100, 'me 멜리스마 종료와 쉼'),
                 715: (253.910, '마지막 learned의 강한 유성음 종료')}


CHORUS_RANGES = ((1, 6), (22, 26), (27, 31), (44, 48), (49, 53), (64, 68), (69, 73))
LARGE_ERROR_MS = 100
