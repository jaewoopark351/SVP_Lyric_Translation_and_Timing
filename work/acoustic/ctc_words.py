import argparse
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
import torch
import torchaudio


ROOT = Path(__file__).resolve().parent
SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
WAV = SOURCE / '1_OneRepublic - Counting Stars_(Vocals).wav'
TXT = SOURCE / 'OneRepublic - Counting Stars.txt'
MODEL_RATE = 16000
FRAME_SAMPLES = 320
FRAME_CENTER = 200


def read_words():
    return [
        {'line': line_no, 'column': match.start() + 1, 'source': match.group()}
        for line_no, line in enumerate(TXT.read_text(encoding='utf-8-sig').splitlines(), 1)
        for match in re.finditer(r"[A-Za-z']+", line)
    ]


def inference(bundle, model_name, wave, stem):
    labels = bundle.get_labels(star=None) if model_name == 'mms' else bundle.get_labels()
    cache = ROOT / f'{stem}_emissions.npy'
    if cache.is_file():
        return np.load(cache), labels
    audio, sr = sf.read(wave, dtype='float32', always_2d=True)
    audio = resample_poly(audio.mean(axis=1), MODEL_RATE, sr)
    device = 'cuda:0'
    options = {'with_star': False} if model_name == 'mms' else {}
    model = bundle.get_model(**options).to(device).eval()
    frame_count = 1 + (len(audio) - 400) // FRAME_SAMPLES
    segments = []
    with torch.inference_mode():
        for start in range(0, frame_count, 650):
            stop = min(frame_count, start + 650)
            first = max(0, start - 150)
            last = min(frame_count, stop + 150)
            signal = torch.from_numpy(audio[first * FRAME_SAMPLES:(last - 1) * FRAME_SAMPLES + 400])
            emission, _ = model(signal.unsqueeze(0).to(device))
            assert emission.shape[1] == last - first
            segments.append(emission[0, start - first:stop - first].log_softmax(dim=-1).cpu().numpy())
            print(f'{model_name} emissions {stop}/{frame_count}', flush=True)
    posterior = np.concatenate(segments)
    np.save(cache, posterior)
    return posterior, labels


def align(posterior, labels, model_name, stem):
    words = read_words()
    label_ids = {symbol: index for index, symbol in enumerate(labels)}
    target = []
    word_targets = []
    for word in words:
        if target and '|' in label_ids:
            target.append(label_ids['|'])
        text = word['source'].upper() if model_name == 'en' else word['source'].lower()
        begin = len(target)
        target.extend(label_ids[c] for c in text)
        word_targets.append((begin, len(target)))
    emission = torch.from_numpy(posterior).unsqueeze(0)
    transcript = torch.tensor(target).unsqueeze(0)
    path, scores = torchaudio.functional.forced_align(emission, transcript, blank=0)
    spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp(), blank=0)
    assert [span.token for span in spans] == target
    for word, (begin, stop) in zip(words, word_targets):
        chars = [
            {
                'label': labels[span.token],
                'start': round((span.start * FRAME_SAMPLES + FRAME_CENTER) / MODEL_RATE, 4),
                'end': round((span.end * FRAME_SAMPLES + FRAME_CENTER) / MODEL_RATE, 4),
                'p': round(span.score, 4),
            }
            for span in spans[begin:stop]
        ]
        word.update(start=chars[0]['start'], end=chars[-1]['end'], p=round(float(np.mean([c['p'] for c in chars])), 4), chars=chars)
    (ROOT / f'{stem}_ctc_words.json').write_text(json.dumps(words, indent=2), encoding='utf-8')
    print(f'{model_name} alignment completed: {len(words)} words, mean p={np.mean([word["p"] for word in words]):.3f}', flush=True)
    for line in range(1, words[-1]['line'] + 1):
        group = [word for word in words if word['line'] == line]
        if group:
            print(f'{line:3} {group[0]["start"]:7.2f} {group[-1]["end"]:7.2f} {np.mean([word["p"] for word in group]):.2f}  {" ".join(word["source"] for word in group)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('model', choices=('en', 'mms'))
    parser.add_argument('--project-audio', action='store_true')
    args = parser.parse_args()
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H if args.model == 'en' else torchaudio.pipelines.MMS_FA
    wave = next(SOURCE.glob('*_(No Reverb).wav')) if args.project_audio else WAV
    stem = f'{args.model}_project' if args.project_audio else args.model
    posterior, labels = inference(bundle, args.model, wave, stem)
    align(posterior, labels, args.model, stem)
