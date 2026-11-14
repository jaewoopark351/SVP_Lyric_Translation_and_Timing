"""Chunked acoustic inference and CTC word/character span decoding."""

import gc

from .model_catalog import ENGLISH_MODELS
from .waveform import FRAME_CENTER, FRAME_SAMPLES, MODEL_RATE, RECEPTIVE_SAMPLES


CHUNK_FRAMES = 650
CONTEXT_FRAMES = 150


def infer_emissions(audio, model_id, model_path, progress):
    import numpy as np
    import torch
    import torchaudio

    bundle = getattr(torchaudio.pipelines, model_id)
    options = {} if model_id in ENGLISH_MODELS else {'with_star': False}
    labels = bundle.get_labels() if model_id in ENGLISH_MODELS else bundle.get_labels(star=None)
    torch.set_num_threads(min(8, max(1, torch.get_num_threads())))
    requested_device = 'cuda:0' if torch.cuda.is_available() else 'cpu'

    def compute(device):
        model = None
        try:
            progress('음성 정렬 모델 읽기 · ' + device, 0.22)
            model = bundle.get_model(dl_kwargs={'model_dir': str(model_path.parent), 'progress': False}, **options)
            model = model.to(device).eval()
            frame_count = 1 + (len(audio) - RECEPTIVE_SAMPLES) // FRAME_SAMPLES
            segments = []
            with torch.inference_mode():
                for start in range(0, frame_count, CHUNK_FRAMES):
                    stop = min(frame_count, start + CHUNK_FRAMES)
                    first = max(0, start - CONTEXT_FRAMES)
                    last = min(frame_count, stop + CONTEXT_FRAMES)
                    signal = torch.from_numpy(audio[first * FRAME_SAMPLES:
                        (last - 1) * FRAME_SAMPLES + RECEPTIVE_SAMPLES]).unsqueeze(0)
                    emission, _ = model(signal.to(device))
                    if emission.shape[1] != last - first:
                        raise ValueError('음성 모델의 시간 프레임 간격이 예상과 다릅니다.')
                    segments.append(emission[0, start - first:stop - first].log_softmax(dim=-1).cpu().numpy())
                    progress(f'새 음성 관측 계산 {stop}/{frame_count} 프레임 · {device}',
                             0.25 + 0.6 * stop / frame_count)
            return np.concatenate(segments), labels, device
        finally:
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    try:
        return compute(requested_device)
    except torch.cuda.OutOfMemoryError:
        if requested_device == 'cpu':
            raise
        progress('GPU 메모리가 부족하여 CPU로 다시 계산합니다.', 0.22)
        gc.collect()
        torch.cuda.empty_cache()
        return compute('cpu')


def decode_words(posterior, labels, words, model_id, duration):
    """Align supported normalized text while keeping unsupported tokens in place."""
    import numpy as np
    import torch
    import torchaudio

    dictionary = {label: index for index, label in enumerate(labels)}
    target, word_targets = [], []
    for word in words:
        text = word['normalized'].upper() if model_id in ENGLISH_MODELS else word['normalized']
        if not text:
            word_targets.append(None)
            continue
        if target and '|' in dictionary:
            target.append(dictionary['|'])
        start = len(target)
        try:
            target.extend(dictionary[character] for character in text)
        except KeyError as error:
            raise ValueError('정규화된 가사에 모델이 지원하지 않는 문자가 있습니다.') from error
        word_targets.append((start, len(target)))
    required = len(target) + sum(left == right for left, right in zip(target, target[1:]))
    if len(posterior) < required:
        raise ValueError('WAV 길이에 비해 가사 문자가 너무 많아 정렬할 수 없습니다.')
    emission = torch.from_numpy(np.asarray(posterior, dtype=np.float32)).unsqueeze(0)
    transcript = torch.tensor(target, dtype=torch.int64).unsqueeze(0)
    path, scores = torchaudio.functional.forced_align(emission, transcript, blank=0)
    spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp(), blank=0)
    if [span.token for span in spans] != target:
        raise ValueError('CTC 정렬 결과가 입력 가사 문자 순서를 보존하지 않습니다.')
    aligned = []
    for word, indices in zip(words, word_targets):
        if indices is None:
            aligned.append({**word, 'start': None, 'end': None, 'p': 0.0, 'chars': []})
            continue
        chars = [{'char': labels[span.token].lower(), 'label': labels[span.token].lower(),
                  'start': round(min(duration, (span.start * FRAME_SAMPLES + FRAME_CENTER) / MODEL_RATE), 5),
                  'end': round(min(duration, (span.end * FRAME_SAMPLES + FRAME_CENTER) / MODEL_RATE), 5),
                  'p': round(float(span.score), 6)} for span in spans[indices[0]:indices[1]]]
        aligned.append({**word, 'start': chars[0]['start'], 'end': chars[-1]['end'],
                        'p': round(float(np.mean([char['p'] for char in chars])), 6), 'chars': chars})
    return aligned
