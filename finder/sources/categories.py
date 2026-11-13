"""메루카리 카테고리 트리.

매물에는 가장 아래 단계 카테고리(예: 149 ロングコート)만 붙어 온다.
"아우터 전체"처럼 위 단계로 규칙을 걸려면 조상을 따라 올라가야 한다.

트리는 두 군데서 읽는다.
- mercari_categories.json: 카테고리 목록 API 스냅샷 (`python main.py update-categories`)
- data/mercari_categories_learned.json: 스냅샷에 없던 카테고리를 매물 상세에서 알아내 쌓아둔 것
"""

import json
from functools import cache
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("mercari_categories.json")
LEARNED = Path(__file__).resolve().parents[2] / "data" / "mercari_categories_learned.json"


def _read(path: Path) -> dict[int, tuple[str, int]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): (name, int(parent)) for k, (name, parent) in raw.items()}


@cache
def _tree() -> dict[int, tuple[str, int]]:
    tree = _read(LEARNED)
    tree.update(_read(SNAPSHOT))  # 겹치면 공식 목록이 우선
    return tree


def is_known(category_id: int | None) -> bool:
    return category_id is None or category_id in _tree()


def lineage(category_id: int | None) -> list[int]:
    """자기 자신부터 최상위까지의 id 목록. 모르는 id면 자기 자신만."""
    if category_id is None:
        return []
    tree = _tree()
    chain = []
    current = category_id
    while current and current not in chain:
        chain.append(current)
        current = tree.get(current, ("", 0))[1]
    return chain


def name(category_id: int) -> str:
    return _tree().get(category_id, (str(category_id), 0))[0]


def path(category_id: int | None) -> str:
    return " > ".join(name(c) for c in reversed(lineage(category_id)))


def learn(chain: list[tuple[int, str, int]]):
    """매물 상세에서 알아낸 경로를 저장한다. 이미 아는 카테고리는 건드리지 않는다."""
    tree = _tree()
    learned = {str(k): list(v) for k, v in _read(LEARNED).items()}
    for cid, cname, parent in chain:
        if cid not in tree:
            learned[str(cid)] = [cname, parent]
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    LEARNED.write_text(json.dumps(learned, ensure_ascii=False, indent=0), encoding="utf-8")
    _tree.cache_clear()


def save_snapshot(tree: dict[str, list]):
    SNAPSHOT.write_text(json.dumps(tree, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _tree.cache_clear()
