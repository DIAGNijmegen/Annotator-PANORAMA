from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import List, Dict

import numpy as np

from .dataloader import DataLoader
from .sequence import Sequence, SequenceCollection


class Sequencer:
    def __init__(self, dataloader: DataLoader):
        self._dataloader = dataloader

    @staticmethod
    def _len_of_values(obj: dict):
        return sum([len(x) for x in obj.values()])

    def generate_sequences(self, *, seed: int = -1, seq_len: int = 15, mean_slices_per_mha: float = 2,
                           max_slices_per_mha: int = 3, q: float = 0.5) -> SequenceCollection:
        """
        Every MHA slice within a case has a 'usefulness' score, calculated as 1/2^x, where is the number of steps away
        from the center slice. For each MHA slice, a sequence takes 1 to (max_slices_per_mha)
        Parameters
        ----------
        seed:
            Seed to use for entire sequence generation
        seq_len: int=15
            Length of sequence
        mean_slices_per_mha: float
            Mean number of slices to take for each .mha
        max_slices_per_mha: int
            Max number of slices to take for each .mha
        q: float=1.75/3
            Quality preference. (0 <= q <= 1)
            Higher means fewer sequences per case, with each sequence containing primarily center slices.
            Lower means more sequences per case, with each sequence containing primarily edge slices.
        """
        q = np.clip(q, 0, 1) * seq_len
        seeds = {case: seed + s for s, case in enumerate(self._dataloader.keys())}

        def _generate_sequences(case: str) -> List[Sequence]:
            r = np.random.default_rng(seeds[case] if seed >= 0 else None)
            sequences: List[Sequence] = []
            shapes = self._dataloader.shapes(case)
            available = {m: list(range(shapes[m][0])) for m in range(len(shapes))}
            slices = {m: np.array(available[m]) for m in range(len(shapes))}

            while True:
                sequence_candidates: list = []

                # is it impossible to make a full sequence, given the number of available slices?
                if self._len_of_values(available) < seq_len:
                    break

                # generate 100 sequence candidates
                for _ in range(100):
                    c_quality = 0
                    c_sequence = {}
                    c_available = deepcopy(available)

                    # while our candidate sequence is not a full sequence of length seq_len
                    m, loop = 0, 0
                    while (c_sequence_len := self._len_of_values(c_sequence)) < seq_len:
                        m_available_slices = len(c_available[m])
                        if m_available_slices > 0:
                            # we take n_slices, normally distributed around mean_slices_per_mha
                            max_n_slices = min(m_available_slices, max_slices_per_mha, seq_len - c_sequence_len)
                            n_slices = int(np.clip(np.round(r.normal(loc=mean_slices_per_mha)), 0, max_n_slices))

                            # quality of a slice is 1/2^x, where x is x steps away from center
                            m_quality = 1 / np.power(2, np.abs(slices[m] - 2))

                            # probability distribution are 1 unless..
                            m_p = np.ones(slices[m].shape)
                            if n_slices == 1:
                                # greatly increase chance of taking a center slice if only taking one
                                m_p = m_quality
                            m_p *= [(x in c_available[m]) for x in slices[m]]

                            selected_slices = r.choice(slices[m], size=int(n_slices), replace=False, p=m_p / m_p.sum())

                            c_quality += m_quality[selected_slices].sum()
                            id = f'{loop}_{m}'
                            c_sequence[id] = c_sequence.get(id, []) + selected_slices.tolist()
                            [c_available[m].remove(s) for s in selected_slices]

                        m = (m + 1) % len(c_available)
                        if m == 0:
                            loop += 1

                    assert self._len_of_values(c_sequence) == seq_len, \
                        SystemError(f'FATAL: length of candidate ({len(c_sequence)}) != seq_len ({seq_len})')
                    sequence_candidates.append((c_quality, Sequence(case, c_sequence), c_available))

                # select candidate closest to quality preference 'q'
                sequence_candidates.sort(key=lambda c: np.abs(q - c[0]))
                c_quality, c_sequence, c_available = sequence_candidates[0]
                if c_quality < q:
                    break
                else:
                    sequences.append(c_sequence)
                    available = c_available
            return sequences

        sequence_collection: Dict[str, List[Sequence]] = {}
        with ThreadPoolExecutor() as pool:
            futures = {pool.submit(_generate_sequences, key): key for key in self._dataloader.keys()}
            for future in as_completed(futures):
                key = futures[future]
                sequence_collection[key] = future.result()

        return SequenceCollection(sequence_collection)
