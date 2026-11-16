"""Клієнт нашого API - так само, як на парі працювали з PokeAPI.

Спочатку запустіть сервер:  python API_support.py
Потім у другому терміналі:   python api_client.py
"""
import requests

BASE_URL = "http://127.0.0.1:8001"


def get_json(url, params=None):
    """GET-запит; 404 означає «такого немає» -> None, інші помилки - виняток."""
    response = requests.get(url, params=params, timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def get_all_models(voltage, band, limit=20):
    """Збирає всі сторінки списку, переходячи за посиланням next."""
    models = []
    page = get_json(f"{BASE_URL}/api/models",
                    {"voltage": voltage, "band": band, "limit": limit, "offset": 0})
    while page is not None:
        models.extend(page["results"])
        page = get_json(BASE_URL + page["next"]) if page["next"] else None
    return models


def calculate(voltage, band, budget, variants):
    response = requests.post(f"{BASE_URL}/api/calculate", timeout=10,
                             json={"voltage": voltage, "band": band,
                                   "budget": budget, "variants": variants})
    data = response.json()
    if response.status_code != 200:
        raise ValueError(data["error"])
    return data


def main():
    voltage, budget = 48, 50000
    bands = get_json(f"{BASE_URL}/api/bands", {"voltage": voltage})
    band = bands["default"]
    print(f"Діапазони для {voltage} В:", ", ".join(f"{b['label']} ({b['count']})" for b in bands["bands"]))

    models = get_all_models(voltage, band, limit=10)
    print(f"\nУ діапазоні {band}.0-{band + 1}.0 кВт моделей: {len(models)}")
    cheapest = sorted(models, key=lambda m: m["price"])[:3]
    for m in cheapest:
        print(f"  #{m['id']} {m['name']} - {m['price']} грн ({m['source']})")

    print("\nМодель з id 9999:", get_json(f"{BASE_URL}/api/models/9999"))

    # той самий вибір, що на сайті: 1 дорогий, 2 середні або 3 дешеві інвертори
    variants = [
        {"units": 1, "model_id": cheapest[-1]["id"], "reliability": 0.92},
        {"units": 2, "model_id": cheapest[1]["id"], "reliability": 0.80},
        {"units": 3, "model_id": cheapest[0]["id"], "reliability": 0.70},
    ]
    result = calculate(voltage, band, budget, variants)
    print(f"\nБюджет {budget} грн, ризик = ймовірність відмови x витрати:")
    for o in result["options"]:
        over = "  (більше бюджету)" if o["over_budget"] else ""
        print(f"  {o['rank']:>5}: {o['units']} x {o['name']} - витрати {o['spent']} грн, "
              f"відмова {o['failure']:.1%}, ризик {o['risk']} грн{over}")


if __name__ == "__main__":
    main()
