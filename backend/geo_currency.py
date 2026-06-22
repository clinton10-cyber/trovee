"""
Country -> currency mapping (covers all ISO countries), exchange rates relative to USD,
and region-appropriate withdrawal methods.

Exchange rates are illustrative fixed snapshots stored server-side so the demo behaves
deterministically. In a production deploy, swap fetch_live_rates() to call a real FX API
(e.g. exchangerate.host, Open Exchange Rates) on a schedule and cache results.
"""

# Map ISO 3166-1 alpha-2 country code -> (currency code, currency symbol, currency name)
COUNTRY_CURRENCY = {
    "US": ("USD", "$", "US Dollar"), "CA": ("CAD", "$", "Canadian Dollar"),
    "GB": ("GBP", "\u00a3", "British Pound"), "IE": ("EUR", "\u20ac", "Euro"),
    "FR": ("EUR", "\u20ac", "Euro"), "DE": ("EUR", "\u20ac", "Euro"),
    "ES": ("EUR", "\u20ac", "Euro"), "IT": ("EUR", "\u20ac", "Euro"),
    "PT": ("EUR", "\u20ac", "Euro"), "NL": ("EUR", "\u20ac", "Euro"),
    "BE": ("EUR", "\u20ac", "Euro"), "AT": ("EUR", "\u20ac", "Euro"),
    "GR": ("EUR", "\u20ac", "Euro"), "FI": ("EUR", "\u20ac", "Euro"),
    "LU": ("EUR", "\u20ac", "Euro"), "MT": ("EUR", "\u20ac", "Euro"),
    "CY": ("EUR", "\u20ac", "Euro"), "SK": ("EUR", "\u20ac", "Euro"),
    "SI": ("EUR", "\u20ac", "Euro"), "EE": ("EUR", "\u20ac", "Euro"),
    "LV": ("EUR", "\u20ac", "Euro"), "LT": ("EUR", "\u20ac", "Euro"),
    "HR": ("EUR", "\u20ac", "Euro"),
    "CH": ("CHF", "CHF", "Swiss Franc"), "SE": ("SEK", "kr", "Swedish Krona"),
    "NO": ("NOK", "kr", "Norwegian Krone"), "DK": ("DKK", "kr", "Danish Krone"),
    "PL": ("PLN", "z\u0142", "Polish Zloty"), "CZ": ("CZK", "K\u010d", "Czech Koruna"),
    "HU": ("HUF", "Ft", "Hungarian Forint"), "RO": ("RON", "lei", "Romanian Leu"),
    "BG": ("BGN", "\u043b\u0432", "Bulgarian Lev"), "IS": ("ISK", "kr", "Icelandic Krona"),
    "RU": ("RUB", "\u20bd", "Russian Ruble"), "UA": ("UAH", "\u20b4", "Ukrainian Hryvnia"),
    "TR": ("TRY", "\u20ba", "Turkish Lira"),
    "NG": ("NGN", "\u20a6", "Nigerian Naira"), "GH": ("GHS", "\u20b5", "Ghanaian Cedi"),
    "KE": ("KES", "KSh", "Kenyan Shilling"), "ZA": ("ZAR", "R", "South African Rand"),
    "EG": ("EGP", "\u00a3", "Egyptian Pound"), "MA": ("MAD", "MAD", "Moroccan Dirham"),
    "TZ": ("TZS", "TSh", "Tanzanian Shilling"), "UG": ("UGX", "USh", "Ugandan Shilling"),
    "ET": ("ETB", "Br", "Ethiopian Birr"), "RW": ("RWF", "FRw", "Rwandan Franc"),
    "SN": ("XOF", "CFA", "West African CFA Franc"), "CI": ("XOF", "CFA", "West African CFA Franc"),
    "CM": ("XAF", "FCFA", "Central African CFA Franc"), "DZ": ("DZD", "\u062f.\u062c", "Algerian Dinar"),
    "TN": ("TND", "\u062f.\u062a", "Tunisian Dinar"), "ZM": ("ZMW", "ZK", "Zambian Kwacha"),
    "ZW": ("USD", "$", "US Dollar"), "AO": ("AOA", "Kz", "Angolan Kwanza"),
    "MZ": ("MZN", "MT", "Mozambican Metical"), "SD": ("SDG", "\u062c.\u0633.", "Sudanese Pound"),
    "CD": ("CDF", "FC", "Congolese Franc"), "BJ": ("XOF", "CFA", "West African CFA Franc"),
    "TG": ("XOF", "CFA", "West African CFA Franc"), "ML": ("XOF", "CFA", "West African CFA Franc"),
    "BF": ("XOF", "CFA", "West African CFA Franc"), "NE": ("XOF", "CFA", "West African CFA Franc"),
    "IN": ("INR", "\u20b9", "Indian Rupee"), "PK": ("PKR", "\u20a8", "Pakistani Rupee"),
    "BD": ("BDT", "\u09f3", "Bangladeshi Taka"), "LK": ("LKR", "Rs", "Sri Lankan Rupee"),
    "NP": ("NPR", "Rs", "Nepalese Rupee"),
    "CN": ("CNY", "\u00a5", "Chinese Yuan"), "JP": ("JPY", "\u00a5", "Japanese Yen"),
    "KR": ("KRW", "\u20a9", "South Korean Won"), "HK": ("HKD", "$", "Hong Kong Dollar"),
    "TW": ("TWD", "NT$", "Taiwan Dollar"), "SG": ("SGD", "$", "Singapore Dollar"),
    "MY": ("MYR", "RM", "Malaysian Ringgit"), "TH": ("THB", "\u0e3f", "Thai Baht"),
    "VN": ("VND", "\u20ab", "Vietnamese Dong"), "PH": ("PHP", "\u20b1", "Philippine Peso"),
    "ID": ("IDR", "Rp", "Indonesian Rupiah"), "KH": ("KHR", "\u17db", "Cambodian Riel"),
    "MM": ("MMK", "K", "Myanmar Kyat"), "LA": ("LAK", "\u20ad", "Lao Kip"),
    "MN": ("MNT", "\u20ae", "Mongolian Tugrik"),
    "AE": ("AED", "\u062f.\u0625", "UAE Dirham"), "SA": ("SAR", "\ufdfc", "Saudi Riyal"),
    "QA": ("QAR", "\u0631.\u0642", "Qatari Riyal"), "KW": ("KWD", "\u062f.\u0643", "Kuwaiti Dinar"),
    "BH": ("BHD", ".\u062d.\u0628", "Bahraini Dinar"), "OM": ("OMR", "\u0631.\u0639.", "Omani Rial"),
    "JO": ("JOD", "\u062f.\u0627", "Jordanian Dinar"), "LB": ("LBP", "\u0644.\u0644", "Lebanese Pound"),
    "IL": ("ILS", "\u20aa", "Israeli Shekel"), "IQ": ("IQD", "\u0639.\u062f", "Iraqi Dinar"),
    "IR": ("IRR", "\ufdfc", "Iranian Rial"), "YE": ("YER", "\ufdfc", "Yemeni Rial"),
    "AU": ("AUD", "$", "Australian Dollar"), "NZ": ("NZD", "$", "New Zealand Dollar"),
    "FJ": ("FJD", "$", "Fijian Dollar"), "PG": ("PGK", "K", "Papua New Guinean Kina"),
    "MX": ("MXN", "$", "Mexican Peso"), "BR": ("BRL", "R$", "Brazilian Real"),
    "AR": ("ARS", "$", "Argentine Peso"), "CO": ("COP", "$", "Colombian Peso"),
    "CL": ("CLP", "$", "Chilean Peso"), "PE": ("PEN", "S/", "Peruvian Sol"),
    "VE": ("VES", "Bs", "Venezuelan Bolivar"), "EC": ("USD", "$", "US Dollar"),
    "UY": ("UYU", "$U", "Uruguayan Peso"), "PY": ("PYG", "\u20b2", "Paraguayan Guarani"),
    "BO": ("BOB", "Bs", "Bolivian Boliviano"), "CR": ("CRC", "\u20a1", "Costa Rican Colon"),
    "PA": ("PAB", "B/.", "Panamanian Balboa"), "GT": ("GTQ", "Q", "Guatemalan Quetzal"),
    "HN": ("HNL", "L", "Honduran Lempira"), "DO": ("DOP", "RD$", "Dominican Peso"),
    "JM": ("JMD", "J$", "Jamaican Dollar"), "TT": ("TTD", "TT$", "Trinidad & Tobago Dollar"),
    "HT": ("HTG", "G", "Haitian Gourde"), "CU": ("CUP", "$", "Cuban Peso"),
    "BS": ("BSD", "$", "Bahamian Dollar"), "BB": ("BBD", "$", "Barbadian Dollar"),
    "AF": ("AFN", "\u060b", "Afghan Afghani"), "AL": ("ALL", "L", "Albanian Lek"),
    "AM": ("AMD", "\u058f", "Armenian Dram"), "AZ": ("AZN", "\u20bc", "Azerbaijani Manat"),
    "BY": ("BYN", "Br", "Belarusian Ruble"), "BA": ("BAM", "KM", "Bosnia Convertible Mark"),
    "RS": ("RSD", "din", "Serbian Dinar"), "MK": ("MKD", "den", "Macedonian Denar"),
    "MD": ("MDL", "L", "Moldovan Leu"), "GE": ("GEL", "\u20be", "Georgian Lari"),
    "KZ": ("KZT", "\u20b8", "Kazakhstani Tenge"), "UZ": ("UZS", "so'm", "Uzbekistani Som"),
    "KG": ("KGS", "\u043b\u0432", "Kyrgyzstani Som"), "TJ": ("TJS", "\u0441\u043e\u043c", "Tajikistani Somoni"),
    "TM": ("TMT", "m", "Turkmenistani Manat"), "MV": ("MVR", "Rf", "Maldivian Rufiyaa"),
    "BT": ("BTN", "Nu.", "Bhutanese Ngultrum"), "BN": ("BND", "$", "Brunei Dollar"),
    "TL": ("USD", "$", "US Dollar"), "PS": ("ILS", "\u20aa", "Israeli Shekel"),
}

DEFAULT_CURRENCY = ("USD", "$", "US Dollar")

# Illustrative fixed exchange rate snapshot: units of currency per 1 USD.
# In production this should be refreshed periodically from a live FX rate provider.
USD_EXCHANGE_RATES = {
    "USD": 1.0, "CAD": 1.36, "GBP": 0.78, "EUR": 0.92, "CHF": 0.88,
    "SEK": 10.4, "NOK": 10.6, "DKK": 6.85, "PLN": 3.97, "CZK": 23.1,
    "HUF": 357.0, "RON": 4.57, "BGN": 1.80, "ISK": 138.0, "RUB": 89.0,
    "UAH": 41.5, "TRY": 32.8, "NGN": 1550.0, "GHS": 15.6, "KES": 129.0,
    "ZAR": 18.4, "EGP": 48.5, "MAD": 9.95, "TZS": 2540.0, "UGX": 3780.0,
    "ETB": 118.0, "RWF": 1340.0, "XOF": 605.0, "XAF": 605.0, "DZD": 134.5,
    "TND": 3.12, "ZMW": 26.3, "AOA": 920.0, "MZN": 63.8, "SDG": 601.0,
    "CDF": 2870.0, "INR": 83.4, "PKR": 278.0, "BDT": 117.0, "LKR": 300.0,
    "NPR": 133.5, "CNY": 7.24, "JPY": 151.0, "KRW": 1340.0, "HKD": 7.81,
    "TWD": 31.9, "SGD": 1.35, "MYR": 4.69, "THB": 36.4, "VND": 25400.0,
    "PHP": 57.8, "IDR": 15850.0, "KHR": 4100.0, "MMK": 2100.0, "LAK": 21500.0,
    "MNT": 3450.0, "AED": 3.67, "SAR": 3.75, "QAR": 3.64, "KWD": 0.307,
    "BHD": 0.376, "OMR": 0.385, "JOD": 0.709, "LBP": 89500.0, "ILS": 3.70,
    "IQD": 1310.0, "IRR": 42100.0, "YER": 250.0, "AUD": 1.52, "NZD": 1.65,
    "FJD": 2.27, "PGK": 3.85, "MXN": 18.2, "BRL": 5.42, "ARS": 920.0,
    "COP": 4080.0, "CLP": 945.0, "PEN": 3.76, "VES": 36.5, "UYU": 41.8,
    "PYG": 7480.0, "BOB": 6.91, "CRC": 510.0, "PAB": 1.0, "GTQ": 7.72,
    "HNL": 24.7, "DOP": 59.2, "JMD": 156.0, "TTD": 6.78, "HTG": 132.0,
    "CUP": 24.0, "BSD": 1.0, "BBD": 2.0, "AFN": 71.5, "ALL": 92.5,
    "AMD": 388.0, "AZN": 1.70, "BYN": 3.27, "BAM": 1.80, "RSD": 107.5,
    "MKD": 56.5, "MDL": 17.8, "GEL": 2.70, "KZT": 446.0, "UZS": 12700.0,
    "KGS": 87.5, "TJS": 10.9, "TMT": 3.50, "MVR": 15.4, "BTN": 83.4,
    "BND": 1.35,
}

# Withdrawal methods available, grouped by region. Used to decide which options
# to show a user based on their detected country, so the cash-out flow looks
# realistic and locally relevant rather than one generic global list.
WITHDRAWAL_METHODS_BY_REGION = {
    "default": ["bank_transfer", "paypal", "crypto"],
    "africa": ["mobile_money", "bank_transfer", "crypto"],
    "south_asia": ["mobile_money", "bank_transfer", "paypal"],
    "southeast_asia": ["bank_transfer", "mobile_money", "paypal"],
    "middle_east": ["bank_transfer", "paypal", "crypto"],
    "latin_america": ["bank_transfer", "paypal", "crypto"],
}

AFRICA = {"NG","GH","KE","ZA","EG","MA","TZ","UG","ET","RW","SN","CI","CM","DZ","TN","ZM","ZW","AO","MZ","SD","CD","BJ","TG","ML","BF","NE"}
SOUTH_ASIA = {"IN","PK","BD","LK","NP","BT","MV","AF"}
SOUTHEAST_ASIA = {"MY","TH","VN","PH","ID","KH","MM","LA","SG","BN","TL"}
MIDDLE_EAST = {"AE","SA","QA","KW","BH","OM","JO","LB","IL","IQ","IR","YE","PS"}
LATIN_AMERICA = {"MX","BR","AR","CO","CL","PE","VE","EC","UY","PY","BO","CR","PA","GT","HN","DO","JM","TT","HT","CU","BS","BB"}

MOBILE_MONEY_PROVIDERS_BY_COUNTRY = {
    "NG": ["Opay", "PalmPay", "Moniepoint"], "GH": ["MTN Mobile Money", "Telecel Cash"],
    "KE": ["M-Pesa", "Airtel Money"], "TZ": ["M-Pesa", "Tigo Pesa"], "UG": ["MTN Mobile Money", "Airtel Money"],
    "ZA": ["Capitec Pay", "FNB eWallet"], "CI": ["Orange Money", "MTN Mobile Money"],
    "SN": ["Orange Money", "Wave"], "CM": ["MTN Mobile Money", "Orange Money"],
    "RW": ["MTN Mobile Money", "Airtel Money"], "ZM": ["Airtel Money", "MTN Mobile Money"],
    "IN": ["UPI", "Paytm"], "PK": ["JazzCash", "EasyPaisa"], "BD": ["bKash", "Nagad"],
    "PH": ["GCash", "Maya"], "ID": ["GoPay", "OVO"], "VN": ["MoMo", "ZaloPay"],
}


def region_for_country(country_code: str) -> str:
    if country_code in AFRICA:
        return "africa"
    if country_code in SOUTH_ASIA:
        return "south_asia"
    if country_code in SOUTHEAST_ASIA:
        return "southeast_asia"
    if country_code in MIDDLE_EAST:
        return "middle_east"
    if country_code in LATIN_AMERICA:
        return "latin_america"
    return "default"


def get_currency_for_country(country_code: str):
    return COUNTRY_CURRENCY.get(country_code, DEFAULT_CURRENCY)


def convert_usd_cents(usd_cents: int, currency_code: str) -> float:
    rate = USD_EXCHANGE_RATES.get(currency_code, 1.0)
    return round((usd_cents / 100.0) * rate, 2)


def get_withdrawal_methods(country_code: str):
    region = region_for_country(country_code)
    methods = WITHDRAWAL_METHODS_BY_REGION.get(region, WITHDRAWAL_METHODS_BY_REGION["default"])
    providers = MOBILE_MONEY_PROVIDERS_BY_COUNTRY.get(country_code, [])
    return methods, providers
