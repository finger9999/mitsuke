"""단계 연결: 수집 → 신규 감지 → 규칙 필터 → Buyee 링크 → 저장 → 알림.

0단계라서 점수가 없다. 규칙을 통과한 매물은 모두 알림으로 보낸다.
"""

import logging
import random
import time
from dataclasses import dataclass, field

from finder import filters, notifier
from finder.checkout import buyee
from finder.sources import categories, mercari
from finder.store import Store

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    seeded: int = 0
    filtered: int = 0
    notified: int = 0
    errors: list[str] = field(default_factory=list)


def rules_for(search_cfg: dict, defaults: dict) -> filters.Rules:
    """검색어별 설정이 기본값을 덮어쓴다. 제외 목록과 카테고리 예산은 합친다."""
    def merged(key):
        return defaults.get(key, []) + search_cfg.get(key, [])

    category_price_max = {int(k): v for k, v in (defaults.get("category_price_max") or {}).items()}
    category_price_max.update({int(k): v for k, v in (search_cfg.get("category_price_max") or {}).items()})
    return filters.Rules(
        price_min=search_cfg.get("price_min", defaults.get("price_min", 0)),
        price_max=search_cfg.get("price_max", defaults.get("price_max")),
        category_price_max=category_price_max,
        exclude_categories=[int(c) for c in merged("exclude_categories")],
        exclude_keywords=merged("exclude_keywords"),
        sizes=search_cfg.get("sizes", defaults.get("sizes", [])),
    )


def learn_categories(listings, chain_fn=mercari.fetch_category_chain, sleep=time.sleep):
    """모르는 카테고리가 있으면 그 카테고리 매물 하나의 상세로 경로를 알아낸다. 카테고리당 한 번뿐이다."""
    unknown = {}
    for listing in listings:
        if not categories.is_known(listing.category_id):
            unknown.setdefault(listing.category_id, listing.id)
    for category_id, listing_id in unknown.items():
        try:
            categories.learn(chain_fn(listing_id))
            log.info("새 카테고리: %s", categories.path(category_id))
        except Exception:
            # 실패하면 기본 예산이 적용된다. 다음 실행에서 다시 시도한다
            log.warning("카테고리 %s 경로를 못 알아냄 (매물 %s)", category_id, listing_id, exc_info=True)
        sleep(1)


def run(config: dict, store: Store, notify: bool = True, search_fn=mercari.search, sleep=time.sleep,
        chain_fn=mercari.fetch_category_chain) -> RunStats:
    stats = RunStats()
    defaults = config.get("defaults", {})
    delay = config.get("request_delay_seconds", 8)
    page_size = config.get("page_size", 60)

    for i, search_cfg in enumerate(config.get("searches", [])):
        keyword = search_cfg["keyword"]
        if i > 0:
            # 검색어 사이에 대기. 일정한 간격이 되지 않게 조금 흔든다
            sleep(delay + random.uniform(0, delay / 2))

        try:
            listings = search_fn(keyword, page_size=page_size)
        except Exception as e:  # 검색어 하나가 실패해도 나머지는 돈다
            log.exception("검색 실패: %r", keyword)
            stats.errors.append(f"{keyword}: {e}")
            continue

        stats.fetched += len(listings)
        first_run = not store.has_search(keyword)
        fresh = store.new_only(listings)
        stats.new += len(fresh)

        if first_run:
            # 첫 실행은 기준점만 저장. 이미 올라와 있던 매물로 알림이 쏟아지지 않게 한다
            for listing in fresh:
                store.add(listing, status="seeded")
            stats.seeded += len(fresh)
            log.info("%r 첫 실행: 기준점 %d개 저장", keyword, len(fresh))
            continue

        rules = rules_for(search_cfg, defaults)
        learn_categories(fresh, chain_fn=chain_fn, sleep=sleep)
        # 오래된 것부터 처리해서 알림도 올라온 순서대로 쌓이게 한다
        for listing in reversed(fresh):
            reason = filters.check(listing, rules)
            if reason:
                store.add(listing, status="filtered", filter_reason=reason)
                stats.filtered += 1
                continue

            url = buyee.item_url(listing.id)
            store.add(listing, status="passed", buyee_url=url)
            if notify and notifier.notify(listing, url):
                store.set_status(listing.id, "notified")
                stats.notified += 1

        log.info("%r: 가져옴 %d, 신규 %d", keyword, len(listings), len(fresh))

    return stats
