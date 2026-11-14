import os
import time

from finder import images


def test_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "CACHE", tmp_path)
    old = time.time() - 10 * 86400
    files = {
        "mercari_m1_full.jpg": old,      # 오래된 원본 → 지움
        "mercari_m2_full.jpg": time.time(),  # 오늘 받은 원본 → 남김
        "mercari_m3_thumb.webp": old,    # 👍한 매물 썸네일 → 남김
        "mercari_m4_thumb.webp": old,    # 평가 안 한 오래된 썸네일 → 지움
    }
    for name, mtime in files.items():
        p = tmp_path / name
        p.write_bytes(b"x")
        os.utime(p, (mtime, mtime))
    assert images.cleanup({"mercari:m3"}) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mercari_m2_full.jpg", "mercari_m3_thumb.webp"]
