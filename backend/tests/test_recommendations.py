import models
from crud import get_fallback_recommendations


def make_product(sku, name, category, price):
    return models.Product(
        sku=sku, name=name, description=name, category=category,
        price=price, stock=10, attributes={},
    )


def test_fallback_excludes_other_categories_and_self(db_session):
    boot_a = make_product("A1", "Boot A", "Hiking Boots", 80.0)
    boot_b = make_product("A2", "Boot B", "Hiking Boots", 95.0)
    tent = make_product("A3", "Tent A", "Tents", 150.0)
    db_session.add_all([boot_a, boot_b, tent])
    db_session.commit()

    results = get_fallback_recommendations(db_session, boot_a, limit=5)
    result_skus = [r.sku for r in results]

    assert "A3" not in result_skus, "different category must never appear"
    assert "A1" not in result_skus, "the product itself must never appear"
    assert "A2" in result_skus


def test_fallback_orders_by_price_closeness(db_session):
    base = make_product("B1", "Base Jacket", "Jackets", 100.0)
    close = make_product("B2", "Close Jacket", "Jackets", 110.0)   # diff 10
    far = make_product("B3", "Far Jacket", "Jackets", 40.0)        # diff 60
    db_session.add_all([base, close, far])
    db_session.commit()

    results = get_fallback_recommendations(db_session, base, limit=5)
    result_skus = [r.sku for r in results]

    assert result_skus == ["B2", "B3"], "closer price must rank first"


def test_fallback_respects_limit(db_session):
    base = make_product("C0", "Base Stove", "Camp Stoves", 50.0)
    others = [make_product(f"C{i}", f"Stove {i}", "Camp Stoves", 50.0 + i) for i in range(1, 8)]
    db_session.add_all([base, *others])
    db_session.commit()

    results = get_fallback_recommendations(db_session, base, limit=3)
    assert len(results) == 3


def test_fallback_returns_empty_when_alone_in_category(db_session):
    lonely = make_product("D1", "Lonely Bottle", "Water Bottles", 20.0)
    db_session.add(lonely)
    db_session.commit()

    results = get_fallback_recommendations(db_session, lonely, limit=5)
    assert results == [], "no error, just an honestly empty result"
