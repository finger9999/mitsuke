from finder.filters import Rules, check
from finder.models import Listing


def make(title="PORTER タンカー リュック", price=10000):
    return Listing(id="mercari:m1", search="s", title=title, price_jpy=price, image_url=None, url="u")


def test_pass():
    assert check(make(), Rules(price_max=20000)) is None


def test_price_bounds():
    assert "예산" in check(make(price=30000), Rules(price_max=20000))
    assert "최저" in check(make(price=500), Rules(price_min=1000))


def test_exclude_keyword_width_insensitive():
    # 반각 가타카나도 잡는다
    assert "제외" in check(make(title="ﾎﾟｰﾀｰ ｼﾞｬﾝｸ"), Rules(exclude_keywords=["ジャンク"]))


def test_sizes():
    rules = Rules(sizes=["27.5"])
    assert check(make(title="990v6 ２７．５cm"), rules) is None
    assert "사이즈" in check(make(title="990v6 26cm"), rules)


def test_outer_gets_category_budget():
    rules = Rules(price_max=30000, category_price_max={12: 70000, 31: 70000})
    coat = make(title="ツモリチサト ロングコート", price=50000)
    coat.category_id = 149  # レディース > ジャケット/アウター > ロングコート
    assert check(coat, rules) is None

    shirt = make(title="ツモリチサト シャツ", price=50000)
    shirt.category_id = 122  # レディース > トップス > シャツ/ブラウス(長袖/七分)
    assert "예산 ¥30,000" in check(shirt, rules)

    expensive_coat = make(price=80000)
    expensive_coat.category_id = 149
    assert "예산 ¥70,000" in check(expensive_coat, rules)


def test_unknown_category_uses_default_budget():
    rules = Rules(price_max=30000, category_price_max={12: 70000})
    assert "예산 ¥30,000" in check(make(price=50000), rules)


def test_exclude_category():
    pajama = make(title="ツモリチサト ルームウェア上下")
    pajama.category_id = 186  # パジャマ
    assert "제외 카테고리" in check(pajama, Rules(exclude_categories=[186]))
