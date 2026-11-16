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


class InverterAPI:
    """Обробляє запити до /api/... і повертає пару (HTTP-код, словник)."""

    def handle_get(self, path, query):
        try:
            return 200, self.route_get(path.rstrip("/"), query)
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
