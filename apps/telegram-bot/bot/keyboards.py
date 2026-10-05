import calendar
from datetime import date
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Өтінім қалдыру")],
        [KeyboardButton(text="📋 Менің өтінімдерім"), KeyboardButton(text="☎️ Байланыс")],
        [KeyboardButton(text="📊 Менің көрсеткіштерім")],
    ],
    resize_keyboard=True,
)
CONTROLS = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Артқа"), KeyboardButton(text="❌ Бас тарту")]], resize_keyboard=True
)
ACCOUNT_HELP = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⚠️ Авариялық өтінім")],
        [KeyboardButton(text="⬅️ Артқа"), KeyboardButton(text="❌ Бас тарту")],
    ], resize_keyboard=True, one_time_keyboard=True,
)
LOCATION = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📍 Геолокацияны жіберу", request_location=True)],
        [KeyboardButton(text="⬅️ Артқа"), KeyboardButton(text="❌ Бас тарту")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def inline(rows, controls=True):
    buttons = [[InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows]
    if controls:
        buttons.append(
            [
                InlineKeyboardButton(text="⬅️ Артқа", callback_data="back"),
                InlineKeyboardButton(text="❌ Бас тарту", callback_data="cancel"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def date_keyboard(today: date, year=None, month=None):
    year, month = year or today.year, month or today.month
    months = [
        "Қаңтар",
        "Ақпан",
        "Наурыз",
        "Сәуір",
        "Мамыр",
        "Маусым",
        "Шілде",
        "Тамыз",
        "Қыркүйек",
        "Қазан",
        "Қараша",
        "Желтоқсан",
    ]
    rows = [
        [(f"{months[month - 1]} {year}", "noop")],
        [(day, "noop") for day in ["Дс", "Сс", "Ср", "Бс", "Жм", "Сб", "Жс"]],
    ]
    for week in calendar.monthcalendar(year, month):
        rows.append(
            [
                (
                    str(day) if day else "·",
                    f"date:{year}-{month:02}-{day:02}" if day and date(year, month, day) >= today else "noop",
                )
                for day in week
            ]
        )
    previous = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    rows.append(
        [("‹", f"month:{previous:%Y-%m}"), ("Бүгін", f"date:{today.isoformat()}"), ("›", f"month:{following:%Y-%m}")]
    )
    return inline(rows)
