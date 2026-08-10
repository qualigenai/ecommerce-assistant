from sqlalchemy.orm import Session

import models

PRODUCTS = [
    # Hiking boots
    {"sku": "BOOT-001", "name": "Trailhead Waterproof Hiking Boot", "description": "Full-grain leather waterproof hiking boot with reinforced ankle support.", "category": "Hiking Boots", "price": 89.99, "stock": 42, "attributes": {"waterproof": True, "color": "brown", "weight_grams": 620}},
    {"sku": "BOOT-002", "name": "Summit Lite Trail Runner", "description": "Lightweight mesh trail runner for fast day hikes, breathable, not waterproof.", "category": "Hiking Boots", "price": 74.50, "stock": 30, "attributes": {"waterproof": False, "color": "gray", "weight_grams": 410}},
    {"sku": "BOOT-003", "name": "Alpine Ridge GTX Boot", "description": "Gore-Tex waterproof boot built for rocky, wet alpine terrain.", "category": "Hiking Boots", "price": 149.99, "stock": 18, "attributes": {"waterproof": True, "color": "black", "weight_grams": 780}},
    {"sku": "BOOT-004", "name": "Meadowbrook Casual Hiker", "description": "Everyday hiking shoe for well-maintained trails and light rain.", "category": "Hiking Boots", "price": 64.99, "stock": 55, "attributes": {"waterproof": True, "color": "olive", "weight_grams": 540}},
    {"sku": "BOOT-005", "name": "Desert Trek Ventilated Boot", "description": "Breathable, non-waterproof boot designed for hot, dry climates.", "category": "Hiking Boots", "price": 79.99, "stock": 27, "attributes": {"waterproof": False, "color": "tan", "weight_grams": 590}},

    # Backpacks
    {"sku": "PACK-001", "name": "TrailBlazer 40L Backpack", "description": "40-liter multi-day backpack with adjustable torso and hip belt.", "category": "Backpacks", "price": 129.99, "stock": 20, "attributes": {"waterproof": False, "capacity_liters": 40, "color": "green"}},
    {"sku": "PACK-002", "name": "DayHiker 22L Pack", "description": "Compact 22-liter daypack with hydration bladder compatibility.", "category": "Backpacks", "price": 54.99, "stock": 48, "attributes": {"waterproof": False, "capacity_liters": 22, "color": "blue"}},
    {"sku": "PACK-003", "name": "Storm Guard 40L Rain-Ready Pack", "description": "40-liter pack with a built-in waterproof rain cover.", "category": "Backpacks", "price": 139.99, "stock": 15, "attributes": {"waterproof": True, "capacity_liters": 40, "color": "black"}},
    {"sku": "PACK-004", "name": "UltraLight 15L Running Vest", "description": "Minimalist running vest pack for trail races.", "category": "Backpacks", "price": 69.99, "stock": 22, "attributes": {"waterproof": False, "capacity_liters": 15, "color": "orange"}},
    {"sku": "PACK-005", "name": "Basecamp 65L Expedition Pack", "description": "Large capacity pack for multi-week backcountry trips.", "category": "Backpacks", "price": 219.99, "stock": 9, "attributes": {"waterproof": True, "capacity_liters": 65, "color": "gray"}},

    # Tents
    {"sku": "TENT-001", "name": "StormShield 2-Person Tent", "description": "Fully waterproof 2-person tent rated for heavy rain.", "category": "Tents", "price": 189.99, "stock": 14, "attributes": {"waterproof": True, "capacity_people": 2, "season": "3-season"}},
    {"sku": "TENT-002", "name": "SoloTrek 1-Person Ultralight Tent", "description": "Ultralight solo backpacking tent, water-resistant fly.", "category": "Tents", "price": 159.99, "stock": 11, "attributes": {"waterproof": True, "capacity_people": 1, "season": "3-season"}},
    {"sku": "TENT-003", "name": "Family Basecamp 6-Person Tent", "description": "Spacious 6-person tent for car camping, not fully waterproof seams.", "category": "Tents", "price": 249.99, "stock": 8, "attributes": {"waterproof": False, "capacity_people": 6, "season": "3-season"}},
    {"sku": "TENT-004", "name": "Winter Fortress 4-Season Tent", "description": "Heavy-duty 4-season tent built for snow and high wind.", "category": "Tents", "price": 349.99, "stock": 6, "attributes": {"waterproof": True, "capacity_people": 3, "season": "4-season"}},

    # Jackets
    {"sku": "JKT-001", "name": "RainGuard Waterproof Shell Jacket", "description": "Fully waterproof, breathable rain shell for hiking in wet conditions.", "category": "Jackets", "price": 119.99, "stock": 33, "attributes": {"waterproof": True, "color": "yellow", "insulated": False}},
    {"sku": "JKT-002", "name": "Summit Down Insulated Jacket", "description": "Warm down-insulated jacket for cold, dry conditions.", "category": "Jackets", "price": 189.99, "stock": 19, "attributes": {"waterproof": False, "color": "navy", "insulated": True}},
    {"sku": "JKT-003", "name": "AllWeather 3-in-1 Jacket", "description": "Waterproof shell plus zip-in insulated liner for all conditions.", "category": "Jackets", "price": 229.99, "stock": 12, "attributes": {"waterproof": True, "color": "black", "insulated": True}},
    {"sku": "JKT-004", "name": "Breeze Windbreaker", "description": "Lightweight windbreaker, water-resistant but not fully waterproof.", "category": "Jackets", "price": 49.99, "stock": 40, "attributes": {"waterproof": False, "color": "red", "insulated": False}},

    # Sleeping bags
    {"sku": "BAG-001", "name": "CozyNight 20F Sleeping Bag", "description": "Synthetic-fill sleeping bag rated to 20°F, water-resistant shell.", "category": "Sleeping Bags", "price": 89.99, "stock": 25, "attributes": {"waterproof": False, "temp_rating_f": 20}},
    {"sku": "BAG-002", "name": "Glacier Zero-Degree Down Bag", "description": "Premium down sleeping bag rated to 0°F for winter expeditions.", "category": "Sleeping Bags", "price": 279.99, "stock": 7, "attributes": {"waterproof": False, "temp_rating_f": 0}},
    {"sku": "BAG-003", "name": "Summer Trekker 40F Bag", "description": "Lightweight summer bag rated to 40°F.", "category": "Sleeping Bags", "price": 59.99, "stock": 38, "attributes": {"waterproof": False, "temp_rating_f": 40}},

    # Camp stoves
    {"sku": "STOVE-001", "name": "QuickBoil Backpacking Stove", "description": "Compact canister stove, boils water in under 3 minutes.", "category": "Camp Stoves", "price": 44.99, "stock": 29, "attributes": {"fuel_type": "canister"}},
    {"sku": "STOVE-002", "name": "TrailChef 2-Burner Camp Stove", "description": "Two-burner propane stove for car camping.", "category": "Camp Stoves", "price": 79.99, "stock": 16, "attributes": {"fuel_type": "propane"}},

    # Water bottles / hydration
    {"sku": "BOTL-001", "name": "InsulatedFlask 32oz Bottle", "description": "Double-wall insulated stainless steel bottle, keeps cold 24 hours.", "category": "Water Bottles", "price": 29.99, "stock": 60, "attributes": {"waterproof": True, "capacity_oz": 32}},
    {"sku": "BOTL-002", "name": "TrailFilter Squeeze Bottle", "description": "Bottle with built-in water filter for backcountry use.", "category": "Water Bottles", "price": 34.99, "stock": 41, "attributes": {"waterproof": True, "capacity_oz": 24}},

    # Headlamps
    {"sku": "LAMP-001", "name": "NightTrail 300-Lumen Headlamp", "description": "Rechargeable headlamp, water-resistant, 300-lumen max output.", "category": "Headlamps", "price": 39.99, "stock": 44, "attributes": {"waterproof": True, "lumens": 300}},
    {"sku": "LAMP-002", "name": "BaseCamp Lantern Headlamp Combo", "description": "Dual-mode headlamp and hanging lantern for camp use.", "category": "Headlamps", "price": 27.99, "stock": 35, "attributes": {"waterproof": False, "lumens": 150}},

    # Gloves
    {"sku": "GLOV-001", "name": "AllSeason Waterproof Gloves", "description": "Insulated waterproof gloves for cold, wet weather hiking.", "category": "Gloves", "price": 34.99, "stock": 26, "attributes": {"waterproof": True, "insulated": True}},
    {"sku": "GLOV-002", "name": "TrailGrip Lightweight Gloves", "description": "Thin, breathable gloves for mild-weather trail use.", "category": "Gloves", "price": 19.99, "stock": 50, "attributes": {"waterproof": False, "insulated": False}},

    # Socks
    {"sku": "SOCK-001", "name": "MerinoTrek Hiking Socks (2-pack)", "description": "Moisture-wicking merino wool hiking socks, water-resistant blend.", "category": "Socks", "price": 18.99, "stock": 70, "attributes": {"waterproof": False, "material": "merino wool"}},

    # Trekking poles
    {"sku": "POLE-001", "name": "SteadyStep Carbon Trekking Poles", "description": "Adjustable carbon fiber trekking poles, pair.", "category": "Trekking Poles", "price": 64.99, "stock": 23, "attributes": {"material": "carbon fiber", "weight_grams": 430}},
]


def seed_if_empty(db: Session):
    """Populate the catalog only if it's currently empty, so re-starting the
    backend doesn't create duplicate rows on every restart."""
    existing_count = db.query(models.Product).count()
    if existing_count > 0:
        return existing_count

    for item in PRODUCTS:
        db.add(models.Product(**item))
    db.commit()
    return len(PRODUCTS)
