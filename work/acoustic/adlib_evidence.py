from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf
import torch
import torchaudio


ROOT = Path(__file__).resolve().parent
SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
WAV = SOURCE / '1_OneRepublic - Counting Stars_(Vocals).wav'
WINDOWS = (
    (54.22, 58.72, 'i feel something so right', 'and i feel something so right', 'ah i feel something so right'),
    (61.80, 66.65, 'i feel something so wrong', 'and i feel something so wrong', 'i say feel something so wrong'),
    (133.00, 137.44, 'i feel something so wrong', 'and i feel something so wrong'),
    (110.8, 113.9, 'hey', 'yeah', 'ay', 'oh', 'ah', ''),
    (182.55, 184.10, 'hey', 'yeah', 'ay', 'oh', 'ah', ''),
    (199.70, 204.20, 'everything that kills me', 'everything that kills me oh', 'everything that kills me yeah'),
    (202.60, 204.22, 'me', 'hey', 'yeah', 'ay', 'oh', 'ah', ''),
)


def main():
    for name, bundle in [('en', torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H), ('mms', torchaudio.pipelines.MMS_FA)]:
        symbols = bundle.get_labels() if name == 'en' else bundle.get_labels(star=None)
        labels = {s: i for i, s in enumerate(symbols)}
        emission = torch.from_numpy(np.load(ROOT / f'{name}_emissions.npy'))
        criterion = torch.nn.CTCLoss(blank=0, reduction='none')
        print(name)
        for start, stop, *phrases in WINDOWS:
            i = round(start * 50)
            f = emission[i:round(stop * 50)]
            greedy = torch.unique_consecutive(f.argmax(1)).tolist()
            print(f'{start}–{stop}', 'greedy=', ''.join(symbols[k] for k in greedy if k))
            candidates = []
            for phrase in phrases:
                letters = phrase.upper().replace(' ', '|') if name == 'en' else phrase.replace(' ', '')
                target = [labels[letter] for letter in letters]
                score = -criterion(f.unsqueeze(1), torch.tensor([target], dtype=torch.int64), torch.tensor([len(f)]), torch.tensor([len(target)])).item()
                if target:
                    path, scores = torchaudio.functional.forced_align(f.unsqueeze(0), torch.tensor([target]), blank=0)
                    spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp(), blank=0)
                    chars = ' '.join(f'{symbols[span.token]}:{(span.start + i)/50 + 0.0125:.2f}[{span.score:.2f}]' for span in spans)
                else:
                    chars = ''
                candidates.append((score, phrase, chars))
            for score, phrase, chars in sorted(candidates, reverse=True):
                print(f'{score:7.2f} {phrase:<39} {chars}')


if __name__ == '__main__':
    main()
