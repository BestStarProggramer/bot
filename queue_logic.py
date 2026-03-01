import random
import math
from config import K_FACTOR, RECENT_QUEUE_LIMIT
from database import (
    update_weight, get_active_students, set_student_weight_direct,
    create_queue_record, add_queue_item, get_recent_queues, get_queue,
    set_queue_item_weights, get_following_queue_ids, get_student_current_weight,
    get_weight_history, add_student_to_existing_queue, delete_queue_item, update_queue_timestamp_and_log,
    get_student_name
)

# --- Weight math ---

def calculate_new_weight(current_weight, position, total_n):
    """
    Корректный пересчёт веса:
    - для верхних позиций вес уменьшается,
    - для нижних позиций вес увеличивается.
    Ограничение результата в диапазоне [0.1, 10].
    """
    if total_n <= 1:
        return current_weight
    # позиция относительно центра: отрицательно для первых позиций, положительно для последних
    mid = (total_n + 1) / 2.0
    delta = (position - mid) / total_n  # примерно в диапазоне (-0.5 .. 0.5)
    # правильный знак: если delta < 0 (первые позиции) => exp(K*delta) < 1 => вес падает
    new_weight = current_weight * math.exp(K_FACTOR * delta)
    # clamp
    new_weight = max(0.1, min(new_weight, 10.0))
    return new_weight

# --- Weighted permutation ---

def weighted_permutation(students, priority_ids=None, late_ids=None):
    """
    students: list of tuples (id, name, weight)
    priority_ids, late_ids: lists of ids
    Возвращает список тех же tuples в порядке очереди:
      priority_students (в порядке передачи) + random weighted + late_students (в порядке передачи)
    """
    priority_ids = set(priority_ids or [])
    late_ids = set(late_ids or [])

    prios = [s for s in students if s[0] in priority_ids]
    lates = [s for s in students if s[0] in late_ids]
    pool = [s for s in students if s[0] not in priority_ids and s[0] not in late_ids]

    # Weighted random sample without replacement for pool
    random_part = []
    available = pool.copy()
    while available:
        total_weight = sum(max(0.0001, a[2]) for a in available)
        r = random.uniform(0, total_weight)
        upto = 0.0
        for s in available:
            upto += max(0.0001, s[2])
            if upto >= r:
                random_part.append(s)
                available.remove(s)
                break

    return prios + random_part + lates

# --- High-level operations ---

def generate_and_save_queue(subject, priority_ids=None, late_ids=None):
    """
    Создаёт очередь: сохраняет в queues и queue_items, обновляет веса (weight_after)
    Возвращает id новой очереди.
    """
    students = get_active_students()
    if not students:
        raise RuntimeError("Нет активных студентов")

    priority_ids = priority_ids or []
    late_ids = late_ids or []
    raw_queue = weighted_permutation(students, priority_ids=priority_ids, late_ids=late_ids)
    qid = create_queue_record(subject)

    # Сначала добавим все записи с weight_before
    position = 1
    for s in raw_queue:
        sid, name, w = s
        is_p = 1 if sid in priority_ids else 0
        is_l = 1 if sid in late_ids else 0
        add_queue_item(qid, position, sid, is_p, is_l, w, None)
        position += 1

    # Теперь пересчитаем веса для регулярных студентов в этой очереди и запишем weight_after
    # regular positions: относительный порядок среди тех кто не priority/late
    # build list of regular items (position, student_id, weight_before)
    q = get_queue(qid)
    items = q["items"]
    # regular positions: относительный порядок среди тех кто не priority/late
    # we'll build ordered list below

    # simpler: iterate through items to gather regulars preserving order
    regulars_ordered = []
    for itm in items:
        pos_full, student_id, is_p, is_l, weight_before, _, is_added = itm
        if not is_p and not is_l:
            regulars_ordered.append((pos_full, student_id, weight_before))

    total_reg = len(regulars_ordered)
    # compute new weights and update DB & students table + weight_history
    rel_pos = 1
    for pos_full, sid, w_before in regulars_ordered:
        new_w = calculate_new_weight(w_before, rel_pos, total_reg)
        set_queue_item_weights(qid, pos_full, w_before, new_w)
        update_weight(sid, new_w, place_info=f"очередь {qid}: место {rel_pos}/{total_reg} (генерация)")
        rel_pos += 1

    # For priority and late students set weight_after equal to their weight_before (no change)
    for itm in items:
        pos_full, sid, is_p, is_l, w_before, w_after, is_added = itm
        if is_p or is_l or is_added:
            set_queue_item_weights(qid, pos_full, w_before, w_before)

    return qid

def swap_and_cascade(queue_id, pos1, pos2):
    """
    Поменять местами в queue_id позиции pos1 и pos2.
    Если очередь не последняя, выполнить каскадный пересчёт весов для всех subsequent queues.
    """
    # 1) Получим текущие пункты и проверим запреты на priority/late
    q = get_queue(queue_id)
    if not q:
        raise ValueError("Очередь не найдена")
    items = q["items"]
    # find items by position
    pos_map = {itm[0]: itm for itm in items}
    if pos1 not in pos_map or pos2 not in pos_map:
        raise ValueError("Неверные позиции")
    s1 = pos_map[pos1]
    s2 = pos_map[pos2]
    # disallow swapping priority, late or added students
    if s1[2] or s1[3] or (len(s1) >= 7 and s1[6]) or s2[2] or s2[3] or (len(s2) >= 7 and s2[6]):
        raise RuntimeError("Нельзя менять приоритетных/опоздавших/добавленных")

    # swap in the specified queue
    from database import swap_queue_positions
    swap_queue_positions(queue_id, pos1, pos2)
    # Recompute weights inside this queue: only for regulars
    q_after = get_queue(queue_id)
    items_after = q_after["items"]
    regulars = [(itm[0], itm[1], itm[4]) for itm in items_after if itm[2]==0 and itm[3]==0 and (len(itm) < 7 or itm[6]==0)]
    total_reg = len(regulars)
    # compute new weight_after for all regulars in this queue based on their relative position among regulars
    rel = 1
    for pos_full, sid, w_before in regulars:
        new_w = calculate_new_weight(w_before, rel, total_reg)
        set_queue_item_weights(queue_id, pos_full, w_before, new_w)
        update_weight(sid, new_w, place_info=f"очередь {queue_id}: место {rel}/{total_reg} (смена мест)")
        rel += 1

    # For priority/late leave as before (we'll set weight_after = weight_before)
    for itm in items_after:
        pos_full, sid, is_p, is_l, w_before, w_after, is_added = itm
        if is_p or is_l or is_added:
            set_queue_item_weights(queue_id, pos_full, w_before, w_before)

    # Now cascade to following queues: for each following queue, for any students that changed position in previous step,
    # recalc their weight_before/after based on their position among regulars in that queue, using their latest weight as input.
    following = get_following_queue_ids(queue_id)
    affected_student_ids = {s1[1], s2[1]}
    for fq in following:
        fq_data = get_queue(fq)
        if not fq_data: continue
        fq_items = fq_data["items"]
        # if in this queue affected students present and are regular, recalc their weight_before (which becomes their previous weight_after) and weight_after
        # we need to compute relative ordering of regulars and then compute new weights (but only for affected students)
        regulars_ordered = []
        for itm in fq_items:
            pos_full, sid, is_p, is_l, w_before, w_after, is_added = itm
            if not is_p and not is_l and not is_added:
                regulars_ordered.append((pos_full, sid, w_before))
        total_reg = len(regulars_ordered)
        # build mapping from sid -> rel_pos
        rel_pos_map = {}
        rel_index = 1
        for pos_full, sid, w_before in regulars_ordered:
            rel_pos_map[sid] = rel_index
            rel_index += 1
        for sid in list(affected_student_ids):
                if sid in rel_pos_map:
                    relp = rel_pos_map[sid]
                    # get current weight for sid (latest overall)
                    cur_w = get_student_current_weight(sid)
                    # use cur_w as weight_before in this subsequent queue for recalculation
                    new_w = calculate_new_weight(cur_w, relp, total_reg)
                    # find position in this queue
                    pos_in_queue = next((itm[0] for itm in fq_items if itm[1]==sid), None)
                    if pos_in_queue is not None:
                        set_queue_item_weights(fq, pos_in_queue, cur_w, new_w)
                        update_weight(sid, new_w, place_info=f"очередь {fq}: место {relp}/{total_reg} (каскад)")
        # continue cascade: the affected students keep same ids (they may be present in further queues too)
    # update logs (include student names)
    name1 = get_student_name(s1[1])
    name2 = get_student_name(s2[1])
    update_queue_timestamp_and_log(queue_id, f"Смена мест: {pos1} {name1} ↔ {pos2} {name2}")
    # (последующие очереди тоже можно пометить, но достаточно логов в изменённой очереди)
    return True

def delete_student_from_queue_and_apply_penalty(queue_id, position, defer_log=False):
    """
    Удаляет студента из queue_id по позиции.
    Откатывает его вес к weight_before (значение ДО генерации этой очереди).
    Удаляет студента и сдвигает остальные позиции.
    Затем выполняет каскадный пересчет для всех следующих очередей.
    Возвращает student_id.
    """
    import database as db
    q = db.get_queue(queue_id)
    if not q:
        raise ValueError("Очередь не найдена")
    # find item row to delete
    row = next((it for it in q["items"] if it[0]==position), None)
    if not row:
        raise ValueError("Позиция не найдена")
    
    pos_full, sid, is_p, is_l, weight_before, weight_after, is_added = row
    
    # Откатить вес студента к weight_before (состояние до генерации этой очереди)
    db.set_student_weight_direct(sid, weight_before)
    db.update_weight(sid, weight_before, place_info=f"удалён из очереди {queue_id} (откат к весу до генерации)")
    
    # delete from queue items (delete_queue_item will shift positions)
    db.delete_queue_item(queue_id, position)
    if not defer_log:
        update_queue_timestamp_and_log(queue_id, f"Удалён студент {db.get_student_name(sid)} с места {position}")
    
    # Now cascade to following queues: пересчитать веса для этого студента во всех следующих очередях
    following = get_following_queue_ids(queue_id)
    affected_student_ids = {sid}
    
    for fq in following:
        fq_data = db.get_queue(fq)
        if not fq_data: continue
        fq_items = fq_data["items"]
        
        # Check if this student is in this following queue
        student_in_fq = next((it for it in fq_items if it[1] == sid), None)
        if not student_in_fq:
            # Student not in this queue, skip
            continue
        
        # Student is present; compute relative ordering among regulars and recalc weight
        regulars_ordered = []
        for itm in fq_items:
            pos_full, s_id, is_p, is_l, w_before, w_after, is_added = itm
            if not is_p and not is_l and not is_added:
                regulars_ordered.append((pos_full, s_id, w_before))
        
        total_reg = len(regulars_ordered)
        
        # Find relative position of sid among regulars
        rel_pos_map = {}
        rel_index = 1
        for pos_full, s_id, w_before in regulars_ordered:
            rel_pos_map[s_id] = rel_index
            rel_index += 1
        
        if sid in rel_pos_map:
            relp = rel_pos_map[sid]
            # Get current weight (already rolled back to weight_before of previous queue)
            cur_w = db.get_student_current_weight(sid)
            # Calculate new weight for this position in this queue
            new_w = calculate_new_weight(cur_w, relp, total_reg)
            # Find position in this queue
            pos_in_queue = next((itm[0] for itm in fq_items if itm[1]==sid), None)
            if pos_in_queue is not None:
                set_queue_item_weights(fq, pos_in_queue, cur_w, new_w)
                db.update_weight(sid, new_w, place_info=f"очередь {fq}: место {relp}/{total_reg} (каскад после удаления)")
    
    return sid

def add_new_student_to_queue_and_penalize(queue_id, student_id, is_priority=0, is_late=0):
    """
    Добавляет студента в конец очереди (если его не было).
    Веса не меняются.
    Возвращает position.
    """
    import database as db
    # if student already in queue, do nothing / raise
    q = db.get_queue(queue_id)
    if not q:
        raise ValueError("Очередь не найдена")
    if any(it[1]==student_id for it in q["items"]):
        raise ValueError("Студент уже в очереди")
    # get current weight from students table
    cur_w = db.get_student_current_weight(student_id)
    # add to queue with is_added flag
    pos, w_before = db.add_student_to_existing_queue(queue_id, student_id, is_priority, is_late)
    # set weight_after equal to current weight (no change)
    set_queue_item_weights(queue_id, pos, w_before, cur_w)
    update_queue_timestamp_and_log(queue_id, f"Добавлен студент {db.get_student_name(student_id)} в конец очереди")
    return pos

def get_latest_queue():
    recent = get_recent_queues(1)
    return recent[0] if recent else None