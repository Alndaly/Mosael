# RNNoise model: somnolent-hogwash

`somnolent-hogwash.rnnn` is the `sh.rnnn` model from
[GregorR/rnnoise-models](https://github.com/GregorR/rnnoise-models/tree/master/somnolent-hogwash-2018-09-01)
(commit on `master`, 2018-09-01), used by ffmpeg's `arnndn` filter.

- **Trained for:** speech in a reasonable recording environment — fans, air conditioning,
  computers. Laughter, coughing and music are treated as noise.
- **Licence:** the repository states that the model files are not creative work and therefore not
  subject to copyright; its tools are BSD-3-Clause, as is RNNoise itself.
- **SHA-256:** `70bb6685eb0c2a1d18e2918dca3fbfbd39317010b1802eb1b6ea73a92f3fdec0`
  (checked by `tests/test_denoise_engines.py`).

Replacing the file means updating the checksum in that test and in
`app/ai/providers/adapters/local/rnnoise_denoise.py`.
