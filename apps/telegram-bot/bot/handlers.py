import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import ACCOUNT_HELP, CONTROLS, LOCATION, MAIN, date_keyboard, inline
from bot.services import Backend
from bot.states import BACK, STATUS_LABELS, TYPE_LABELS, Flow

router = Router()


def today(timezone="Asia/Qyzylorda"):
    return datetime.now(ZoneInfo(timezone)).date()


def valid_date(value, timezone="Asia/Qyzylorda"):
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y").date()
        if not today(timezone) <= parsed <= date(today(timezone).year + 2, 12, 31):
            return None
        return parsed
    except ValueError:
        return None


async def prompt(message: Message, state: FSMContext, backend: Backend, timezone="Asia/Qyzylorda"):
    current, data = await state.get_state(), await state.get_data()
    account = data.get("personal_account", "")
    markup = CONTROLS
    if current == Flow.WAITING_ACCOUNT.state:
        text = "Дербес шотты енгізіңіз:"
    elif current == Flow.ACCOUNT_NOT_FOUND.state:
        text = ("Дербес шот табылмады. Нөмірді тексеріп, қайта енгізіңіз.\n"
                "Қауіпті жағдай туралы хабарлау үшін «Авариялық өтінім» батырмасын басыңыз.")
        markup = ACCOUNT_HELP
    elif current == Flow.CONFIRM_ACCOUNT.state:
        verified = await backend.account(data["telegram_user_id"], account)
        if not verified.get("verified"):
            await state.set_state(Flow.WAITING_ACCOUNT)
            await message.answer("Шотқа қолжетімділікті қайта растаңыз. /start басыңыз.", reply_markup=CONTROLS)
            return
        resident = verified["account"]
        text = (f"✅ Шот расталды\nДербес шот: {account}\nЕсептегіш: {resident['meter_number']}\n"
                f"Аты-жөні: {resident['full_name']}\nМекенжай: {resident['address']}\n\nБұл сіздің шотыңыз ба?")
        markup = inline([[("✅ Дұрыс", "account:yes"), ("✏️ Өзгерту", "account:edit")]])
    elif current == Flow.SELECT_APPLICATION_TYPE.state:
        text = "Өтінім түрін таңдаңыз:"
        markup = inline(
            [
                [("📊 Газ көрсеткішін жіберу", "reading:start")],
                [("🔧 Счетчик жұмыс жасамайды", "type:METER_NOT_WORKING")],
                [("📅 МПИ-ге шешу", "type:MPI_REMOVAL")],
                [("⚠️ Есептеу құралынан газ шығуы", "type:GAS_LEAK")],
            ]
        )
    elif current == Flow.READING_PHOTO.state:
        text = "Есептегіштің көрсеткіші анық көрінетін фотосын жіберіңіз."
    elif current == Flow.READING_CONFIRM.state:
        text = f"Дербес шот: {account}\nКезең: {data['reading_period'][:7]}\nФото: ✅\n\nТексеруге жіберейік пе?"
        markup = inline([[("✅ Жіберу", "reading:submit"), ("✏️ Қайта түсіру", "reading:edit")]])
    elif current in {Flow.METER_WAITING_PHOTO.state, Flow.GAS_WAITING_METER_PHOTO.state}:
        text = "Есептеу құралының фотосын жіберіңіз."
    elif current == Flow.GAS_WAITING_LEAK_PHOTO.state:
        text = "Газ шығып жатқан жердің фотосын жіберіңіз."
    elif current in {Flow.METER_WAITING_LOCATION.state, Flow.GAS_WAITING_LOCATION.state}:
        text, markup = "Геолокацияңызды жіберіңіз.", LOCATION
    elif current == Flow.MPI_WAITING_DATE.state:
        text = "МПИ-ге шешу күнін енгізіңіз.\nКүнтізбеден таңдаңыз немесе ДД.ММ.ГГГГ форматында жазыңыз."
        markup = date_keyboard(today(timezone))
    else:
        kind = data["application_type"]
        text = f"{'⚠️ ' if kind == 'GAS_LEAK' else ''}Өтінім түрі: {TYPE_LABELS[kind]}\nДербес шот: {account}\n"
        if kind == "MPI_REMOVAL":
            text += f"Күні: {date.fromisoformat(data['requested_date']):%d.%m.%Y}\n\nДеректер дұрыс па?"
        else:
            text += "Есептеу құралының фотосы: ✅\n"
            if kind == "GAS_LEAK":
                text += "Газ шығып жатқан жердің фотосы: ✅\n"
            text += "Геолокация: ✅\n\nӨтінімді жібересіз бе?"
        markup = inline(
            [
                [("🚨 Жіберу" if kind == "GAS_LEAK" else "✅ Жіберу", "submit")],
                [("✏️ Күнді өзгерту" if kind == "MPI_REMOVAL" else "✏️ Өзгерту", "edit")],
            ]
        )
    sent = await message.answer(text, reply_markup=markup)
    await state.update_data(active_message_id=sent.message_id)


@router.message(CommandStart())
@router.message(Command("new"))
@router.message(F.text == "📝 Өтінім қалдыру")
async def start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Flow.WAITING_ACCOUNT)
    await state.update_data(idempotency_key=str(uuid.uuid4()), telegram_user_id=message.from_user.id)
    sent = await message.answer(
        "Қош келдіңіз!\nДербес шотыңызды енгізіңіз.\n"
        f"Telegram ID: {message.from_user.id}",
        reply_markup=CONTROLS,
    )
    await state.update_data(active_message_id=sent.message_id)


async def cancel(message, state):
    await state.clear()
    await message.answer("Өтінімнен бас тартылды.", reply_markup=MAIN)


@router.message(Command("cancel"))
@router.message(F.text == "❌ Бас тарту")
async def cancel_message(message: Message, state: FSMContext):
    await cancel(message, state)


async def go_back(message, state, backend, timezone):
    current = await state.get_state()
    if current not in BACK:
        await cancel(message, state)
        return
    await state.set_state(BACK[current])
    await prompt(message, state, backend, timezone)


@router.message(F.text == "⬅️ Артқа")
async def back_message(message: Message, state: FSMContext, backend: Backend, timezone: str):
    await go_back(message, state, backend, timezone)


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Басты мәзір", reply_markup=MAIN)


@router.message(F.text == "☎️ Байланыс")
@router.message(Command("contact"))
async def contact(message: Message, backend: Backend):
    config = await backend.settings()
    text = config["organization_name"] + "\nБайланыс: " + (config["contact_phone"] or "Нөмір әлі көрсетілмеген")
    if config["emergency_phone"]:
        text += "\nАвариялық қызмет: " + config["emergency_phone"]
    await message.answer(text)


async def show_applications(message, backend, user_id, page=1):
    result = await backend.applications(user_id, page)
    if not result["items"]:
        await message.answer("Өтінімдеріңіз жоқ.", reply_markup=MAIN)
        return
    blocks = [
        f"{a['application_number']}\n{TYPE_LABELS[a['application_type']]}\n{a['created_at'][:10]} · {STATUS_LABELS[a['status']]}"
        for a in result["items"]
    ]
    rows = [[(a["application_number"], f"view:{a['id']}")] for a in result["items"]]
    navigation = []
    if page > 1:
        navigation.append(("‹ Алдыңғы", f"list:{page - 1}"))
    if result["has_more"]:
        navigation.append(("Келесі ›", f"list:{page + 1}"))
    if navigation:
        rows.append(navigation)
    await message.answer("📋 Менің өтінімдерім\n\n" + "\n\n".join(blocks), reply_markup=inline(rows, controls=False))


@router.message(F.text == "📋 Менің өтінімдерім")
@router.message(Command("applications"))
async def my_applications(message: Message, state: FSMContext, backend: Backend):
    await state.clear()
    await show_applications(message, backend, message.from_user.id)


@router.callback_query(F.data.startswith("view:"))
async def view_application(callback: CallbackQuery, backend: Backend):
    await callback.answer()
    id = callback.data.split(":")[1]
    if not id.isdigit():
        return
    a = await backend.application(callback.from_user.id, int(id))
    await callback.message.answer(
        f"{a['application_number']}\nДербес шот: {a['personal_account']}\n{TYPE_LABELS[a['application_type']]}\n{STATUS_LABELS[a['status']]}"
    )


@router.callback_query(F.data.startswith("list:"))
async def list_page(callback: CallbackQuery, backend: Backend):
    await callback.answer()
    page = callback.data.split(":")[1]
    if page.isdigit() and 1 <= int(page) <= 10000:
        await show_applications(callback.message, backend, callback.from_user.id, int(page))


@router.message(Flow.WAITING_ACCOUNT, F.text, ~F.text.startswith("/"), F.text != "📊 Менің көрсеткіштерім")
async def account(message: Message, state: FSMContext, backend: Backend, timezone: str):
    value = message.text.strip()
    if not re.fullmatch(r"[0-9]{6,20}", value):
        await message.answer("Дербес шот 6–20 цифрдан тұруы керек. Қайта енгізіңіз:")
        return
    await state.update_data(lookup_identifier=value, telegram_user_id=message.from_user.id)
    result = await backend.account(message.from_user.id, value)
    if result.get("verified"):
        await state.update_data(personal_account=result["account"]["account_number"], account_id=result["account"]["id"])
        await state.set_state(Flow.CONFIRM_ACCOUNT)
    else:
        await state.set_state(Flow.ACCOUNT_NOT_FOUND)
    await prompt(message, state, backend, timezone)


@router.message(Flow.ACCOUNT_NOT_FOUND, F.text == "⚠️ Авариялық өтінім")
async def unverified_emergency(message: Message, state: FSMContext, backend: Backend, timezone: str):
    data = await state.get_data()
    await state.update_data(personal_account=data["lookup_identifier"], application_type="GAS_LEAK")
    await state.set_state(Flow.GAS_WAITING_METER_PHOTO)
    await message.answer("⚠️ Қауіп төніп тұрса, авариялық газ қызметіне дереу хабарласыңыз. "
                         "Өтінім расталмаған шотпен қабылданады.", reply_markup=CONTROLS)
    await prompt(message, state, backend, timezone)


@router.message(Command("readings"))
@router.message(F.text == "📊 Менің көрсеткіштерім")
async def my_readings(message: Message, backend: Backend):
    result = await backend.readings(message.from_user.id)
    labels = {"PENDING": "Тексерілуде", "ACCEPTED": "Қабылданды", "REJECTED": "Қабылданбады"}
    blocks = [f"Шот: {item['account_number']} · {item['period'][:7]}\n"
              + (f"{item['value']} м³" if item['value'] is not None else "Фото тексерілуде")
              + f" · {labels[item['status']]}"
              + (f"\nШығын: {item['consumption']} м³" if item['consumption'] is not None else "")
              + (f"\n{item['review_note']}" if item.get('review_note') else "") for item in result["items"]]
    await message.answer("\n\n".join(blocks) if blocks else "Әзірге көрсеткіштер жоқ.")


@router.message(Flow.READING_PHOTO, F.photo)
async def reading_photo(message: Message, state: FSMContext, backend: Backend, timezone: str):
    image = message.photo[-1]
    file = await backend.upload(message.bot, message.from_user.id, image, "METER_READING_PHOTO")
    await state.update_data(reading_photo_id=file["id"], reading_period=today(timezone).replace(day=1).isoformat())
    await state.set_state(Flow.READING_CONFIRM)
    await prompt(message, state, backend, timezone)


@router.message(Flow.MPI_WAITING_DATE, F.text)
async def mpi_date(message: Message, state: FSMContext, backend: Backend, timezone: str):
    value = valid_date(message.text, timezone)
    if value is None:
        await message.answer("Күн дұрыс емес. Бүгіннен бастап екі жыл шегінде ДД.ММ.ГГГГ форматымен енгізіңіз.")
        return
    await state.update_data(requested_date=value.isoformat())
    await state.set_state(Flow.MPI_CONFIRM)
    await prompt(message, state, backend, timezone)


@router.message(Flow.METER_WAITING_PHOTO, F.photo)
@router.message(Flow.GAS_WAITING_METER_PHOTO, F.photo)
@router.message(Flow.GAS_WAITING_LEAK_PHOTO, F.photo)
async def photo(message: Message, state: FSMContext, backend: Backend, timezone: str):
    current = await state.get_state()
    leak = current == Flow.GAS_WAITING_LEAK_PHOTO.state
    data = await state.get_data()
    image = message.photo[-1]
    if leak and image.file_unique_id == data.get("meter_unique_id"):
        await message.answer("Газ шығып жатқан жердің бөлек фотосын жіберіңіз.")
        return
    file = await backend.upload(message.bot, message.from_user.id, image, "GAS_LEAK_PHOTO" if leak else "METER_PHOTO")
    await state.update_data(
        **(
            {"leak_photo_id": file["id"]}
            if leak
            else {"meter_photo_id": file["id"], "meter_unique_id": image.file_unique_id}
        )
    )
    next_state = {
        Flow.METER_WAITING_PHOTO.state: Flow.METER_WAITING_LOCATION,
        Flow.GAS_WAITING_METER_PHOTO.state: Flow.GAS_WAITING_LEAK_PHOTO,
        Flow.GAS_WAITING_LEAK_PHOTO.state: Flow.GAS_WAITING_LOCATION,
    }[current]
    await state.set_state(next_state)
    await prompt(message, state, backend, timezone)


@router.message(Flow.METER_WAITING_LOCATION, F.location)
@router.message(Flow.GAS_WAITING_LOCATION, F.location)
async def location(message: Message, state: FSMContext, backend: Backend, timezone: str):
    latitude, longitude = message.location.latitude, message.location.longitude
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        await message.answer("Геолокация дұрыс емес. Қайта жіберіңіз.")
        return
    current = await state.get_state()
    await state.update_data(latitude=latitude, longitude=longitude)
    await state.set_state(Flow.METER_CONFIRM if current == Flow.METER_WAITING_LOCATION.state else Flow.GAS_CONFIRM)
    await message.answer("Геолокация қабылданды.", reply_markup=CONTROLS)
    await prompt(message, state, backend, timezone)


@router.callback_query()
async def callback(callback: CallbackQuery, state: FSMContext, backend: Backend, timezone: str):
    current, data = await state.get_state(), await state.get_data()
    if not current or callback.message.message_id != data.get("active_message_id"):
        await callback.answer("Бұл батырма ескірген. Соңғы хабарламаны пайдаланыңыз.")
        return
    await callback.answer()
    if "telegram_user_id" not in data:
        await state.clear()
        await callback.message.answer("Жүйе жаңартылды. Шотыңызды растау үшін /start басыңыз.", reply_markup=MAIN)
        return
    action = callback.data
    if action == "noop":
        return
    if action == "cancel":
        await cancel(callback.message, state)
        return
    if action == "back":
        await go_back(callback.message, state, backend, timezone)
        return
    if current == Flow.SELECT_APPLICATION_TYPE.state and action == "reading:start":
        verified = await backend.account(callback.from_user.id, data["personal_account"])
        if not verified.get("verified"):
            await state.set_state(Flow.WAITING_ACCOUNT)
        else:
            await state.update_data(account_id=verified["account"]["id"], idempotency_key=str(uuid.uuid4()))
            await state.set_state(Flow.READING_PHOTO)
        await prompt(callback.message, state, backend, timezone)
        return
    if current == Flow.READING_CONFIRM.state and action in {"reading:submit", "reading:edit"}:
        if action == "reading:edit":
            await state.set_state(Flow.READING_PHOTO)
            await prompt(callback.message, state, backend, timezone)
            return
        await backend.reading({"account_id": data["account_id"], "telegram_user_id": callback.from_user.id,
                               "idempotency_key": data["idempotency_key"], "photo_id": data["reading_photo_id"],
                               "period": data["reading_period"]})
        await state.clear()
        await callback.message.answer("✅ Көрсеткіштің фотосы тексеруге жіберілді.\n"
                                      "Күйін «Менің көрсеткіштерім» бөлімінен көре аласыз.", reply_markup=MAIN)
        return
    if current == Flow.CONFIRM_ACCOUNT.state and action in {"account:yes", "account:edit"}:
        await state.set_state(Flow.SELECT_APPLICATION_TYPE if action == "account:yes" else Flow.WAITING_ACCOUNT)
    elif current == Flow.SELECT_APPLICATION_TYPE.state and action.startswith("type:"):
        kind = action.split(":")[1]
        if kind not in TYPE_LABELS:
            return
        # Switching type clears incompatible fields but preserves the confirmed account and idempotency key.
        await state.set_data({k: data[k] for k in ["personal_account", "idempotency_key", "telegram_user_id", "account_id"]
                              if k in data})
        await state.update_data(application_type=kind)
        if kind == "GAS_LEAK":
            warning = "⚠️ Газ иісі қатты сезілсе немесе қауіп төніп тұрса, авариялық газ қызметіне дереу хабарласыңыз."
            # Show the warning immediately, even if the settings API is temporarily unavailable.
            await callback.message.answer(warning, reply_markup=CONTROLS)
            from bot.services import APIError

            try:
                config = await backend.settings()
                if config["emergency_phone"]:
                    await callback.message.answer("☎️ Авариялық қызмет: " + config["emergency_phone"])
            except APIError:
                pass
        await state.set_state(
            {
                "METER_NOT_WORKING": Flow.METER_WAITING_PHOTO,
                "MPI_REMOVAL": Flow.MPI_WAITING_DATE,
                "GAS_LEAK": Flow.GAS_WAITING_METER_PHOTO,
            }[kind]
        )
    elif current == Flow.MPI_WAITING_DATE.state and action.startswith("month:"):
        try:
            month = date.fromisoformat(action.split(":")[1] + "-01")
        except ValueError:
            return
        if not today(timezone).replace(day=1) <= month <= date(today(timezone).year + 2, 12, 1):
            return
        await callback.message.edit_reply_markup(reply_markup=date_keyboard(today(timezone), month.year, month.month))
        return
    elif current == Flow.MPI_WAITING_DATE.state and action.startswith("date:"):
        try:
            date_value = date.fromisoformat(action.split(":")[1])
        except ValueError:
            return
        if valid_date(date_value.strftime("%d.%m.%Y"), timezone) is None:
            return
        await state.update_data(requested_date=date_value.isoformat())
        await state.set_state(Flow.MPI_CONFIRM)
    elif current in {Flow.METER_CONFIRM.state, Flow.MPI_CONFIRM.state, Flow.GAS_CONFIRM.state}:
        if action == "edit":
            await state.set_state(
                {
                    Flow.METER_CONFIRM.state: Flow.METER_WAITING_PHOTO,
                    Flow.MPI_CONFIRM.state: Flow.MPI_WAITING_DATE,
                    Flow.GAS_CONFIRM.state: Flow.GAS_WAITING_METER_PHOTO,
                }[current]
            )
        elif action == "submit":
            payload = {
                k: data[k]
                for k in [
                    "idempotency_key",
                    "personal_account",
                    "application_type",
                    "requested_date",
                    "latitude",
                    "longitude",
                    "meter_photo_id",
                    "leak_photo_id",
                ]
                if k in data
            }
            user = callback.from_user
            payload["user"] = {
                "telegram_user_id": user.id,
                "telegram_username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
            result = await backend.create(payload)
            await state.clear()
            await callback.message.answer(
                f"✅ Өтініміңіз қабылданды.\n\nӨтінім нөмірі:\n{result['application_number']}\n\nӨтініміңіздің жағдайын осы нөмір арқылы бақылай аласыз.",
                reply_markup=MAIN,
            )
            return
        else:
            return
    else:
        return
    await prompt(callback.message, state, backend, timezone)


@router.message()
async def fallback(message: Message, state: FSMContext):
    current = await state.get_state()
    if current in {
        Flow.METER_WAITING_PHOTO.state,
        Flow.GAS_WAITING_METER_PHOTO.state,
        Flow.GAS_WAITING_LEAK_PHOTO.state,
        Flow.READING_PHOTO.state,
    }:
        await message.answer(
            "Фотосуретті «Фото» ретінде жіберіңіз. Құжат немесе мәтін қабылданбайды.", reply_markup=CONTROLS
        )
    elif current in {Flow.METER_WAITING_LOCATION.state, Flow.GAS_WAITING_LOCATION.state}:
        await message.answer("📍 Геолокацияны жіберу батырмасын басыңыз.", reply_markup=LOCATION)
    elif current == Flow.ACCOUNT_NOT_FOUND.state:
        await message.answer("Дербес шот нөмірін қайта енгізу үшін ⬅️ Артқа батырмасын басыңыз.", reply_markup=ACCOUNT_HELP)
    elif current:
        await message.answer("Соңғы хабарламадағы батырманы пайдаланыңыз. ⬅️ Артқа немесе ❌ Бас тарту қолжетімді.")
    else:
        await message.answer("Басты мәзір", reply_markup=MAIN)
