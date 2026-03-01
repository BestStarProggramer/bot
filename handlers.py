import logging
import re
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import ADMINS, RECENT_QUEUE_LIMIT
from database import (
    get_active_students, get_full_list, get_all_weights,
    toggle_student_status, enable_all_students, get_recent_queues,
    get_queue, get_student_current_weight, get_weight_history,
    get_student_name
)
from queue_logic import (
    generate_and_save_queue, swap_and_cascade, delete_student_from_queue_and_apply_penalty,
    add_new_student_to_queue_and_penalize
)

logging.basicConfig(level=logging.INFO)
router = Router()

priority_list = []
late_list = []
user_selections = {}  # temporary UI selections

def is_admin(user_id):
    return user_id in ADMINS

def get_keyboard(user_id, queue_id=None):
    if is_admin(user_id):
        buttons = []
        buttons.append([InlineKeyboardButton(text="🎲 Сгенерировать", callback_data="admin_gen")])
        # show swap only when viewing a specific queue (queue_id provided)
        if queue_id:
            buttons.append([InlineKeyboardButton(text="🔀 Поменять местами", callback_data=f"admin_swap_start_{queue_id}")])
        buttons.append([InlineKeyboardButton(text="⭐ Приоритеты", callback_data="sel_priority"), InlineKeyboardButton(text="🐌 Опоздания", callback_data="sel_late")])
        buttons.append([InlineKeyboardButton(text="✅ Включить", callback_data="sel_enable"), InlineKeyboardButton(text="❌ Исключить", callback_data="sel_disable")])
        # quick access: latest queue and full list
        buttons.append([InlineKeyboardButton(text="📌 Текущая очередь", callback_data="open_latest_queue"), InlineKeyboardButton(text="📜 Очереди", callback_data="pub_queues")])
        # admin per-queue actions (only when viewing a specific queue)
        if queue_id:
            buttons.append([InlineKeyboardButton(text="➕ Добавить студента", callback_data=f"admin_add_{queue_id}"), InlineKeyboardButton(text="➖ Удалить студента", callback_data=f"admin_del_{queue_id}")])
        buttons.append([InlineKeyboardButton(text="📝 Список", callback_data="pub_list"), InlineKeyboardButton(text="📊 Веса", callback_data="pub_weights")])
        buttons.append([InlineKeyboardButton(text="🔄 Включить всех", callback_data="admin_enable_all")])

        buttons.append([InlineKeyboardButton(text="📈 История весов", callback_data="pub_weight_history")])
    else:
        buttons = [
            [InlineKeyboardButton(text="📌 Текущая очередь", callback_data="open_latest_queue"), InlineKeyboardButton(text="📜 Очереди", callback_data="pub_queues")],
            [InlineKeyboardButton(text="📝 Список ID", callback_data="pub_list"), InlineKeyboardButton(text="📊 Шансы", callback_data="pub_weights")],
            [InlineKeyboardButton(text="📈 История весов", callback_data="pub_weight_history")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Simple selection UI functions kept similar to предыдущему проекту
def get_selection_keyboard(user_id):
    data = user_selections.get(user_id)
    if not data: return None
    action = data["action"]
    temp_selected = data["selected"]

    if action == "swap":
        # show current latest queue for swapping
        data = user_selections.get(user_id)
        use_qid = data.get("queue_id") if data else None
        if use_qid:
            q = get_queue(use_qid)
        else:
            latest = get_recent_queues(1)
            if not latest:
                return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚠️ Нет очередей", callback_data="cancel_selection")]])
            qid = latest[0][0]
            q = get_queue(qid)
        buttons = []
        row = []
        for item in q["items"]:
            pos, sid, is_p, is_l, w_before, w_after, is_added = item
            prefix = "⭐ " if is_p else "🐌 " if is_l else "😭 " if is_added else ""
            check = "✅ " if pos in temp_selected else ""
            name = get_student_name(sid)
            row.append(InlineKeyboardButton(text=f"{check}{pos}. {prefix}{name}", callback_data=f"swap_toggle_{pos}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        confirm_text = "🚀 ПОМЕНЯТЬ" if len(temp_selected) == 2 else "Выбери двоих"
        buttons.append([InlineKeyboardButton(text=confirm_text, callback_data="confirm_swap")])
        buttons.append([InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel_selection")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    # other selection types: enable/disable/priority/late
    # admin add/delete selection UIs
    if action in ("admin_add", "admin_del"):
        qid = data.get("queue_id")
        if qid is None:
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚠️ Нет очереди", callback_data="cancel_selection")]])
        buttons = []
        row = []
        if action == "admin_del":
            q = get_queue(qid)
            for itm in q["items"]:
                pos, sid, is_p, is_l, w_before, w_after, is_added = itm
                name = get_student_name(sid)
                check = "✅ " if pos in temp_selected else ""
                label = f"{check}{pos}. {name} {'⭐' if is_p else '🐌' if is_l else ''}"
                row.append(InlineKeyboardButton(text=label, callback_data=f"admin_del_toggle_{qid}_{pos}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
        else:  # admin_add
            students = get_full_list()
            q = get_queue(qid)
            present_ids = {itm[1] for itm in q["items"]}
            for s_id, name, active in students:
                if s_id in present_ids: continue
                check = "✅ " if s_id in temp_selected else ""
                row.append(InlineKeyboardButton(text=f"{check}{name}", callback_data=f"admin_add_toggle_{qid}_{s_id}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
        if row: buttons.append(row)
        # confirm / reset / cancel
        if action == "admin_add":
            buttons.append([InlineKeyboardButton(text="🚀 ДОБАВИТЬ", callback_data="admin_confirm_add")])
        else:
            buttons.append([InlineKeyboardButton(text="🚀 УДАЛИТЬ", callback_data="admin_confirm_del")])
        buttons.append([InlineKeyboardButton(text="🧹 Сбросить выбор", callback_data="clear_current_list")])
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

@router.callback_query(F.data.startswith("admin_swap_start"))
async def start_swap_ui(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return
    # determine which queue to operate on: allow callback like "admin_swap_start_{qid}"
    data = callback.data
    qid = None
    if data.startswith("admin_swap_start_"):
        try:
            qid = int(data.replace("admin_swap_start_", ""))
        except:
            qid = None
    if qid is None:
        recent = get_recent_queues(1)
        if not recent:
            await callback.answer("⚠️ Очередь пуста!", show_alert=True)
            return
        qid = recent[0][0]
    user_selections[callback.from_user.id] = {"action": "swap", "selected": [], "queue_id": qid}
    await callback.message.answer("🔀 Выбери двух человек:", reply_markup=get_selection_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(lambda c: re.match(r"^admin_del_\d+$", getattr(c, "data", "") or ""))
async def admin_delete_student_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return

    # Теперь callback.data гарантированно вида "admin_del_<digits>"
    rest = callback.data[len("admin_del_"):]
    qid = int(rest)
    q = get_queue(qid)
    if not q:
        await callback.answer("⚠️ Очередь не найдена", show_alert=True)
        return
    # initialize multi-select UI for deletion
    user_selections[callback.from_user.id] = {"action": "admin_del", "selected": [], "queue_id": qid}
    await callback.message.answer(f"Выбери позиции для удаления из очереди {qid}:", reply_markup=get_selection_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_confirm_"))
async def admin_delete_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return
    rest = callback.data[len("admin_del_confirm_"):]
    try:
        qid_s, pos_s = rest.split("_")
        qid = int(qid_s); pos = int(pos_s)
    except:
        await callback.answer("⚠️ Неверные данные", show_alert=True)
        return
    try:
        sid = delete_student_from_queue_and_apply_penalty(qid, pos)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return
    await callback.message.answer(f"Удалён студент {get_student_name(sid)}")
    await callback.answer()


@router.callback_query(lambda c: re.match(r"^admin_add_\d+$", getattr(c, "data", "") or ""))
async def admin_add_student_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return

    # Теперь callback.data гарантированно вида "admin_add_<digits>"
    rest = callback.data[len("admin_add_"):]
    qid = int(rest)
    all_students = get_full_list()
    q = get_queue(qid)
    if not q:
        await callback.answer("⚠️ Очередь не найдена", show_alert=True)
        return
    # initialize multi-select UI for adding
    user_selections[callback.from_user.id] = {"action": "admin_add", "selected": [], "queue_id": qid}
    await callback.message.answer(f"Выбери студентов для добавления в очередь {qid}:", reply_markup=get_selection_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_add_confirm_"))
async def admin_add_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return
    rest = callback.data[len("admin_add_confirm_"):]
    try:
        qid_s, sid_s = rest.split("_")
        qid = int(qid_s); sid = int(sid_s)
    except:
        await callback.answer("⚠️ Неверные данные", show_alert=True)
        return
    try:
        pos = add_new_student_to_queue_and_penalize(qid, sid)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return
    await callback.message.answer(f"Добавлен студент {get_student_name(sid)} на место {pos}")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_add_toggle_"))
async def admin_add_toggle(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or user_selections[u_id].get("action") != "admin_add":
        return
    rest = callback.data[len("admin_add_toggle_"):]
    try:
        qid_s, sid_s = rest.split("_")
        qid = int(qid_s); sid = int(sid_s)
    except:
        return
    sel = user_selections[u_id]["selected"]
    if sid in sel:
        sel.remove(sid)
    else:
        sel.append(sid)
    await callback.message.edit_reply_markup(reply_markup=get_selection_keyboard(u_id))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_toggle_"))
async def admin_del_toggle(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or user_selections[u_id].get("action") != "admin_del":
        return
    rest = callback.data[len("admin_del_toggle_"):]
    try:
        qid_s, pos_s = rest.split("_")
        qid = int(qid_s); pos = int(pos_s)
    except:
        return
    sel = user_selections[u_id]["selected"]
    if pos in sel:
        sel.remove(pos)
    else:
        sel.append(pos)
    await callback.message.edit_reply_markup(reply_markup=get_selection_keyboard(u_id))
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_add")
async def admin_confirm_add(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or user_selections[u_id].get("action") != "admin_add":
        await callback.answer("⚠️ Ничего не выбрано", show_alert=True)
        return
    qid = user_selections[u_id].get("queue_id")
    ids = user_selections[u_id].get("selected", [])
    if not ids:
        await callback.answer("⚠️ Ничего не выбрано", show_alert=True)
        return
    import database as db
    added = []
    for sid in ids:
        try:
            pos, w_before = db.add_student_to_existing_queue(qid, sid)
            # set weight_after equal to current student weight
            cur_w = db.get_student_current_weight(sid)
            db.set_queue_item_weights(qid, pos, w_before, cur_w)
            added.append((sid, pos))
        except Exception as e:
            await callback.message.answer(f"Ошибка при добавлении {get_student_name(sid)}: {e}")
    # build combined log
    if added:
        names = ", ".join(db.get_student_name(sid) for sid, _ in added)
        log_text = f"Добавлен студент {names}" if len(added) == 1 else f"Добавлены студенты: {names}"
        db.update_queue_timestamp_and_log(qid, log_text)
    # remove selection message
    try:
        await callback.message.delete()
    except:
        pass
    user_selections.pop(u_id, None)
    # send updated queue
    q = get_queue(qid)
    if q:
        meta = q["meta"]
        items = q["items"]
        qid, subject, created_at, updated_at, change_log = meta
        text = f"Очередь {subject}\nСоздана {created_at}\n"
        if (str(updated_at) != str(created_at)) or not (change_log and change_log.startswith("Создана")):
            text += f"Изменена {updated_at} ({change_log})\n\n"
        else:
            text += "\n"
        for itm in items:
            pos, sid, is_p, is_l, w_before, w_after, is_added = itm
            pref = "⭐ " if is_p else "🐌 " if is_l else "😭 " if is_added else ""
            name = get_student_name(sid)
            weight_display = w_after if w_after is not None else w_before
            text += f"{pos}. {pref}{name} — {weight_display:.2f}\n"
        await callback.message.answer(text, reply_markup=get_keyboard(u_id, queue_id=qid))
    else:
        await callback.message.answer("Добавление выполнено")
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_del")
async def admin_confirm_del(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or user_selections[u_id].get("action") != "admin_del":
        await callback.answer("⚠️ Ничего не выбрано", show_alert=True)
        return
    qid = user_selections[u_id].get("queue_id")
    positions = sorted(user_selections[u_id].get("selected", []))
    if not positions:
        await callback.answer("⚠️ Ничего не выбрано", show_alert=True)
        return
    removed = []
    # map original positions to student ids based on a snapshot
    q_snapshot = get_queue(qid)
    pos_to_sid = {itm[0]: itm[1] for itm in q_snapshot["items"]}
    sids = [pos_to_sid.get(p) for p in positions if pos_to_sid.get(p) is not None]
    for sid in sids:
        # find current position for this student
        q_now = get_queue(qid)
        cur_item = next((it for it in q_now["items"] if it[1] == sid), None)
        if not cur_item: continue
        cur_pos = cur_item[0]
        try:
            deleted_sid = delete_student_from_queue_and_apply_penalty(qid, cur_pos, defer_log=True)
            removed.append(deleted_sid)
        except Exception as e:
            await callback.message.answer(f"Ошибка при удалении {get_student_name(sid)}: {e}")
    # build combined log and update queue record
    import database as db
    if removed:
        names = ", ".join(db.get_student_name(sid) for sid in removed)
        log_text = f"Удалён студент {names}" if len(removed) == 1 else f"Удалены студенты: {names}"
        db.update_queue_timestamp_and_log(qid, log_text)
    # remove selection message
    try:
        await callback.message.delete()
    except:
        pass
    user_selections.pop(u_id, None)
    # send updated queue
    q = get_queue(qid)
    if q:
        meta = q["meta"]
        items = q["items"]
        qid, subject, created_at, updated_at, change_log = meta
        text = f"Очередь {subject}\nСоздана {created_at}\n"
        if (str(updated_at) != str(created_at)) or not (change_log and change_log.startswith("Создана")):
            text += f"Изменена {updated_at} ({change_log})\n\n"
        else:
            text += "\n"
        for itm in items:
            pos, sid, is_p, is_l, w_before, w_after, is_added = itm
            pref = "⭐ " if is_p else "🐌 " if is_l else "😭 " if is_added else ""
            name = get_student_name(sid)
            weight_display = w_after if w_after is not None else w_before
            text += f"{pos}. {pref}{name} — {weight_display:.2f}\n"
        await callback.message.answer(text, reply_markup=get_keyboard(u_id, queue_id=qid))
    else:
        await callback.message.answer("Удаление выполнено")
    await callback.answer()


@router.callback_query(F.data == "open_latest_queue")
async def open_latest(callback: CallbackQuery):
    recent = get_recent_queues(1)
    if not recent:
        await callback.answer("⚠️ Нет сохранённых очередей!", show_alert=True)
        return
    qid = recent[0][0]
    # reuse open_queue flow by calling get_queue and rendering
    q = get_queue(qid)
    if not q:
        await callback.answer("⚠️ Очередь не найдена", show_alert=True)
        return
    meta = q["meta"]
    items = q["items"]
    qid, subject, created_at, updated_at, change_log = meta
    text = f"Очередь {subject}\nСоздана {created_at}\n"
    if (str(updated_at) != str(created_at)) or not (change_log and change_log.startswith("Создана")):
        text += f"Изменена {updated_at} ({change_log})\n\n"
    else:
        text += "\n"
    for itm in items:
        pos, sid, is_p, is_l, w_before, w_after, is_added = itm
        pref = "⭐ " if is_p else "🐌 " if is_l else "😭 " if is_added else ""
        name = get_student_name(sid)
        weight_display = w_after if w_after is not None else w_before
        text += f"{pos}. {pref}{name} — {weight_display:.2f}\n"
    kb = get_keyboard(callback.from_user.id, queue_id=qid)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "pub_queues")
async def show_queues_list(callback: CallbackQuery):
    # Показываем список последних очередей (до HISTORY_LIMIT)
    qlist = get_recent_queues()
    if not qlist:
        await callback.answer("⚠️ Нет сохранённых очередей!", show_alert=True)
        return
    text = "📜 <b>Список очередей:</b>\n\n"
    kb_rows = []
    for q in qlist:
        qid, subject, created, updated, changelog = q
        display = f"{created} — {subject}"
        kb_rows.append([InlineKeyboardButton(text=display, callback_data=f"open_queue_{qid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("open_queue_"))
async def open_queue(callback: CallbackQuery):
    qid = int(callback.data.replace("open_queue_", ""))
    q = get_queue(qid)
    if not q:
        await callback.answer("⚠️ Очередь не найдена", show_alert=True)
        return
    meta = q["meta"]
    items = q["items"]
    qid, subject, created_at, updated_at, change_log = meta
    text = f"Очередь {subject}\nСоздана {created_at}\n"
    # don't show "Изменена" for a freshly created queue where updated==created and log indicates creation
    if (str(updated_at) != str(created_at)) or not (change_log and change_log.startswith("Создана")):
        text += f"Изменена {updated_at} ({change_log})\n\n"
    else:
        text += "\n"
    for itm in items:
        pos, sid, is_p, is_l, w_before, w_after, is_added = itm
        pref = "⭐ " if is_p else "🐌 " if is_l else "😭 " if is_added else ""
        name = get_student_name(sid)
        weight_display = w_after if w_after is not None else w_before
        text += f"{pos}. {pref}{name} — {weight_display:.2f}\n"
    kb = get_keyboard(callback.from_user.id, queue_id=qid)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "pub_list")
async def pub_list(callback: CallbackQuery):
    students = get_full_list()
    text = "📝 <b>Список:</b>\n\n"
    for s_id, name, active in students:
        text += f"<code>{s_id}</code>: {name} {'✅' if active else '❌'}\n"
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "pub_weights")
async def pub_weights(callback: CallbackQuery):
    students = get_all_weights()
    text = "📊 <b>Веса:</b>\n\n"
    for name, weight in students:
        text += f"{name}: <code>{weight:.2f}</code>\n"
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "pub_weight_history")
async def pub_weight_history(callback: CallbackQuery):
    # show list of students to pick
    students = get_full_list()
    buttons = []
    row = []
    for s_id, name, active in students:
        row.append(InlineKeyboardButton(text=f"{name}", callback_data=f"hist_weights_select_{s_id}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel_selection")])
    await callback.message.answer("Выбери студента для просмотра истории весов:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("hist_weights_select_"))
async def show_weight_history(callback: CallbackQuery):
    sid = int(callback.data.replace("hist_weights_select_", ""))
    # fetch last 11 records so we can present transitions (prev -> cur) for up to 10 changes
    history = get_weight_history(sid, limit=11)
    if not history:
        await callback.answer("⚠️ Нет истории для этого студента", show_alert=True)
        return
    # history currently returns rows in DESC order (newest first). Reverse to chronological.
    hist_chrono = list(reversed(history))
    # produce transitions: prev -> cur with place info from cur
    transitions = []
    for i in range(1, len(hist_chrono)):
        prev_w, prev_ts, _ = hist_chrono[i-1]
        cur_w, cur_ts, place = hist_chrono[i]
        place_txt = f" [{place}]" if place else ""
        transitions.append((prev_ts, cur_ts, prev_w, cur_w, place_txt))
    # if there is only one record, show single value
    text = f"📈 <b>История весов студента {sid} (последние {min(10, len(transitions) if transitions else 1)}):</b>\n\n"
    if transitions:
        for prev_ts, cur_ts, prev_w, cur_w, place_txt in transitions[-10:]:
            text += f"{cur_ts}: {prev_w:.2f} → {cur_w:.2f}{place_txt}\n"
    else:
        # only one record available
        w, ts, place = hist_chrono[-1]
        place_txt = f" [{place}]" if place else ""
        text += f"{ts}: {w:.2f}{place_txt}\n"
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "cancel_selection")
async def cancel_selection_handler(callback: CallbackQuery):
    user_selections.pop(callback.from_user.id, None)
    try:
        await callback.message.delete()
    except:
        await callback.message.edit_text("❌ Отменено.", reply_markup=None)
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
    if u_id not in user_selections or user_selections[u_id]["action"] != "swap":
        return
    pos = int(callback.data.replace("swap_toggle_", ""))
    selected = user_selections[u_id]["selected"]
    # ensure we operate on the correct queue and disallow selecting priority/late
    qid = user_selections[u_id].get("queue_id")
    if qid is None:
        recent = get_recent_queues(1)
        qid = recent[0][0] if recent else None
    if qid:
        q = get_queue(qid)
        item = next((it for it in q["items"] if it[0] == pos), None)
        if item and (item[2] or item[3] or (len(item) >= 7 and item[6])):
            await callback.answer("⚠️ Нельзя выбирать приоритетных/опоздавших/добавленных", show_alert=True)
            return
    if pos in selected:
        selected.remove(pos)
    elif len(selected) < 2:
        selected.append(pos)
    else:
        # already have 2 selected, ignore additional selection
        await callback.answer("⚠️ Можно выбрать только двоих", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=get_selection_keyboard(u_id))
    await callback.answer()

@router.callback_query(F.data == "confirm_swap")
async def confirm_swap_ui(callback: CallbackQuery):
    u_id = callback.from_user.id
    if u_id not in user_selections or len(user_selections[u_id]["selected"]) != 2:
        await callback.answer("⚠️ Выбери двоих!", show_alert=True)
        return
    p1, p2 = user_selections[u_id]["selected"]
    # operate on latest queue
    qid = user_selections[u_id].get("queue_id")
    if qid is None:
        recent = get_recent_queues(1)
        if not recent:
            await callback.answer("⚠️ Нет очереди", show_alert=True)
            return
        qid = recent[0][0]
    try:
        swap_and_cascade(qid, p1, p2)
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)
        return
    user_selections.pop(u_id, None)
    await callback.message.edit_text("🔄 Очередь обновлена", reply_markup=get_keyboard(u_id, queue_id=qid))
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

# admin actions

@router.callback_query(F.data.startswith("admin_"))
async def handle_admin_btn(callback: CallbackQuery):
    u_id = callback.from_user.id
    if not is_admin(u_id):
        await callback.answer("⛔ Нет прав! Знай свой место!", show_alert=True)
        return
    if callback.data == "admin_gen":
        # ask user for subject via simple reply (we'll accept inline subject input via message)
        await callback.message.answer("Введи название предмета для новой очереди (например, \"Физика\"):")
        user_selections[u_id] = {"action": "await_subject_for_gen", "selected": None}
        await callback.answer()
        return
    elif callback.data == "admin_enable_all":
        enable_all_students()
        await callback.message.answer("✅ Все включены", reply_markup=get_keyboard(u_id))
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
        text = (
            "👮‍♂️ <b>Админка</b>\n"
            "🎲 <b>Сгенерировать</b> — создать новую очередь (бот спросит название предмета).\n"
            "🔀 <b>Поменять местами</b> — интерактивно выбрать двух человек в очереди и поменять их места.\n"
            "⭐ <b>Приоритеты</b> — выделить студентов, которые должны быть вверху (не затрагивает веса напрямую до генерации).\n"
            "🐌 <b>Опоздания</b> — выделить студентов, которые должны быть внизу очереди.\n"
            "❌ <b>Исключить</b> — временно убрать человека из ротации (статус выключен).\n"
            "✅ <b>Включить</b> — вернуть человека в ротацию.\n"
            "🔄 <b>Включить всех</b> — быстро восстановить всех студентов в ротации.\n\n"
            "🧩 <b>Админские действия над очередью (появляются при просмотре конкретной очереди):</b>\n"
            "➕ <b>Добавить студента</b> — добавить выбранного студента в текущую очередь.\n"
            "➖ <b>Удалить студента</b> — удалить выбранного студента из текущей очереди.\n\n"
            "👤 <b>Общие команды (доступны всем):</b>\n"
            "📌 <b>Текущая очередь</b> — показать последнюю сохранённую очередь: позиции, пометки (приоритет/опоздание/добавлен) и отображаемые веса.\n"
            "📈 <b>История весов</b> — посмотреть историю изменений веса конкретного студента (переходы prev → cur с датами и местом в очереди, если доступно).\n"
            "📜 <b>Очереди</b> — список сохранённых очередей.\n"
            "📝 <b>Список</b> — посмотреть всех одногруппников и их статус (включён/выключен).\n"
            "📊 <b>Веса</b> — посмотреть текущие коэффициенты (шансы).\n"
        )
    else:
        text = (
            "👤 <b>Команды, на которые тебе хватит прав:</b>\n"
            "📌 <b>Текущая очередь</b> — показать последнюю сохранённую очередь с позициями и видимыми весами.\n"
            "📈 <b>История весов</b> — выбрать студента и посмотреть, как менялся его вес во времени.\n"
            "📜 <b>Очереди</b> — список сохранённых очередей.\n"
            "📝 <b>Список</b> — посмотреть всех одногруппников и их статус.\n"
            "📊 <b>Веса</b> — посмотреть текущие коэффициенты (шансы).\n"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=get_keyboard(user_id))

@router.message()
async def generic_text_handler(message: Message):
    u_id = message.from_user.id
    sel = user_selections.get(u_id)
    if sel and sel.get("action") == "await_subject_for_gen":
        subject = message.text.strip()
        # попытка сгенерировать очередь
        try:
            qid = generate_and_save_queue(subject, priority_ids=priority_list, late_ids=late_list)
        except Exception as e:
            await message.answer(f"Ошибка генерации: {e}")
            user_selections.pop(u_id, None)
            return

        # очистка временных списков и статуса
        priority_list.clear()
        late_list.clear()
        user_selections.pop(u_id, None)

        # вывести только что созданную очередь
        q = get_queue(qid)
        meta = q["meta"]
        items = q["items"]
        qid, subject, created_at, updated_at, change_log = meta
        text = f"Очередь {subject}\n"
        text += f"Создана {created_at}\n"
        if (str(updated_at) != str(created_at)) or not (change_log and change_log.startswith("Создана")):
            text += f"Изменена {updated_at} ({change_log})\n\n"
        else:
            text += "\n"
        for itm in items:
            pos, sid, is_p, is_l, w_before, w_after, is_added = itm
            pref = "⭐ " if is_p else "🐌 " if is_l else "😭 " if is_added else ""
            name = get_student_name(sid)
            weight_display = w_after if w_after is not None else w_before
            text += f"{pos}. {pref}{name} — {weight_display:.2f}\n"

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_keyboard(u_id, queue_id=qid)
        )
        return
    return

@router.message(Command("swap"))
async def cmd_swap_text(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id): return
    recent = get_recent_queues(1)
    if not recent: return await message.answer("Очередь пуста")
    qid = recent[0][0]
    current_q = get_queue(qid)
    if not current_q: return await message.answer("Очередь пуста")
    args = (command.args or "").split()
    if len(args) != 2: return await message.answer("Использование: /swap 1 5")
    try:
        p1, p2 = map(int, args)
        # validate positions
        positions = [itm[0] for itm in current_q["items"]]
        if p1 not in positions or p2 not in positions:
            raise ValueError
    except:
        return await message.answer("Неверные индексы")
    # check priority/late
    s1_pre = next(x for x in current_q["items"] if x[0] == p1)
    s2_pre = next(x for x in current_q["items"] if x[0] == p2)
    # disallow swapping priority/late/added
    if s1_pre[2] or s1_pre[3] or (len(s1_pre) >= 7 and s1_pre[6]) or s2_pre[2] or s2_pre[3] or (len(s2_pre) >= 7 and s2_pre[6]):
        return await message.answer("⚠️ Нельзя менять приоритетных/опоздавших/добавленных!")
    try:
        swap_and_cascade(qid, p1, p2)
    except Exception as e:
        return await message.answer(f"Ошибка: {e}")
    await message.answer(f"🔄 Очередь обновлена", reply_markup=get_keyboard(message.from_user.id))

@router.message(Command("reset"))
async def cmd_reset(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав! Знай свой место!")
        return
    import sqlite3
    from config import DB_NAME
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE students SET weight=1.0")
        cur.execute("DELETE FROM weight_history")
        conn.commit()
    await message.answer("⚠️ Веса сброшены", reply_markup=get_keyboard(message.from_user.id))