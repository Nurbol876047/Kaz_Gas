from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    WAITING_ACCOUNT = State()
    ACCOUNT_NOT_FOUND = State()
    CONFIRM_ACCOUNT = State()
    SELECT_APPLICATION_TYPE = State()
    METER_WAITING_PHOTO = State()
    METER_WAITING_LOCATION = State()
    METER_CONFIRM = State()
    MPI_WAITING_DATE = State()
    MPI_CONFIRM = State()
    GAS_WAITING_METER_PHOTO = State()
    GAS_WAITING_LEAK_PHOTO = State()
    GAS_WAITING_LOCATION = State()
    GAS_CONFIRM = State()
    READING_PHOTO = State()
    READING_CONFIRM = State()


BACK = {
    Flow.ACCOUNT_NOT_FOUND.state: Flow.WAITING_ACCOUNT,
    Flow.READING_PHOTO.state: Flow.SELECT_APPLICATION_TYPE,
    Flow.READING_CONFIRM.state: Flow.READING_PHOTO,
    Flow.CONFIRM_ACCOUNT.state: Flow.WAITING_ACCOUNT,
    Flow.SELECT_APPLICATION_TYPE.state: Flow.CONFIRM_ACCOUNT,
    Flow.METER_WAITING_PHOTO.state: Flow.SELECT_APPLICATION_TYPE,
    Flow.METER_WAITING_LOCATION.state: Flow.METER_WAITING_PHOTO,
    Flow.METER_CONFIRM.state: Flow.METER_WAITING_LOCATION,
    Flow.MPI_WAITING_DATE.state: Flow.SELECT_APPLICATION_TYPE,
    Flow.MPI_CONFIRM.state: Flow.MPI_WAITING_DATE,
    Flow.GAS_WAITING_METER_PHOTO.state: Flow.SELECT_APPLICATION_TYPE,
    Flow.GAS_WAITING_LEAK_PHOTO.state: Flow.GAS_WAITING_METER_PHOTO,
    Flow.GAS_WAITING_LOCATION.state: Flow.GAS_WAITING_LEAK_PHOTO,
    Flow.GAS_CONFIRM.state: Flow.GAS_WAITING_LOCATION,
}
TYPE_LABELS = {
    "METER_NOT_WORKING": "Счетчик жұмыс жасамайды",
    "MPI_REMOVAL": "МПИ-ге шешу",
    "GAS_LEAK": "Есептеу құралынан газ шығуы",
}
STATUS_LABELS = {
    "NEW": "🆕 Жаңа",
    "IN_PROGRESS": "🟡 Өңделуде",
    "COMPLETED": "🟢 Аяқталды",
    "REJECTED": "🔴 Қабылданбады",
}
