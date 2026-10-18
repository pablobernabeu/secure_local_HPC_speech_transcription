# Curated name dictionary: record and origin

The repository contains [data/curated_names.csv](../data/curated_names.csv),
with the fields `name`, `language` and `type`. Its only file-history entry is
the initial commit, `8d8c58e3814e0a7bc0dee57fe403bc7265e515a6`, authored by
Pablo Bernabeu on 5 November 2025. That commit supplies the CSV directly, with
no source list, selection record or builder.

The author stated on 17 October 2026 that they compiled the dictionary
themselves, as their own selection of common given names and surnames. It
is therefore distributed with the software under the MIT licence in
[LICENSE](../LICENSE).

The committed dictionary has 1,793 rows and 1,559 distinct name strings, with
1,466 rows labelled `first` and 327 labelled `last`. There are no repeated
complete rows. The table gives the file's own language labels and their counts.
The assignment of those labels has not been independently verified.

| Label | Rows |
|---|---:|
| arabic | 13 |
| chinese | 143 |
| english | 967 |
| french | 180 |
| german | 141 |
| hindi | 141 |
| italian | 21 |
| polynesian | 11 |
| spanish | 176 |

The LF representation of the committed input has SHA-256
`0f8606668959a3464bf8e46e693ebfcd2320723b9d52acc849a893d07a881e4a`.
With CRLF line endings, its SHA-256 is
`e60dec823e338a7084bfed812b9259bbc081cceebec3c1ad1df6e7da6c130a0a`,
the digest recorded by the four committed masking summaries. These digests
identify the archived input's bytes, not its representativeness.

The code also offers the optional `names-dataset` package. Its upstream
[README](https://github.com/philipperemy/name-dataset) describes a much larger
name collection derived from a Facebook data dump, and its repository has an
[Apache 2.0 licence](https://github.com/philipperemy/name-dataset/blob/master/LICENSE).
That collection is a separate, optional source; no committed record
connects it to this CSV, and the author's account names no source.

What the record still lacks is the selection procedure: how names were
chosen, spelt and transliterated, and how the language and first/last
labels were assigned. The file can be checked against its archived bytes
and its masking benchmark rerun, but no builder recreates it. The
benchmark's in-dictionary cells test masking behaviour conditional on
membership. Estimating coverage of names in a population or corpus would
require a separate sampling frame.
