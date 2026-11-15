"""Hugging Face 패션 이미지 모델로 취향 맞히기 실험 (맥에서 무료).

  python evals/hf_experiment.py

라벨(👍👎) 달린 매물 썸네일을 이미지 모델로 벡터로 바꾸고, 세 방식으로 👍 여부를 예측한다.
모든 방식은 한 개 빼고 평가(leave-one-out): 매물 하나를 맞힐 때 그 매물의 라벨은 쓰지 않는다.

- 중심 유사도: 👍 사진들과의 평균 유사도 - 👎 사진들과의 평균 유사도
- kNN: 가장 비슷한 라벨 매물 5개의 👍 비율 (유사도 가중)
- 로지스틱 회귀: 벡터로 👍/👎를 가르는 작은 선형 모델

지표는 run_eval.py와 같은 분리도(AUC). 결과는 evals/reports/에 남긴다.
"""

import functools
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

import main  # noqa: E402
from evals.run_eval import auc  # noqa: E402
from finder import images  # noqa: E402
from finder.store import Store  # noqa: E402

print = functools.partial(print, flush=True)  # noqa: A001
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def load_marqo():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms("hf-hub:Marqo/marqo-fashionSigLIP")
    model = model.eval().to(DEVICE)

    @torch.no_grad()
    def embed(pils):
        x = torch.stack([preprocess(p) for p in pils]).to(DEVICE)
        return model.encode_image(x, normalize=True).float().cpu().numpy()
    return embed


def load_fashion_clip():
    from transformers import CLIPModel, CLIPProcessor
    model = CLIPModel.from_pretrained("patrickjohncyh/fashion-clip").eval().to(DEVICE)
    processor = CLIPProcessor.from_pretrained("patrickjohncyh/fashion-clip")

    @torch.no_grad()
    def embed(pils):
        inputs = processor(images=pils, return_tensors="pt").to(DEVICE)
        out = model.get_image_features(**inputs)
        out = getattr(out, "pooler_output", out)  # 버전에 따라 텐서 또는 출력 객체
        out = out / out.norm(dim=-1, keepdim=True)
        return out.float().cpu().numpy()
    return embed


MODELS = {"Marqo FashionSigLIP": load_marqo, "FashionCLIP": load_fashion_clip}


def predict_centroid(X, y):
    sims = X @ X.T
    scores = []
    for i in range(len(y)):
        mask = np.arange(len(y)) != i
        likes, dislikes = mask & (y == 1), mask & (y == 0)
        scores.append(sims[i, likes].mean() - sims[i, dislikes].mean())
    return scores


def predict_knn(X, y, k=5):
    sims = X @ X.T
    np.fill_diagonal(sims, -np.inf)
    scores = []
    for i in range(len(y)):
        top = np.argsort(-sims[i])[:k]
        w = np.maximum(sims[i, top], 0) + 1e-6
        scores.append(float((w * y[top]).sum() / w.sum()))
    return scores


def predict_logreg(X, y):
    scores = []
    for i in range(len(y)):
        mask = np.arange(len(y)) != i
        clf = LogisticRegression(class_weight="balanced", C=1.0, max_iter=2000).fit(X[mask], y[mask])
        scores.append(float(clf.predict_proba(X[i:i + 1])[0, 1]))
    return scores


METHODS = {"중심 유사도": predict_centroid, "kNN (5개)": predict_knn, "로지스틱 회귀": predict_logreg}


def main_():
    store = Store(main.DB_PATH)
    rows = [dict(r) for r in store.conn.execute(
        "SELECT id, image_url, feedback FROM listings WHERE feedback IS NOT NULL ORDER BY feedback_at")]
    pils, ys, ids = [], [], []
    for r in rows:
        got = images.thumb(r["id"], r["image_url"])
        if not got:
            continue
        pils.append(Image.open(BytesIO(got[0])).convert("RGB"))
        ys.append(1 if r["feedback"] > 0 else 0)
        ids.append(r["id"])
    y = np.array(ys)
    print(f"라벨 {len(y)}개 (👍 {y.sum()} / 👎 {len(y) - y.sum()}), 장치 {DEVICE}")

    # 012 평가에서 Gemini로 다시 채점한 매물들과 같은 집합에서도 따로 잰다 (공정 비교용)
    earlier = sorted((ROOT / "evals" / "datasets").glob("labels-20261114-1939.json"))
    subset = {d["id"] for d in json.loads(earlier[0].read_text())} if earlier else set()
    sub_mask = np.array([i in subset for i in ids])

    results = []
    for name, loader in MODELS.items():
        print(f"{name} 불러오는 중…")
        embed = loader()
        embed(pils[:2])  # 첫 호출은 준비 시간이 섞여서 뺀다
        t = time.perf_counter()
        X = np.concatenate([embed(pils[i:i + 16]) for i in range(0, len(pils), 16)])
        per_image_ms = (time.perf_counter() - t) / len(pils) * 1000
        for mname, fn in METHODS.items():
            s = np.array(fn(X, y))
            a_all = auc(list(s[y == 1]), list(s[y == 0]))
            a_sub = auc(list(s[sub_mask & (y == 1)]), list(s[sub_mask & (y == 0)])) if sub_mask.any() else None
            results.append((name, mname, a_all, a_sub, per_image_ms))
            print(f"  {mname}: AUC 전체 {a_all:.3f}" + (f" / 012 집합 {a_sub:.3f}" if a_sub else ""))

    stamp = f"{datetime.now():%Y%m%d-%H%M}"
    lines = [
        f"# Hugging Face 이미지 모델 실험 {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"라벨 {len(y)}개 (👍 {y.sum()} / 👎 {len(y) - y.sum()}). 썸네일(240×240)만 사용, 한 개 빼고 평가. 장치 {DEVICE}.",
        f"\"012 집합\"은 012 평가에서 Gemini로 다시 채점한 매물들({sub_mask.sum()}개)만 따로 잰 값이다. "
        "그때 Gemini 사진 비교 AUC는 0.801, 글 기준만은 0.590.",
        "",
        "| 모델 | 방식 | AUC (전체) | AUC (012 집합) | 사진 한 장 처리 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, mname, a_all, a_sub, ms in results:
        lines.append(f"| {name} | {mname} | {a_all:.3f} | {a_sub:.3f} | {ms:.0f}ms |" if a_sub is not None
                     else f"| {name} | {mname} | {a_all:.3f} | - | {ms:.0f}ms |")
    text = "\n".join(lines) + "\n"
    path = ROOT / "evals" / "reports" / f"{stamp}-hf.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"저장: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main_()
