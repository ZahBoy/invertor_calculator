
FILE_24 = "Invertor_24V.csv"
FILE_48 = "Invertor_48V.csv"

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

#----------------------------------------------------------------------------------------------------

def parse_number(value):
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("грн", "").replace("%", "")
    if text == "" or text.lower() == "nan":
        return None
    return float(text.replace(",", "."))