"""평가 지표. evals/run_eval.py와 finder/tuner.py가 같이 쓴다."""


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def metrics(rows: list[dict], threshold: int) -> dict:
    """rows: {feedback: 1|-1, score: int}"""
    pos = [r["score"] for r in rows if r["feedback"] > 0]
    neg = [r["score"] for r in rows if r["feedback"] < 0]
    alerted = [r for r in rows if r["score"] >= threshold]
    tp = sum(r["feedback"] > 0 for r in alerted)
    return {
        "n": len(rows),
        "likes": len(pos),
        "dislikes": len(neg),
        "auc": auc(pos, neg),
        "mean_like": sum(pos) / len(pos) if pos else None,
        "mean_dislike": sum(neg) / len(neg) if neg else None,
        "alerts": len(alerted),
        "precision": tp / len(alerted) if alerted else None,
        "recall": tp / len(pos) if pos else None,
    }
