import json
from pathlib import Path

import soundfile as sf
from scipy.signal import resample_poly
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline


ROOT = Path(__file__).resolve().parent
SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
WAV = SOURCE / '1_OneRepublic - Counting Stars_(Vocals).wav'
MODEL = Path('C:/Users/jaewo/.cache/huggingface/hub/models--openai--whisper-large-v3/snapshots/06f233fe06e710322aca913c1bc4249a0d71fce1')


def main():
    audio, sr = sf.read(WAV, always_2d=True, dtype='float32')
    audio = resample_poly(audio.mean(axis=1), 16000, sr)
    model = AutoModelForSpeechSeq2Seq.from_pretrained(MODEL, torch_dtype=torch.float16, attn_implementation='eager', local_files_only=True).to('cuda:0')
    processor = AutoProcessor.from_pretrained(MODEL, local_files_only=True)
    transcribe = pipeline('automatic-speech-recognition', model=model, tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor, device='cuda:0', torch_dtype=torch.float16, chunk_length_s=26, stride_length_s=4, batch_size=3)
    print('Whisper loaded', flush=True)
    result = transcribe(audio, return_timestamps='word', generate_kwargs={'language': 'en', 'task': 'transcribe', 'num_beams': 1})
    (ROOT / 'whisper_words.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Words:', len(result['chunks']), flush=True)


if __name__ == '__main__':
    main()
