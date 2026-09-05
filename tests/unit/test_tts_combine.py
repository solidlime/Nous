import wave, io, math, struct
import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import _concat_wav

def _sine_wav(nframes=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        frames = b"".join(struct.pack("<h", int(1000*math.sin(i/10))) for i in range(nframes))
        w.writeframes(frames)
    buf.seek(0)
    return buf.read()

def test_concat_sums_frames(tmp_path):
    a = tmp_path / "a.wav"; b = tmp_path / "b.wav"
    a.write_bytes(_sine_wav(16000)); b.write_bytes(_sine_wav(8000))
    blob, params = _concat_wav([a, b])
    with wave.open(io.BytesIO(blob), "rb") as w:
        assert w.getnframes() == 24000
        assert w.getframerate() == 16000

def test_concat_rejects_mismatch(tmp_path):
    a = tmp_path / "a.wav"; b = tmp_path / "b.wav"
    a.write_bytes(_sine_wav(100))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 100 * 2)
    b.write_bytes(buf.getvalue())
    with pytest.raises(ValueError):
        _concat_wav([a, b])

