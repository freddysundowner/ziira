"""Reading a vehicle identification number (VIN): the make from the maker code, the model year, and whether the check
digit adds up. No lookup service is used: this is what the number itself says. The model and trim are not in a VIN
in any way that works worldwide, so they are left for the person to type."""

from dataclasses import dataclass
from datetime import date

ALLOWED = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")          # I, O and Q are never used
_VALUES = {**{str(d): d for d in range(10)},
           **dict(zip("ABCDEFGH", range(1, 9), strict=True)), **dict(zip("JKLMN", range(1, 6), strict=True)),
           "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10), strict=True))}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
_YEARS = "ABCDEFGHJKLMNPRSTVWXY123456789"                   # position 10: 1980 or 2010 for 'A', and so on

# The first three characters (the world manufacturer code); a two-character entry covers every code that starts with it.
_MAKERS = {
    "JT": "Toyota", "JN": "Nissan", "JH": "Honda", "JM": "Mazda", "JF": "Subaru", "JS": "Suzuki", "JA": "Isuzu",
    "JL": "Mitsubishi Fuso", "MR": "Toyota", "MM": "Mahindra", "MA": "Mahindra", "MB": "Mitsubishi",
    "KM": "Hyundai", "KN": "Kia", "KL": "Daewoo", "5N": "Hyundai", "1G": "General Motors", "2G": "General Motors",
    "3G": "General Motors", "1F": "Ford", "2F": "Ford", "3F": "Ford", "1C": "Chrysler", "2C": "Chrysler",
    "1H": "Honda", "2H": "Honda", "5Y": "Mazda", "4T": "Toyota", "5T": "Toyota", "2T": "Toyota", "1N": "Nissan",
    "WB": "BMW", "WD": "Mercedes-Benz", "WM": "Mercedes-Benz", "WA": "Audi", "WV": "Volkswagen", "WF": "Ford",
    "W0": "Opel", "VF": "Renault", "VR": "Peugeot", "VS": "Seat", "VW": "Volkswagen", "ZF": "Fiat", "ZA": "Alfa Romeo",
    "ZH": "Fiat", "SA": "Land Rover", "SB": "Toyota", "SC": "Lotus", "SD": "Bentley", "SJ": "Ford", "SH": "Honda",
    "YV": "Volvo", "YS": "Saab", "TM": "Skoda", "VN": "Nissan", "LV": "Chery", "LH": "Hyundai", "LF": "Geely",
    "LS": "Changan", "LG": "Dongfeng", "LB": "Beijing Auto", "LZ": "Zhongxing", "LM": "Jiangling", "LT": "Isuzu",
    "AA": "Volkswagen", "AC": "Mazda", "AH": "Isuzu", "AJ": "Toyota", "MP": "Isuzu", "NM": "Hyundai", "TR": "Mazda",
}
_MAKERS3 = {"1HG": "Honda", "2HG": "Honda", "JTD": "Toyota", "JTM": "Toyota", "JHM": "Honda", "SAJ": "Jaguar",
            "SAL": "Land Rover", "WP0": "Porsche", "WP1": "Porsche", "JTE": "Toyota", "JTH": "Lexus", "JN1": "Nissan",
            "JN8": "Nissan", "JMZ": "Mazda", "JF1": "Subaru", "JF2": "Subaru", "JS3": "Suzuki", "JS2": "Suzuki",
            "TRU": "Audi", "WAU": "Audi", "WBA": "BMW", "WBS": "BMW M", "WDD": "Mercedes-Benz", "WVW": "Volkswagen",
            "WVG": "Volkswagen", "WF0": "Ford", "VF1": "Renault", "VF3": "Peugeot", "VF7": "Citroën", "ZFA": "Fiat",
            "ZAR": "Alfa Romeo", "KMH": "Hyundai", "KNA": "Kia", "KND": "Kia", "KNM": "Kia", "MHF": "Toyota",
            "MHR": "Honda", "MMM": "Chevrolet", "MNB": "Ford", "AHT": "Toyota", "SJN": "Nissan", "NMT": "Toyota"}


@dataclass(frozen=True)
class VinReading:
    vin: str
    valid_shape: bool              # 17 characters, none of I, O, Q
    make: str | None
    year: int | None
    check_digit_ok: bool | None    # None when the shape is wrong; many non-American makers do not use the check digit
    problem: str | None


def clean(raw: str) -> str:
    return "".join(raw.split()).upper()


def check_digit_ok(vin: str) -> bool:
    total = sum(_VALUES[c] * w for c, w in zip(vin, _WEIGHTS, strict=True))
    want = total % 11
    return vin[8] == ("X" if want == 10 else str(want))


def model_year(vin: str, today: date | None = None) -> int | None:
    """The year coded in position 10. The code repeats every 30 years, so the later one is used unless it would be
    more than one year in the future. Position 7 (a letter on newer American cars, a digit on older ones) is not
    used, because makers outside America do not follow that rule."""
    index = _YEARS.find(vin[9])
    if index < 0:
        return None
    this = (today or date.today()).year
    year = 2010 + index
    while year > this + 1:
        year -= 30
    return year


def make_of(vin: str) -> str | None:
    return _MAKERS3.get(vin[:3]) or _MAKERS.get(vin[:2])


def read(raw: str, today: date | None = None) -> VinReading:
    vin = clean(raw)
    if len(vin) != 17:
        return VinReading(vin, False, None, None, None, f"A VIN has 17 characters; this has {len(vin)}")
    bad = sorted(set(vin) - ALLOWED)
    if bad:
        return VinReading(vin, False, None, None, None, f"A VIN never contains {', '.join(bad)}")
    return VinReading(vin, True, make_of(vin), model_year(vin, today), check_digit_ok(vin), None)
