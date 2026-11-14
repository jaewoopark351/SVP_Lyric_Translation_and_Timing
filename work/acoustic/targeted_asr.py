import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

ROOT = Path(__file__).resolve().parent
SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
WAV = SOURCE / '1_OneRepublic - Counting Stars_(Vocals).wav'
MODEL = Path('C:/Users/jaewo/.cache/huggingface/hub/models--openai--whisper-large-v3/snapshots/06f233fe06e710322aca913c1bc4249a0d71fce1')


WINDOWS = [
    (0, 5.15), (8.30, 14.08), (41.9, 44.58),
    (53.9, 56.65), (56.30, 61.95), (61.65, 64.62), (62.0, 69.95), (70.0, 74.0),
    (77.7, 81.60), (93.05, 97.46), (100.7, 105.42), (110.5, 114.32),
    (132.9, 140.65), (140.65, 145.00), (148.6, 152.50),
    (152.45, 156.08), (155.7, 160.30), (163.68, 168.22),
    (171.5, 176.06), (177.90, 181.7), (181.4, 184.0), (183.65, 188.00),
    (187.75, 191.90), (191.75, 195.83), (195.62, 199.89), (199.45, 205.4),
    (206.6, 210.52), (210.50, 213.97), (213.80, 218.28),
    (221.8, 226.33), (229.5, 234.10), (236.05, 238.25),
    (237.98, 242.01), (241.92, 245.93), (245.91, 249.9),
    (249.86, 254.13), (254.15, 262.56),
]


def main():
    audio, sr = sf.read(WAV, always_2d=True, dtype='float32')
    other, other_sr = sf.read(next(SOURCE.glob('*_(No Reverb).wav')), always_2d=True, dtype='float32')
    assert len(audio) == len(other) and sr == other_sr
    waves = {'source': audio.mean(axis=1), 'reference': other.mean(axis=1)}
    model = AutoModelForSpeechSeq2Seq.from_pretrained(MODEL, torch_dtype=torch.float16, attn_implementation='eager', local_files_only=True).to('cuda:0')
    processor = AutoProcessor.from_pretrained(MODEL, local_files_only=True)
    transcribe = pipeline('automatic-speech-recognition', model=model, tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor, device='cuda:0', torch_dtype=torch.float16, batch_size=1)
    outputs = []
    for variant, samples in waves.items():
        for index, window in enumerate(WINDOWS):
            chunk = resample_poly(samples[round(window[0] * sr):round(window[1] * sr)], 16000, sr)
            result = transcribe(chunk, return_timestamps='word', generate_kwargs={'language': 'en', 'task': 'transcribe', 'num_beams': 1, 'max_new_tokens': 45})
            outputs.append({'variant': variant, 'start': window[0], 'end': window[1], **result})
            print(f'{variant:>9} {index:2} {window[0]:6.2f} {window[1]:6.2f} {result["text"]}', flush=True)
            (ROOT / 'targeted_asr.json').write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
