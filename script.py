import csv
import html
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


FILE_24 = "data/Invertor_24V.csv"
FILE_48 = "data/Invertor_48V.csv"
TEMPLATES = "template/"
HORIZON = 5
HOST, PORT = "127.0.0.1", 8000
CATALOG = []
COLORS = {1: "#010101", 2: "#F17B77", 3: "#64A587"}
MUTED = "#5E5A57"
GRID = "#EBCFC2"
RANK_TEXT = {"best": "найкращий", "mid": "проміжний", "worst": "найгірший"}




class Model:        #моделька для будь-якого інвертора
    def __init__(self, name: str, power_w: int, price: int, source: str, voltage: int, id: int = 0):
        self.name = name
        self.power_w = power_w
        self.price = price
        self.source = source
        self.voltage = voltage
        self.id = id

class Choice:       #моделька для інверторів, які обирає користувач
    def __init__(self, name: str, units: int, unit_price: int, reliability: float, power_w: int):
        self.name = name
        self.units = units
        self.unit_price = unit_price
        self.reliability = reliability
        self.power_w = power_w
        self.spent = units * unit_price


class Option:
    def __init__(self, choice, failure: float, risk: float, budget: int):
        self.choice = choice
        self.failure = failure
        self.risk = risk
        self.budget = budget
        self.over_budget = choice.spent > budget

#БЛОК ФОРМАТУВАННЯ ЧИСЕЛ ДЛЯ НАДІЙНОСТІ ТА РОБОТИ З ТАБЛИЦЕЮ----------------------------------------------------------------------------------------------------

def parse_number(value):
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("грн", "").replace("%", "")
    if text == "" or text.lower() == "nan":
        return None
    return float(text.replace(",", "."))

def parse_reliability(value):
    number = parse_number(value)
    if number is None:
        return None
    if 1.0 < number <= 100.0:
        number /= 100.0
    if not 0.0 < number <= 1.0:
        raise ValueError(number)
    return number

def parse_power(value):
    digits = ""
    for i in str(value or ""):
        if i.isdigit():
            digits += i
        elif digits:
            break
    return int(digits) if digits else 0


def parse_price(value):
    try:
        number = parse_number(value)
    except ValueError:
        return 0
    return 0 if number is None else int(round(number))


def money(value):
    return f"{round(value):,.0f}".replace(",", " ") + " грн"



def price_text(value):
    return f"{value:,}".replace(",", " ")


def percent(value):
    return f"{value * 100:.1f}".replace(".", ",") + "%"

#ЧИТКА ТАБЛИЦЬ-----------------------------------------------------------------------------------


def load_file(path, voltage):
    with open(path, encoding="utf-8-sig", newline="") as f:

        rows = []
        for raw in csv.DictReader(f, delimiter=";"):
            name = raw["Марка інвертора"].strip()
            power = parse_power(raw["Потужність"])
            price = parse_price(raw["Ціна"])
            source = raw["Джерело (сайт)"].strip()

            if name and power > 0 and price > 0:
                rows.append(Model(name, power, price, source, voltage))

    return rows

def load_catalog():
    try:
        catalog = load_file(FILE_24, 24) + load_file(FILE_48, 48)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Немає файлу: {error.filename}") from error
    for index, item in enumerate(catalog):
        item.id = index
    return catalog

#Фільтрація інверторів за потужніст.-----------------------------------------------------------------------------------

def power_band(power_w):
    return max(0, power_w) // 1000


def band_label(band_kw):
    return f"{band_kw}.0-{band_kw + 1}.0 кВт"


def in_band(power_w, band_kw):
    return power_band(power_w) == band_kw

def models_for(voltage, band):
    found = [m for m in CATALOG if m.voltage == voltage and in_band(m.power_w, band)]
    return sorted(found, key=lambda m: (m.power_w, m.price, m.name))


def bands_for(voltage):
    counts = {}
    for item in CATALOG:
        if item.voltage == voltage:
            band = power_band(item.power_w)
            counts[band] = counts.get(band, 0) + 1
    default = max(counts, key=lambda b: (counts[b], -abs(b - 5))) if counts else None
    return sorted(counts.items()), default

def suggest(models, units, budget):
    fitting = [m for m in models if m.price * units <= budget]
    return min(fitting or models, key=lambda m: (abs(m.price * units - budget), m.price, m.name))


#Мат розрахунок------------------------------------------------------------------------------

def reliability_at(reliability, years):
    if years <= 0 or reliability >= 1.0:
        return 1.0
    if reliability <= 0.0:
        return 0.0
    return reliability ** (years / HORIZON)

def plain_p(value):
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".00"
    elif len(text.split(".")[1]) < 2:
        text += "0"
    return text.replace(".", ",")

def failure_probability(reliability, units):
    return (1.0 - reliability) ** units


def failure_formula(reliability, units):
    return " × ".join([f"(1 − {plain_p(reliability)})"] * units)

def evaluate(choice, budget):

    failure = failure_probability(choice.reliability, choice.units)
    return Option(choice, failure, failure * choice.spent, budget)

def shown_options(options):
    if len(options) < 3:
        return options, False
    a, b = options[1].choice, options[2].choice
    if a.name == "Noname" or a.name != b.name:
        return options, False
    kept = options[1] if options[1].risk <= options[2].risk else options[2]
    return [options[0], kept], True


def ranks(count):
    if count <= 1:
        return ["best"] * count
    return ["best"] + ["mid"] * (count - 2) + ["worst"]

def curve(option: Option, points: int = 90):
    span = HORIZON * 1.25
    values = []
    for step in range(points):
        unit = reliability_at(option.choice.reliability, span * step / (points - 1))
        values.append(1.0 - (1.0 - unit) ** option.choice.units)
    return values

def read_choice(row: dict, power_w: int) -> Choice:
    units = int(row["units"])
    title = f"Варіант {units}"
    model_id = row.get("id")
    if model_id is None:
        price = parse_price(row.get("price"))
        if price <= 0:
            raise ValueError(f"{title}: вкажіть ціну однієї штуки.")
    try:
        reliability = parse_reliability(row.get("reliability"))
    except ValueError:
        reliability = None
    if reliability is None:
        raise ValueError(f"{title}: вкажіть надійність від 0 до 1 (0,92 означає 92%).")
    if model_id is None:
        return Choice("Noname", units, price, reliability, power_w)
    item = CATALOG[int(model_id)]
    return Choice(item.name, units, item.price, reliability, item.power_w)

def calculate(band: int | None, budget: int, rows: list[dict]) -> dict:
    if band is None:
        raise ValueError("У базі цієї напруги немає інверторів.")
    options = [evaluate(read_choice(row, band * 1000), budget) for row in rows]
    visible, collapsed = shown_options(options)
    ordered = sorted(visible, key=lambda o: (o.risk, o.choice.spent, o.choice.units))
    return {
        "collapsed": collapsed,
        "ordered": list(zip(ordered, ranks(len(ordered)))),
        "curves": [
            (o.choice.units, f"{o.choice.units} × {o.choice.name}", curve(o), 1.0 - o.failure)
            for o in visible
        ],
    }


#Побудова графіка(ШІ)--------------------------------------------------------------------------------------------------
esc = html.escape


def result_block(data: dict) -> str:
    parts = []
    for option, rank in data["ordered"]:
        choice = option.choice
        power = f", {choice.power_w} Вт" if choice.power_w > 0 else ""
        note = " (більше, ніж є грошей)" if option.over_budget else ""
        parts.append(
            f'<p class="res {rank}">{choice.units} × {esc(choice.name)}{power}: '
            f"відмова {failure_formula(choice.reliability, choice.units)} = {percent(option.failure)}, "
            f"витрати {money(choice.spent)}, ризик {money(option.risk)}{note}"
            f"<b>{RANK_TEXT[rank]}</b></p>"
        )
    if data["collapsed"]:
        parts.append('<p class="collapsed-note">Варіанти 2 і 3 — той самий інвертор, '
                     "показано той, що з меншим ризиком.</p>")
    return "\n".join(parts)


def chart_svg(curves: list) -> str:
    """Графік у вигляді SVG: Python сам складає розмітку, бібліотеки не потрібні."""
    width, height, left, right, top, bottom = 640, 340, 52, 64, 16, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    span = HORIZON * 1.25
    low = max(0.0, min(1.0, min(min(c[2]) for c in curves)))
    if 1.0 - low < 0.02:
        low = 0.98

    def x_of(years: float) -> float:
        return left + plot_w * years / span

    def y_of(value: float) -> float:
        value = max(low, min(1.0, value))
        return top + plot_h * (1.0 - (value - low) / (1.0 - low))

    def pct(value: float) -> str:
        return f"{value * 100:.1f}%"

    s = [f'<svg viewBox="0 0 {width} {height}" role="img" font-family="Segoe UI, system-ui, sans-serif" '
         f'aria-label="Графік надійності варіантів у часі">']
    for i in range(6):
        v = low + (1.0 - low) * i / 5
        y = y_of(v)
        s.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
        s.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="{MUTED}">{pct(v)}</text>')
    for year in range(7):
        s.append(f'<text x="{x_of(year):.1f}" y="{top + plot_h + 16}" text-anchor="middle" '
                 f'font-size="11" fill="{MUTED}">{year}</text>')
    s.append(f'<text x="{left + plot_w / 2:.1f}" y="{height - 6}" text-anchor="middle" '
             f'font-size="11" fill="{MUTED}">Роки від покупки</text>')

    hx = x_of(HORIZON)
    s.append(f'<line x1="{hx:.1f}" x2="{hx:.1f}" y1="{top}" y2="{top + plot_h}" '
             f'stroke="{MUTED}" stroke-dasharray="3 4"/>')
    s.append(f'<text x="{hx + 4:.1f}" y="{top + 10}" font-size="11" fill="{MUTED}">{HORIZON:g} р.</text>')

    for units, _label, values, _at in curves:
        points = " ".join(
            f"{x_of(span * i / (len(values) - 1)):.1f},{y_of(v):.1f}" for i, v in enumerate(values)
        )
        s.append(f'<polyline fill="none" stroke="{COLORS[units]}" stroke-width="2.6" '
                 f'stroke-linejoin="round" points="{points}"/>')

    # Підписи точних відсотків на пунктирі; розсуваємо, щоб не налягали.
    previous = -1e9
    for y, (units, _label, _values, at) in sorted(((y_of(c[3]), c) for c in curves), key=lambda item: item[0]):
        ty = max(y, previous + 15)
        previous = ty
        color = COLORS[units]
        s.append(f'<circle cx="{hx:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        s.append(f'<line x1="{hx + 4:.1f}" y1="{y:.1f}" x2="{hx + 10:.1f}" y2="{ty:.1f}" stroke="{color}"/>')
        s.append(f'<text x="{hx + 12:.1f}" y="{ty + 4:.1f}" font-size="12" font-weight="600" '
                 f'fill="#010101">{pct(at)}</text>')

    # Легенда в нижньому лівому куті графіка.
    for i, (units, label, _values, _at) in enumerate(curves):
        y = top + plot_h - 10 - 18 * (len(curves) - 1 - i)
        s.append(f'<line x1="{left + 10}" x2="{left + 28}" y1="{y}" y2="{y}" '
                 f'stroke="{COLORS[units]}" stroke-width="3"/>')
        s.append(f'<text x="{left + 34}" y="{y + 4}" font-size="12" fill="#010101">{esc(label)}</text>')
    s.append("</svg>")
    return "\n".join(s)


def options_html(items: list[tuple[str, str]], selected: str) -> str:
    return "".join(
        f'<option value="{esc(value)}"{" selected" if value == selected else ""}>{esc(text)}</option>'
        for value, text in items
    )


def variant_rows(rows: list[dict], models: list[Model], budget: int) -> str:
    titles = {
        1: "1. Один інвертор",
        2: "2. Два однакові: один працює, другий лежить у запасі",
        3: "3. Три однакові: один працює, два лежать у запасі",
    }
    out = []
    for row in rows:
        n, model_id = row["units"], row["id"]
        items = [("noname", "Noname — вписати ціну з сайту")] + [
            (str(m.id), f"{m.name} — {m.power_w} Вт — {price_text(m.price)} грн") for m in models
        ]
        selected = "noname" if model_id is None else str(model_id)
        if model_id is None:
            price_input = (f'<input class="price manual" name="p{n}" inputmode="numeric" '
                           f'placeholder="ціна" value="{esc(row["price"])}">')
            caption, price = "Ціна з сайту", parse_price(row["price"])
            note = "Моделі немає в базі: впишіть ціну однієї штуки і надійність."
        else:
            item = CATALOG[model_id]
            price_input = (f'<input class="price" name="p{n}" value="{price_text(item.price)}" readonly>')
            caption, price = "Ціна з бази", item.price
            note = f"{item.power_w} Вт, ціна з {esc(item.source)}. Надійності в прайсі немає — впишіть її самі."
        if price > 0:
            spent = price * n
            over = spent > budget
            total = (f'<div class="total{" over" if over else ""}">разом {money(spent)}'
                     f'{" — більше, ніж є грошей" if over else ""}</div>')
        else:
            total = '<div class="total">разом —</div>'
        out.append(f"""
      <article class="variant">
        <h3>{titles[n]}</h3>
        <div class="row">
          <label class="field grow">Модель <select name="m{n}">{options_html(items, selected)}</select></label>
          <label class="field">{caption}, грн {price_input}</label>
          <label class="field">Надійність <input class="rel" name="r{n}" inputmode="decimal" placeholder="0,92" value="{esc(row['reliability'])}"></label>
          {total}
        </div>
        <p class="note">{note}</p>
      </article>""")
    return "\n".join(out)

#Все що стосується html-сторінки----------------------------------------------------------------------------------------------------------------


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def fill(source, **values):
    for key, value in values.items():
        source = source.replace("$" + key, str(value))
    return source


def page(title, body, active):
    return fill(
        read(TEMPLATES + "layout.html"),
        title=title,
        calc_cls=' class="active"' if active == "calc" else "",
        help_cls="",
        body=body,
    )


def first(form, key, default=""):
    return form.get(key, [default])[0]


def render_index(form):
    action = first(form, "action")

    try:
        voltage = int(first(form, "voltage", "48"))
    except ValueError:
        voltage = 48

    if voltage not in (24, 48):
        voltage = 48

    budget = min(2_000_000, max(1_000, parse_price(first(form, "budget", "50000")) or 50_000))

    bands, default_band = bands_for(voltage)
    raw_band = first(form, "band")
    valid = {b for b, _count in bands}
    band = int(raw_band) if raw_band.isdigit() and int(raw_band) in valid else default_band

    models = models_for(voltage, band) if band is not None else []
    known = {m.id for m in models}
    suggested = {n: suggest(models, n, budget).id for n in (1, 2, 3)} if models else {}

    rows = []

    for n in (1, 2, 3):
        raw = first(form, f"m{n}")

        if raw == "noname":
            model_id = None
        elif raw.isdigit() and int(raw) in known:
            model_id = int(raw)
        else:
            model_id = suggested.get(n)

        rows.append({
            "units": n,
            "id": model_id,
            "price": first(form, f"p{n}"),
            "reliability": first(form, f"r{n}")
        })

    error = ""
    result = '<p class="empty">Тут з’являться рядки порівняння.</p>'
    chart = '<p class="empty">Після «Розрахувати» тут з’являться криві кожного варіанта.</p>'

    if action == "calc":
        try:
            data = calculate(band, budget, rows)
        except ValueError as problem:
            error = f'<p class="error" role="alert">{esc(str(problem))}</p>'
        else:
            result = result_block(data)
            chart = chart_svg(data["curves"])

    body = fill(
        read(TEMPLATES + "index.html"),
        budget=budget,
        voltage_options=options_html([("24", "24 В"), ("48", "48 В")], str(voltage)),
        band_options=options_html(
            [(str(b), f"{band_label(b)} · у базі {count}") for b, count in bands],
            str(band)
        ),
        error=error,
        variants=variant_rows(rows, models, budget),
        chart=chart,
        result=result,
    )

    return page("Один, два чи три інвертори", body, "calc")


# Сервер

class Handler(BaseHTTPRequestHandler):

    def _send(self, status, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            return self._send(200, render_index({}), "text/html")

        if path == "/style.css":
            return self._send(200, read("static/style.css"), "text/css")

        self._send(
            404,
            page("Не знайдено", '<section class="intro"><h1>Сторінку не знайдено</h1></section>', ""),
            "text/html"
        )

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        self._send(200, render_index(form), "text/html")

    def log_message(self, *_args):
        pass


def main():
    global CATALOG

    try:
        CATALOG = load_catalog()
    except FileNotFoundError as error:
        raise SystemExit(str(error)) from error

    server = HTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"

    print(f"Сайт працює: {url} (зупинити — Ctrl+C), у базі {len(CATALOG)} інверторів")

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nЗупинено.")


if __name__ == "__main__":
    main()
