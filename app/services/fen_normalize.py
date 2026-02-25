from __future__ import annotations

"""FEN normalization utilities.

The chess application matches positions across skill blocks using only the
first 4 fields of a FEN string:

    <piece placement> <active color> <castling> <en passant>

The half-move clock (field 5) and full-move number (field 6) are intentionally
ignored so that transpositions and repeated positions are treated as identical
regardless of move history.
"""


def normalize_fen(fen: str) -> str:
    """Return a 4-field FEN by stripping the half-move clock and full-move number.

    Examples::

        >>> normalize_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3'

        >>> normalize_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3")
        'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3'

    Raises ValueError if the FEN has fewer than 4 fields.
    """
    fields = fen.split()
    if len(fields) < 4:
        raise ValueError(
            f"FEN has only {len(fields)} field(s), expected at least 4: {fen!r}"
        )
    return " ".join(fields[:4])
