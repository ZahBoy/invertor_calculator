"""JSON API калькулятора інверторів.

Побудований за тими самими принципами, що й PokeAPI з пари:
- відповіді у форматі JSON;
- списки посторінково: limit / offset, ключі count / next / previous / results;
- 404, якщо об'єкта немає, і 400, якщо параметр неправильний.

Уся логіка (каталог, діапазони, розрахунок ризику) береться з script.py,
тут лише перевірка запиту і перетворення результату у словники.
Запускати з кореня репозиторію (шляхи до data/ відносні).
"""
from urllib.parse import urlencode

import script

VOLTAGES = (24, 48)
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_UNITS = 3

# script.py завантажує базу лише в своєму main(), тому при імпорті вантажимо її самі
if not script.CATALOG:
    script.CATALOG = script.load_catalog()


class ApiError(Exception):
    """Помилка, яку API віддає клієнту як {"error": "..."} з HTTP-кодом."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def param(query, name, default=None):
    """Перше значення параметра з parse_qs (там кожне значення - список)."""
    return query.get(name, [default])[0]


def to_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"Параметр {name} має бути цілим числом.")


def read_voltage(value):
    voltage = to_int(value, "voltage")
    if voltage not in VOLTAGES:
        raise ApiError(400, "Напруга (voltage) може бути тільки 24 або 48.")
    return voltage


def model_json(model):
    return {
        "id": model.id,
        "name": model.name,
        "power_w": model.power_w,
        "price": model.price,
        "source": model.source,
        "voltage": model.voltage,
    }


def option_json(option, rank):
    choice = option.choice
    return {
        "rank": rank,
        "units": choice.units,
        "name": choice.name,
        "power_w": choice.power_w,
        "unit_price": choice.unit_price,
        "spent": choice.spent,
        "reliability": choice.reliability,
        "failure": round(option.failure, 6),
        "risk": round(option.risk),
        "over_budget": option.over_budget,
    }


class InverterAPI:
    """Обробляє запити до /api/... і повертає пару (HTTP-код, словник)."""

    def handle_get(self, path, query):
        try:
            return 200, self.route_get(path.rstrip("/"), query)
        except ApiError as error:
            return error.status, {"error": error.message}

    def handle_post(self, path, body):
        try:
            if path.rstrip("/") != "/api/calculate":
                raise ApiError(404, f"Немає такого ендпоінта: {path}")
            return 200, self.calculate(body)
        except ApiError as error:
            return error.status, {"error": error.message}

    def route_get(self, path, query):
        if path == "/api":
            return self.index()
        if path == "/api/bands":
            return self.bands(query)
        if path == "/api/models":
            return self.models(query)
        if path.startswith("/api/models/"):
            return self.model(path.rsplit("/", 1)[1])
        raise ApiError(404, f"Немає такого ендпоінта: {path}")

    def index(self):
        return {
            "bands": "/api/bands?voltage=48",
            "models": "/api/models?voltage=48&band=6&limit=20&offset=0",
            "model": "/api/models/{id}",
            "calculate": "POST /api/calculate",
        }

    def bands(self, query):
        voltage = read_voltage(param(query, "voltage"))
        counts, default = script.bands_for(voltage)
        return {
            "voltage": voltage,
            "default": default,
            "bands": [{"band": band, "label": script.band_label(band), "count": count}
                      for band, count in counts],
        }

    def models(self, query):
        voltage = read_voltage(param(query, "voltage"))
        band = param(query, "band")
        if band is None:
            found = [m for m in script.CATALOG if m.voltage == voltage]
        else:
            found = script.models_for(voltage, to_int(band, "band"))
        max_price = param(query, "max_price")
        if max_price is not None:
            limit_price = to_int(max_price, "max_price")
            found = [m for m in found if m.price <= limit_price]

        limit = to_int(param(query, "limit", DEFAULT_LIMIT), "limit")
        offset = to_int(param(query, "offset", 0), "offset")
        if not 1 <= limit <= MAX_LIMIT or offset < 0:
            raise ApiError(400, f"limit має бути від 1 до {MAX_LIMIT}, offset - не менше 0.")

        def page_url(new_offset):
            params = {k: v[0] for k, v in query.items()}
            params.update(limit=limit, offset=new_offset)
            return "/api/models?" + urlencode(params)

        return {
            "count": len(found),
            "next": page_url(offset + limit) if offset + limit < len(found) else None,
            "previous": page_url(max(0, offset - limit)) if offset > 0 else None,
            "results": [model_json(m) for m in found[offset:offset + limit]],
        }

    def model(self, raw_id):
        model_id = to_int(raw_id, "id")
        if not 0 <= model_id < len(script.CATALOG):
            raise ApiError(404, f"Моделі з id {model_id} немає.")
        return model_json(script.CATALOG[model_id])

    def calculate(self, body):
        """Тіло запиту:
        {"voltage": 48, "band": 6, "budget": 50000,
         "variants": [{"units": 1, "model_id": 186, "reliability": 0.9},
                      {"units": 2, "price": 19800, "reliability": 0.7}]}
        Варіант без model_id - це Noname, для нього потрібна ціна.
        """
        if not isinstance(body, dict):
            raise ApiError(400, "Тіло запиту має бути JSON-об'єктом.")
        voltage = read_voltage(body.get("voltage"))
        band = to_int(body.get("band"), "band")
        if band not in dict(script.bands_for(voltage)[0]):
            raise ApiError(400, f"Для {voltage} В немає моделей у діапазоні {script.band_label(band)}.")
        budget = to_int(body.get("budget"), "budget")
        if budget <= 0:
            raise ApiError(400, "Бюджет (budget) має бути більшим за 0.")
        variants = body.get("variants")
        if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_UNITS:
            raise ApiError(400, f"variants - це список від 1 до {MAX_UNITS} варіантів.")

        allowed_ids = {m.id for m in script.models_for(voltage, band)}
        rows = []
        for variant in variants:
            if not isinstance(variant, dict):
                raise ApiError(400, "Кожен варіант має бути JSON-об'єктом.")
            units = to_int(variant.get("units"), "units")
            if not 1 <= units <= MAX_UNITS:
                raise ApiError(400, f"units має бути від 1 до {MAX_UNITS}.")
            model_id = variant.get("model_id")
            if model_id is not None:
                model_id = to_int(model_id, "model_id")
                if model_id not in allowed_ids:
                    raise ApiError(400, f"Модель {model_id} не з {voltage} В / {script.band_label(band)}.")
            rows.append({"units": units, "id": model_id,
                         "price": variant.get("price"), "reliability": variant.get("reliability")})

        try:
            result = script.calculate(band, budget, rows)
        except ValueError as error:  # script.read_choice пояснює, що не так з варіантом
            raise ApiError(400, str(error))

        return {
            "voltage": voltage,
            "band": band,
            "budget": budget,
            "collapsed": result["collapsed"],
            "options": [option_json(option, rank) for option, rank in result["ordered"]],
            "reliability_after_5_years": [
                {"units": units, "label": label, "value": round(at, 6)}
                for units, label, _values, at in result["curves"]
            ],
        }
