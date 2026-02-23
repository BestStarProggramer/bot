import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import ADMINS
from database import (
    get_active_students,
    reset_all_weights,
    get_all_weights,
    get_full_list,
    toggle_student_status,
    enable_all_students,
    save_queue_to_db,
    load_queue_from_db,
    swap_queue_items,
    get_queue_time 
)
from queue_logic import weighted_permutation, update_weights, update_swap_weights

logging.basicConfig(level=logging.INFO)
router = Router()

priority_list = []
late_list = []
user_selections = {}

def is_admin(user_id):
    return user_id in ADMINS

def get_keyboard(user_id):
    if is_admin(user_id):
        buttons = [
            [InlineKeyboardButton(text="🎲 Сгенерировать", callback_data="admin_gen")],
            [InlineKeyboardButton(text="🔀 Поменять местами", callback_data="admin_swap_start")],
            [InlineKeyboardButton(text="⭐ Приоритеты", callback_data="sel_priority"),
             InlineKeyboardButton(text="🐌 Опоздания", callback_data="sel_late")],
            [InlineKeyboardButton(text="✅ Включить", callback_data="sel_enable"),
             InlineKeyboardButton(text="❌ Исключить", callback_data="sel_disable")],
            [InlineKeyboardButton(text="📜 Очередь", callback_data="pub_queue")], 
            [InlineKeyboardButton(text="📝 Список", callback_data="pub_list"),
             InlineKeyboardButton(text="📊 Веса", callback_data="pub_weights")],
            [InlineKeyboardButton(text="🔄 Включить всех", callback_data="admin_enable_all")],
            [InlineKeyboardButton(text="⚠️ Сброс весов", callback_data="admin_reset_confirm")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="📜 Текущая очередь", callback_data="pub_")],
            [InlineKeyboardButton(text="📝 Список ID", callback_data="pub_list"),
             InlineKeyboardButton(text="📊 Шансы", callback_data="pub_weights")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_selection_keyboard(user_id):
    data = user_selections.get(user_id)
    if not data: return None
    action = data["action"]
    temp_selected = data["selected"]
    
    if action == "swap":
        current_q = load_queue_from_db()
        buttons = []
        row = []
        for item in current_q:
            pos, s_id, name, is_p, is_l, _ = item
            prefix = "⭐ " if is_p else "🐌 " if is_l else ""
            check = "✅ " if pos in temp_selected else ""
            row.append(InlineKeyboardButton(text=f"{check}{pos}. {prefix}{name}", callback_data=f"swap_toggle_{pos}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        confirm_text = "🚀 ПОМЕНЯТЬ" if len(temp_selected) == 2 else "Выбери двоих"
        buttons.append([InlineKeyboardButton(text=confirm_text, callback_data="confirm_swap")])
        buttons.append([InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel_selection")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    students = get_full_list()
    buttons = []
    row = []
    for s_id, name, active in students:
        prefix = "⭐ " if s_id in priority_list else "🐌 " if s_id in late_list else ""
        check = "✅ " if s_id in temp_selected else ""
        status_dot = "🟢" if active else "🔴"
        row.append(InlineKeyboardButton(text=f"{check}{prefix}{status_dot} {name}", callback_data=f"toggle_{s_id}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🚀 ПРИМЕНИТЬ", callback_data="confirm_selection")])
    buttons.append([InlineKeyboardButton(text="🧹 Сбросить выбор", callback_data="clear_current_list")])
    buttons.append([InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel_selection")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data.startswith("sel_"))
async def start_selection(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return
    action = callback.data.replace("sel_", "")
    initial_selected = priority_list.copy() if action == "priority" else late_list.copy() if action == "late" else []
    user_selections[callback.from_user.id] = {"action": action, "selected": initial_selected}
    titles = {"priority": "⭐ Приоритеты", "late": "🐌 Опоздания", "enable": "✅ Включение", "disable": "❌ Исключение"}
    await callback.message.answer(titles[action], reply_markup=get_selection_keyboard(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "admin_swap_start")
async def start_swap_ui(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return
    if not load_queue_from_db():
        await callback.answer("⚠️ Очередь пуста!", show_alert=True)
        return
    user_selections[callback.from_user.id] = {"action": "swap", "selected": []}
    await callback.message.answer("🔀 Выбери двух человек:", reply_markup=get_selection_keyboard(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data.startswith("pub_"))
async def handle_pub_btn(callback: CallbackQuery):
    u_id = callback.from_user.id
    if callback.data == "pub_queue":
        current_q = load_queue_from_db()
        if not current_q:
            await callback.answer("⚠️ Очередь еще не была сгенерирована!", show_alert=True)
            return
        
        q_time = get_queue_time()
        text = f"📜 <b>Текущая очередь:</b>\n<i>(Обновлено: {q_time})</i>\n\n"
        for item in current_q:
            pref = "⭐ " if item[3] else "🐌 " if item[4] else ""
            text += f"{item[0]}. {pref}{item[2]}\n"
        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(u_id))
        
    elif callback.data == "pub_list":
        students = get_full_list()
        text = "📝 <b>Список:</b>\n\n"
        for s_id, name, active in students: text += f"<code>{s_id}</code>: {name} {'✅' if active else '❌'}\n"
        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(u_id))
        
    elif callback.data == "pub_weights":
        students = get_all_weights()
        text = "📊 <b>Веса:</b>\n\n"
        for name, weight in students: text += f"{name}: <code>{weight:.2f}</code>\n"
        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(u_id))
    await callback.answer()

@router.callback_query(F.data == "cancel_selection")
async def cancel_selection_handler(callback: CallbackQuery):
    user_selections.pop(callback.from_user.id, None)
    try: await callback.message.delete()
    except: await callback.message.edit_text("❌ Отменено.", reply_markup=None)
    await callback.answer()

@router.callback_query(F.data == "clear_current_list")
async def clear_selection_handler(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id in user_selections:
        user_selections[u_id]["selected"] = []
        await callback.message.edit_reply_markup(reply_markup=get_selection_keyboard(u_id))
        await callback.answer("Выбор очищен")

@router.callback_query(F.data.startswith("swap_toggle_"))
async def toggle_swap_item(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or user_selections[u_id]["action"] != "swap": return
    pos = int(callback.data.replace("swap_toggle_", ""))
    selected = user_selections[u_id]["selected"]
    if pos in selected: selected.remove(pos)
    elif len(selected) < 2: selected.append(pos)
    await callback.message.edit_reply_markup(reply_markup=get_selection_keyboard(u_id))
    await callback.answer()

@router.callback_query(F.data == "confirm_swap")
async def confirm_swap_ui(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or len(user_selections[u_id]["selected"]) != 2:
        await callback.answer("⚠️ Выбери двоих!", show_alert=True)
        return
    
    pos1, pos2 = user_selections[u_id]["selected"]
    current_q = load_queue_from_db()
    s1_pre = next(x for x in current_q if x[0] == pos1)
    s2_pre = next(x for x in current_q if x[0] == pos2)

    if s1_pre[3] or s1_pre[4] or s2_pre[3] or s2_pre[4]:
        await callback.answer("⚠️ Нельзя менять приоритетных или опоздавших!", show_alert=True)
        return

    swap_queue_items(pos1, pos2)
    new_q = load_queue_from_db()
    
    regular_in_queue = [item for item in new_q if not item[3] and not item[4]]
    total_n = len(regular_in_queue)
    
    def get_rel_pos(pos_in_full):
        for i, item in enumerate(regular_in_queue, start=1):
            if item[0] == pos_in_full: return i
        return 1

    s1_post = next(x for x in new_q if x[0] == pos1)
    s2_post = next(x for x in new_q if x[0] == pos2)
    
    
    update_swap_weights(
        (s1_post[1], get_rel_pos(pos1), s1_post[5]), 
        (s2_post[1], get_rel_pos(pos2), s2_post[5]), 
        total_n
    )

    q_time = get_queue_time()
    text = f"🔄 <b>Очередь обновлена:</b>\n<i>(Смена мест: {q_time})</i>\n\n"
    for item in new_q:
        pref = "⭐ " if item[3] else "🐌 " if item[4] else ""
        text += f"{item[0]}. {pref}{item[2]}\n"
    
    user_selections.pop(u_id, None)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_keyboard(u_id))
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_"))
async def toggle_student(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections: return
    s_id = int(callback.data.replace("toggle_", ""))
    selected = user_selections[u_id]["selected"]
    if s_id in selected: selected.remove(s_id)
    else: selected.append(s_id)
    await callback.message.edit_reply_markup(reply_markup=get_selection_keyboard(u_id))
    await callback.answer()

@router.callback_query(F.data == "confirm_selection")
async def confirm_selection(callback: CallbackQuery):
    global priority_list, late_list
    u_id = callback.from_user.id
    if u_id not in user_selections: return
    action, ids = user_selections[u_id]["action"], user_selections[u_id]["selected"]
    if action == "priority": priority_list = ids.copy()
    elif action == "late": late_list = ids.copy()
    elif action == "enable":
        for s_id in ids: toggle_student_status(s_id, 1)
    elif action == "disable":
        for s_id in ids: toggle_student_status(s_id, 0)
    user_selections.pop(u_id, None)
    await callback.message.edit_text("✅ Изменения применены", reply_markup=get_keyboard(u_id))
    await callback.answer()

async def perform_generation(target, user_id):
    global priority_list, late_list
    students = get_active_students()
    if not students:
        msg = "Нет активных студентов"
        if isinstance(target, Message): await target.answer(msg)
        else: await target.message.answer(msg)
        return
    
    raw_queue = weighted_permutation(students, priority_ids=priority_list, late_ids=late_list)
    db_ready_queue = []
    for s in raw_queue:
      
        orig_weight = next(st[2] for st in students if st[0] == s[0])
        db_ready_queue.append({
            'id': s[0], 
            'name': s[1], 
            'is_priority': 1 if s[0] in priority_list else 0, 
            'is_late': 1 if s[0] in late_list else 0,
            'weight_before': orig_weight 
        })
    
    save_queue_to_db(db_ready_queue)
    regular_students = [s for s in raw_queue if s[0] not in priority_list and s[0] not in late_list]
    update_weights(regular_students)

    priority_list.clear()
    late_list.clear()

    q_time = get_queue_time()
    text = f"🎲 <b>Новая очередь:</b>\n<i>(Создана: {q_time})</i>\n\n"
    for i, s in enumerate(db_ready_queue, start=1):
        pref = "⭐ " if s['is_priority'] else "🐌 " if s['is_late'] else ""
        text += f"{i}. {pref}{s['name']}\n"

    kb = get_keyboard(user_id)
    if isinstance(target, Message): await target.answer(text, parse_mode="HTML", reply_markup=kb)
    else: await target.message.answer(text, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data.startswith("admin_"))
async def handle_admin_btn(callback: CallbackQuery):
    u_id = callback.from_user.id
    if not is_admin(u_id): return
    if callback.data == "admin_gen": await perform_generation(callback, u_id)
    elif callback.data == "admin_enable_all":
        enable_all_students()
        await callback.message.answer("✅ Все включены", reply_markup=get_keyboard(u_id))
    elif callback.data == "admin_reset_confirm":
        reset_all_weights()
        await callback.message.answer("⚠️ Веса сброшены", reply_markup=get_keyboard(u_id))
    await callback.answer()

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
    "🤖 qq чат! Я бот, который позволит вам знать своё место\n\n"
    "В моем алгоритме используется система весов, чтобы очередь была честной:\n"
    "• Чем выше вес, тем больше шансов оказаться в начале.\n"
    "• Был первым - вес падает. Был в конце - вес растет.\n"
    "• Система самобалансирующаяся.\n\n"
    "Введи /help, чтобы увидеть список команд.",
    reply_markup=get_keyboard(message.from_user.id)
)

@router.message(Command("help"))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        text = "👮‍♂️ <b>Админка</b>\n🎲 <b>Сгенерировать</b> — создать новую очередь\n🔀 <b>Поменять местами</b> — ну, название вроде все объясняет.\n⭐ <b>Приоритеты</b> — выбрать тех, кто точно будет в ТОПЕ.\n🐌 <b>Опоздания</b> — выбрать тех, кто точно будет в КОНЦЕ.\n❌ <b>Исключить</b> — убрать из ротации.\n✅ <b>Включить</b> — вернуть в ротацию.\n🔄 <b>Включить всех</b> — быстро вернуть всех ротацию.\n⚠️ <b>Сброс весов</b> — установить всем одинаковый начальный вес.\n\n👤 <b>Общие команды:</b>\n📝 <b>Список</b> — посмотреть всех одногруппников и их статус.\n📜 <b>Текущая очередь</b> - объяснять не буду.\n📊 <b>Веса</b> — посмотреть текущие коэффициенты.\n\n<i>Также доступны текстовые команды:</i>\n<code>/swap 1 5</code> — поменять местами 1-го и 5-го."
    else:
        text = "👤 <b>Команды, на которые тебе хватит прав:</b>\n📜 <b>Текущая очередь</b> - объяснять не буду\n📝 <b>Список</b> — посмотреть всех одногруппников и их статус.\n📊 <b>Веса</b> — посмотреть текущие коэффициенты."
    await message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(user_id))

@router.message(Command("swap"))
async def cmd_swap_text(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id): return
    current_q = load_queue_from_db()
    if not current_q: return await message.answer("Очередь пуста")
    args = (command.args or "").split()
    if len(args) != 2: return await message.answer("Использование: /swap 1 5")
    try:
        p1, p2 = map(int, args)
        if not (0 < p1 <= len(current_q)) or not (0 < p2 <= len(current_q)): raise ValueError
    except: return await message.answer("Неверные индексы")
    
    s1_pre = next(x for x in current_q if x[0] == p1)
    s2_pre = next(x for x in current_q if x[0] == p2)
    if s1_pre[3] or s1_pre[4] or s2_pre[3] or s2_pre[4]:
        return await message.answer("⚠️ Нельзя менять приоритетных!")

    swap_queue_items(p1, p2)
    new_q = load_queue_from_db()
    regular_in_queue = [item for item in new_q if not item[3] and not item[4]]
    total_n = len(regular_in_queue)
    
    def get_rel_pos(pos_in_full):
        for i, item in enumerate(regular_in_queue, start=1):
            if item[0] == pos_in_full: return i
        return 1

    s1_post = next(x for x in new_q if x[0] == p1)
    s2_post = next(x for x in new_q if x[0] == p2)
    
    
    update_swap_weights(
        (s1_post[1], get_rel_pos(p1), s1_post[5]),
        (s2_post[1], get_rel_pos(p2), s2_post[5]),
        total_n
    )

    q_time = get_queue_time()
    await message.answer(f"🔄 Очередь обновлена ({q_time})", reply_markup=get_keyboard(message.from_user.id))