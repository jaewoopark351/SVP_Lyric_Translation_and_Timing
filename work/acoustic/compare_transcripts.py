from pathlib import Path

import numpy as np
import torch
import torchaudio


ROOT = Path(__file__).resolve().parent
WINDOWS = (
    (42.35, 44.43, 'in my faces flashing signs', 'in my face is flashing signs'),
    (58.9, 61.85, 'at doing the wrong thing', 'by doing the wrong thing', 'but doing the wrong thing', 'doing the wrong thing'),
    (66.78, 69.65, 'at doing the right thing', 'but doing the right thing', 'by doing the right thing', 'with doing the right thing', 'doing the right thing'),
    (137.60, 140.47, 'at doing the right thing', 'but doing the right thing', 'by doing the right thing', 'with doing the right thing', 'doing the right thing'),
    (152.60, 155.90, 'dreaming about the things that we could be', 'dreaming bout the things that we could be'),
    (155.80, 159.99, 'but baby i been i been prayin hard', "but baby i've been i've been praying hard", "baby i've been i've been praying hard", "baby i've been i've been prayin hard"),
    (213.89, 218.09, 'but baby i been i been prayin hard', "but baby i've been i've been praying hard", "baby i've been i've been praying hard", "baby i've been i've been prayin hard"),
    (236.06, 238.15, "we'll be we'll be counting stars", "we'll be counting stars", "we'll be we'll be countin stars"),
    *((start, stop, 'take that money and watch it burn', 'take that money watch it burn') for start, stop in ((184.00, 185.80), (187.89, 189.74), (191.82, 193.67), (195.75, 197.60), (238.09, 239.91), (242.00, 243.87), (245.94, 247.80), (249.88, 251.74))),
    *((start, stop, 'sink in the river the lessons i learned', "sink in the river the lessons i've learned", 'sing in the river the lessons i learned', 'sink in the river the lessons learned', 'sink in the river the lessons are learned', 'sink in the river the lessons we learned') for start, stop in ((185.73, 187.90), (189.66, 191.84), (193.64, 195.81), (197.56, 199.79), (239.80, 241.99), (243.80, 245.93), (247.74, 249.90), (251.71, 253.93))),
)


def main():
    criterion = torch.nn.CTCLoss(blank=0, reduction='none')
    for name in ('en', 'mms'):
        if name == 'en':
            symbols = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_labels()
        else:
            symbols = torchaudio.pipelines.MMS_FA.get_labels(star=None)
        labels = {s: i for i, s in enumerate(symbols)}
        emission = torch.from_numpy(np.load(ROOT / f'{name}_emissions.npy')).unsqueeze(1)
        print(name)
        for start, end, *phrases in WINDOWS:
            scores = []
            frames = emission[round(start * 50):round(end * 50)]
            for phrase in phrases:
                normalized = phrase.upper().replace(' ', '|') if name == 'en' else phrase.replace(' ', '')
                target = [labels[character] for character in normalized]
                nll = criterion(frames, torch.tensor([target]), torch.tensor([len(frames)]), torch.tensor([len(target)]))
                scores.append((-round(nll.item(), 1), phrase))
            print(start, end, *sorted(scores, reverse=True), sep='\t')


if __name__ == '__main__':
    main()
