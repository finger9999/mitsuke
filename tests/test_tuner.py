from finder import tuner
from finder.models import Listing
from finder.store import Store


def make_store(n_like=6, n_dislike=10):
    store = Store(":memory:")
    store.set_setting("taste", "[알림 받고 싶은 것]\n울 숏코트")
    for i in range(n_like + n_dislike):
        fb = 1 if i < n_like else -1
        store.add(Listing(f"mercari:m{i}", "s", f"t{i}", 1000, None, "u"), status="scored",
                  score=50 if fb > 0 else 80, score_reason="r")
        store.set_feedback(f"mercari:m{i}", fb)
    return store


def test_split_is_stable():
    assert tuner.split("mercari:m1") == tuner.split("mercari:m1")
    sides = {tuner.split(f"mercari:m{i}") for i in range(20)}
    assert sides == {"propose", "validate"}


def test_mismatches_pick_disagreements():
    rows = [{"feedback": -1, "score": 85}, {"feedback": -1, "score": 30},
            {"feedback": 1, "score": 40}, {"feedback": 1, "score": 95}]
    got = tuner._mismatches(rows, 90)
    assert [(r["feedback"], r["score"]) for r in got] == [(-1, 85), (1, 40)]


def run_tune(monkeypatch, before_good: bool):
    store = make_store()
    monkeypatch.setattr(tuner, "propose", lambda *a: ("새 기준", ["바꿈"], 0.001))
    calls = []

    def fake_score_all(store_, key, model, taste, rows, interval, sleep):
        calls.append(taste)
        good = (taste == "새 기준") != before_good
        # good이면 👍에 높은 점수 → AUC 1.0, 아니면 반대 → AUC 0.0
        return [{"id": r["id"], "feedback": r["feedback"],
                 "score": (90 if r["feedback"] > 0 else 10) if good else (10 if r["feedback"] > 0 else 90)}
                for r in rows], 0.0

    monkeypatch.setattr(tuner, "_score_all", fake_score_all)
    monkeypatch.setattr(tuner.genai, "Client", lambda **kw: None)
    result = tuner.tune(store, "key", {}, sample=20)
    return store, result


def test_tune_applies_when_better(monkeypatch):
    store, result = run_tune(monkeypatch, before_good=False)
    assert result.accepted and store.settings()["taste"] == "새 기준"
    assert store.settings()["taste_history"][-1]["accepted"] is True


def test_tune_keeps_when_not_better(monkeypatch):
    store, result = run_tune(monkeypatch, before_good=True)
    assert not result.accepted and store.settings()["taste"].startswith("[알림")
