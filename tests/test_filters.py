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
