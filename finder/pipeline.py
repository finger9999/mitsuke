"""단계 연결: 수집 → 신규 감지 → 규칙 필터 → LLM 채점 → Buyee 링크 → 저장 → 알림.

채점기(scorer)가 없으면(API 키나 취향 기준이 없을 때) 0단계처럼 규칙 통과 매물을 모두 알림으로 보낸다.
채점기가 있으면 notify_score점 이상만 알림을 보내고, 나머지는 앱 목록에만 쌓인다.
실행당 LLM 호출 수에 상한이 있고, 상한을 넘거나 채점에 실패한 매물은 점수 없이 목록에 올린다.
"""

import logging
import random
import time
from dataclasses import dataclass, field

from finder import filters, notifier
from finder.checkout import buyee
from finder.models import Listing
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
    scored: int = 0
    cost_usd: float = 0.0
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


class Evaluator:
    """매물 하나를 규칙 → (채점) → 저장 → (알림) 순서로 처리한다. 실행 하나 동안 상한과 비용을 함께 센다."""

    def __init__(self, config: dict, store: Store, stats: RunStats, scorer=None,
                 describe_fn=mercari.fetch_description):
        self.store = store
        self.stats = stats
        self.scorer = scorer
        self.describe_fn = describe_fn
        self.llm_limit = config.get("llm_calls_per_run", 30)
        self.notify_score = config.get("notify_score", 90)
        # 채점할 카테고리. 비어 있으면 규칙 통과 매물 전부, 있으면 그 카테고리(와 그 아래)만 채점한다
        self.score_categories = {int(c) for c in config.get("score_categories") or []}
        self.budget_left = config.get("llm_monthly_budget_usd", 1.0) - store.month_cost_usd()
        self.halted: str | None = None  # 결제·권한 오류가 나면 이번 실행에서는 채점을 멈춘다

    def evaluate(self, listing: Listing, rules: filters.Rules, notify: bool):
        stats, store = self.stats, self.store
        reason = filters.check(listing, rules)
        if reason:
            store.add(listing, status="filtered", filter_reason=reason)
            stats.filtered += 1
            return

        url = buyee.item_url(listing.id)
        if self.scorer is None:
            store.add(listing, status="passed", buyee_url=url)
            if notify and notifier.notify(listing, url):
                store.set_status(listing.id, "notified")
                stats.notified += 1
            return

        if self.score_categories and not self.score_categories & set(categories.lineage(listing.category_id)):
            # 지금 찾는 종류가 아니면 LLM을 부르지 않고 목록에만 올린다
            store.add(listing, status="passed", buyee_url=url)
            return
        if self.halted:
            store.add(listing, status="passed", buyee_url=url, score_reason=f"채점 중단: {self.halted}")
            return
        if stats.scored >= self.llm_limit or stats.cost_usd >= self.budget_left:
            store.add(listing, status="passed", buyee_url=url, score_reason="LLM 호출·비용 상한을 넘어 채점하지 않음")
            return
        try:
            result = self.scorer.score(listing, self.describe_fn(listing.id))
        except Exception as e:  # 채점 실패도 목록에는 올려서 놓치지 않는다
            short = _short_error(e)
            log.warning("채점 실패 %s: %s", listing.id, e)
            stats.errors.append(f"채점 {listing.id}: {short}")
            store.add(listing, status="passed", buyee_url=url, score_reason=f"채점 실패: {short}")
            if getattr(e, "code", None) in (401, 402, 403, 429):
                # 키·결제·한도 문제는 다음 매물에서도 똑같이 실패한다. 헛호출하지 않고 멈춘다
                self.halted = short
                log.error("채점 중단 (이번 실행): %s", short)
            return
        stats.scored += 1
        stats.cost_usd += result.cost_usd
        store.add(listing, status="scored", buyee_url=url, score=result.score, score_reason=result.reason,
                  score_model=result.model, score_cost_usd=result.cost_usd)
        if notify and result.score >= self.notify_score and notifier.notify(listing, url, result.score, result.reason):
            store.set_status(listing.id, "notified")
            stats.notified += 1


def _short_error(e: Exception) -> str:
    code = getattr(e, "code", None)
    known = {401: "API 키가 잘못됨", 402: "API 선불 크레딧 소진", 403: "API 권한 없음", 429: "API 사용 한도 초과"}
    if code in known:
        return f"{known[code]} ({code})"
    return str(e)[:120]


def run(config: dict, store: Store, notify: bool = True, search_fn=mercari.search, sleep=time.sleep,
        chain_fn=mercari.fetch_category_chain, scorer=None, describe_fn=mercari.fetch_description) -> RunStats:
    stats = RunStats()
    evaluator = Evaluator(config, store, stats, scorer, describe_fn)
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

        rules = rules_for(search_cfg, defaults)
        learn_categories(fresh, chain_fn=chain_fn, sleep=sleep)
        if first_run:
            # 첫 실행: 이미 올라와 있던 매물도 규칙·채점은 하되 알림은 보내지 않는다 (알림이 쏟아지지 않게)
            stats.seeded += len(fresh)
            log.info("%r 첫 실행: 매물 %d개 평가 (알림 없음)", keyword, len(fresh))
        # 오래된 것부터 처리해서 알림도 올라온 순서대로 쌓이게 한다
        for listing in reversed(fresh):
            evaluator.evaluate(listing, rules, notify=notify and not first_run)

        log.info("%r: 가져옴 %d, 신규 %d", keyword, len(listings), len(fresh))

    return stats


def reevaluate(config: dict, store: Store, scorer=None, chain_fn=mercari.fetch_category_chain,
               describe_fn=mercari.fetch_description, sleep=time.sleep) -> RunStats:
    """이미 저장된 매물을 다시 평가한다. 알림은 보내지 않는다.

    대상: 예전 방식으로 평가 없이 저장된 기준점 매물, 그리고 채점기가 있으면 아직 점수가 없는 통과 매물.
    """
    stats = RunStats()
    evaluator = Evaluator(config, store, stats, scorer, describe_fn)
    defaults = config.get("defaults", {})
    search_cfgs = {s["keyword"]: s for s in config.get("searches", [])}
    targets = store.listings_to_reevaluate(include_unscored=scorer is not None)
    learn_categories(targets, chain_fn=chain_fn, sleep=sleep)
    for listing in targets:
        evaluator.evaluate(listing, rules_for(search_cfgs.get(listing.search, {}), defaults), notify=False)
    stats.new = len(targets)
    return stats
