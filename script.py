
FILE_24 = "data/Invertor_24V.csv"
FILE_48 = "data/Invertor_48V.csv"
TEMPLATES = "template/"

import csv

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





