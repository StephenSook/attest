"""The shipped hero film must stay scrub-safe.

The landing scrubs video.currentTime with scroll. With sparse keyframes,
every mid-file seek re-decodes from the previous keyframe; on machines
without cheap hardware decode that starves the main thread and freezes
scrolling entirely (observed live 2026-07-25: the shipped film had ONE
keyframe in 192 frames and scroll died mid-page). This test parses the
mp4's sync-sample table directly, stdlib only, so a badly encoded film
fails CI instead of shipping.
"""

import struct
from collections.abc import Iterator
from pathlib import Path

FILM = Path(__file__).parent.parent / "frontend" / "public" / "hero.mp4"

# One keyframe at least every half second of film keeps worst-case seek
# decode short enough that scrubbing can never starve the main thread.
MAX_SECONDS_PER_KEYFRAME = 0.5


def _boxes(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack(">I4s", data[offset : offset + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
            header = 16
        elif size == 0:
            size = end - offset
        yield kind, offset + header, offset + size
        offset += size


def _find(
    data: bytes, path: list[bytes], start: int = 0, end: int | None = None
) -> Iterator[tuple[int, int]]:
    if end is None:
        end = len(data)
    for kind, body_start, body_end in _boxes(data, start, end):
        if kind == path[0]:
            if len(path) == 1:
                yield body_start, body_end
            else:
                yield from _find(data, path[1:], body_start, body_end)


def _video_stbl(data: bytes) -> tuple[int, int] | None:
    """The sample table of the first video track (the one with an avc1/hvc1)."""
    for moov_s, moov_e in _find(data, [b"moov"]):
        for trak_s, trak_e in _find(data, [b"trak"], moov_s, moov_e):
            for stbl_s, stbl_e in _find(data, [b"mdia", b"minf", b"stbl"], trak_s, trak_e):
                stsd = next(iter(_find(data, [b"stsd"], stbl_s, stbl_e)), None)
                if stsd and (
                    b"avc1" in data[stsd[0] : stsd[1]]
                    or b"hvc1" in data[stsd[0] : stsd[1]]
                    or b"hev1" in data[stsd[0] : stsd[1]]
                ):
                    return stbl_s, stbl_e
    return None


def test_hero_film_keyframe_density() -> None:
    data = FILM.read_bytes()

    # Duration from mvhd (version 0 or 1).
    mvhd_s, _ = next(iter(_find(data, [b"moov", b"mvhd"])))
    version = data[mvhd_s]
    if version == 1:
        timescale, dur = struct.unpack(">IQ", data[mvhd_s + 20 : mvhd_s + 32])
    else:
        timescale, dur = struct.unpack(">II", data[mvhd_s + 12 : mvhd_s + 20])
    seconds = dur / timescale
    assert 4 <= seconds <= 30, f"unexpected film duration {seconds:.1f}s"

    stbl = _video_stbl(data)
    assert stbl is not None, "no video track found in hero.mp4"

    stss = next(iter(_find(data, [b"stss"], *stbl)), None)
    if stss is None:
        return  # no sync table = every sample is a keyframe: ideal for scrubbing
    keyframes = struct.unpack(">I", data[stss[0] + 4 : stss[0] + 8])[0]
    assert keyframes >= seconds / MAX_SECONDS_PER_KEYFRAME, (
        f"hero.mp4 has {keyframes} keyframes over {seconds:.1f}s; scrubbing needs "
        f"one at least every {MAX_SECONDS_PER_KEYFRAME}s or seeks freeze scroll. "
        "Re-encode with ffmpeg -g <fps/2> -bf 0."
    )
