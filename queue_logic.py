import random
import math
from typing import List, Tuple, Optional, Dict, Any, Set
from config import K_FACTOR, MIN_WEIGHT_THRESHOLD, WEIGHT_MIN_LIMIT, WEIGHT_MAX_LIMIT
from database import (
    update_weight, get_active_students, set_student_weight_direct,
    create_queue_record, add_queue_item, get_recent_queues, get_queue,
    set_queue_item_weights, get_following_queue_ids, get_student_current_weight,
    get_weight_history, add_student_to_existing_queue, delete_queue_item, update_queue_timestamp_and_log,
    get_student_name, swap_queue_positions
)

def calculate_new_weight(current_weight: float, position: int, total_n: int) -> float:
    if total_n <= 1:
        return current_weight
    mid = (total_n + 1) / 2.0
    delta = (position - mid) / total_n
    new_weight = current_weight * math.exp(K_FACTOR * delta)
    new_weight = max(WEIGHT_MIN_LIMIT, min(new_weight, WEIGHT_MAX_LIMIT))
    return new_weight

def weighted_permutation(students: List[Tuple[int, str, float]], priority_ids: Optional[List[int]] = None, late_ids: Optional[List[int]] = None) -> List[Tuple[int, str, float]]:
    priority_ids = set(priority_ids or [])
    late_ids = set(late_ids or [])

    prios = [s for s in students if s[0] in priority_ids]
    lates = [s for s in students if s[0] in late_ids]
    pool = [s for s in students if s[0] not in priority_ids and s[0] not in late_ids]

    random_part = []
    available = pool.copy()
    while available:
        total_weight = sum(max(MIN_WEIGHT_THRESHOLD, a[2]) for a in available)
        r = random.uniform(0, total_weight)
        upto = 0.0
        for s in available:
            upto += max(MIN_WEIGHT_THRESHOLD, s[2])
            if upto >= r:
                random_part.append(s)
                available.remove(s)
                break

    return prios + random_part + lates

def _validate_swap(queue_id: int, pos1: int, pos2: int) -> Dict[str, Any]:
    q = get_queue(queue_id)
    if not q:
        raise ValueError("Очередь не найдена")
    items = q["items"]
    pos_map = {itm[0]: itm for itm in items}
    if pos1 not in pos_map or pos2 not in pos_map:
        raise ValueError("Неверные позиции")
    s1 = pos_map[pos1]
    s2 = pos_map[pos2]
    if s1[2] or s1[3] or s2[2] or s2[3]:
        raise RuntimeError("Нельзя менять приоритетных/опоздавших/добавленных")
    return {"queue": q, "s1": s1, "s2": s2, "items": items}

def _perform_swap(queue_id: int, pos1: int, pos2: int) -> None:
    swap_queue_positions(queue_id, pos1, pos2)

def _recalculate_queue_weights(queue_id: int) -> List[Tuple[int, float]]:
    q_after = get_queue(queue_id)
    items_after = q_after["items"]
    regulars = [(itm[0], itm[1], itm[4]) for itm in items_after if itm[2]==0 and itm[3]==0 and (len(itm) < 7 or itm[6]==0)]
    total_reg = len(regulars)
    updated_weights = []
    rel = 1
    for pos_full, sid, w_before in regulars:
        new_w = calculate_new_weight(w_before, rel, total_reg)
        set_queue_item_weights(queue_id, pos_full, w_before, new_w)
        update_weight(sid, new_w, place_info=f"очередь {queue_id}: место {rel}/{total_reg} (смена мест)")
        updated_weights.append((sid, new_w))
        rel += 1
    for itm in items_after:
        pos_full, sid, is_p, is_l, w_before, w_after, is_added = itm
        if is_p or is_l or is_added:
            set_queue_item_weights(queue_id, pos_full, w_before, w_before)
    return updated_weights

def _cascade_update(queue_id: int, affected_student_ids: Set[int]) -> None:
    following = get_following_queue_ids(queue_id)
    for fq in following:
        fq_data = get_queue(fq)
        if not fq_data:
            continue
        fq_items = fq_data["items"]
        regulars_ordered = []
        for itm in fq_items:
            pos_full, sid, is_p, is_l, w_before, w_after, is_added = itm
            if not is_p and not is_l and not is_added:
                regulars_ordered.append((pos_full, sid, w_before))
        total_reg = len(regulars_ordered)
        rel_pos_map = {}
        rel_index = 1
        for pos_full, sid, w_before in regulars_ordered:
            rel_pos_map[sid] = rel_index
            rel_index += 1
        for sid in list(affected_student_ids):
            if sid in rel_pos_map:
                relp = rel_pos_map[sid]
                cur_w = get_student_current_weight(sid)
                new_w = calculate_new_weight(cur_w, relp, total_reg)
                pos_in_queue = next((itm[0] for itm in fq_items if itm[1]==sid), None)
                if pos_in_queue is not None:
                    set_queue_item_weights(fq, pos_in_queue, cur_w, new_w)
                    update_weight(sid, new_w, place_info=f"очередь {fq}: место {relp}/{total_reg} (каскад)")

def swap_and_cascade(queue_id: int, pos1: int, pos2: int) -> bool:
    validation_data = _validate_swap(queue_id, pos1, pos2)
    s1 = validation_data["s1"]
    s2 = validation_data["s2"]
    _perform_swap(queue_id, pos1, pos2)
    _recalculate_queue_weights(queue_id)
    affected_student_ids = {s1[1], s2[1]}
    _cascade_update(queue_id, affected_student_ids)
    name1 = get_student_name(s1[1])
    name2 = get_student_name(s2[1])
    update_queue_timestamp_and_log(queue_id, f"Смена мест: {pos1} {name1} ↔ {pos2} {name2}")
    return True

def generate_and_save_queue(subject: str, priority_ids: Optional[List[int]] = None, late_ids: Optional[List[int]] = None) -> int:
    students = get_active_students()
    if not students:
        raise RuntimeError("Нет активных студентов")

    priority_ids = priority_ids or []
    late_ids = late_ids or []
    raw_queue = weighted_permutation(students, priority_ids=priority_ids, late_ids=late_ids)
    qid = create_queue_record(subject)

    position = 1
    for s in raw_queue:
        sid, name, w = s
        is_p = 1 if sid in priority_ids else 0
        is_l = 1 if sid in late_ids else 0
        add_queue_item(qid, position, sid, is_p, is_l, w, None)
        position += 1

    q = get_queue(qid)
    items = q["items"]

    regulars_ordered = []
    for itm in items:
        pos_full, student_id, is_p, is_l, weight_before, _, is_added = itm
        if not is_p and not is_l:
            regulars_ordered.append((pos_full, student_id, weight_before))

    total_reg = len(regulars_ordered)
    rel_pos = 1
    for pos_full, sid, w_before in regulars_ordered:
        new_w = calculate_new_weight(w_before, rel_pos, total_reg)
        set_queue_item_weights(qid, pos_full, w_before, new_w)
        update_weight(sid, new_w, place_info=f"очередь {qid}: место {rel_pos}/{total_reg} (генерация)")
        rel_pos += 1

    for itm in items:
        pos_full, sid, is_p, is_l, w_before, w_after, is_added = itm
        if is_p or is_l or is_added:
            set_queue_item_weights(qid, pos_full, w_before, w_before)

    return qid

def delete_student_from_queue_and_apply_penalty(queue_id: int, position: int, defer_log: bool = False) -> int:
    import database as db
    q = db.get_queue(queue_id)
    if not q:
        raise ValueError("Очередь не найдена")
    row = next((it for it in q["items"] if it[0]==position), None)
    if not row:
        raise ValueError("Позиция не найдена")
    
    pos_full, sid, is_p, is_l, weight_before, weight_after, is_added = row
    
    db.set_student_weight_direct(sid, weight_before)
    db.update_weight(sid, weight_before, place_info=f"удалён из очереди {queue_id} (откат к весу до генерации)")
    
    db.delete_queue_item(queue_id, position)
    if not defer_log:
        update_queue_timestamp_and_log(queue_id, f"Удалён студент {db.get_student_name(sid)} с места {position}")
    
    following = get_following_queue_ids(queue_id)
    affected_student_ids = {sid}
    
    for fq in following:
        fq_data = db.get_queue(fq)
        if not fq_data:
            continue
        fq_items = fq_data["items"]
        
        student_in_fq = next((it for it in fq_items if it[1] == sid), None)
        if not student_in_fq:
            continue
        
        regulars_ordered = []
        for itm in fq_items:
            pos_full, s_id, is_p, is_l, w_before, w_after, is_added = itm
            if not is_p and not is_l and not is_added:
                regulars_ordered.append((pos_full, s_id, w_before))
        
        total_reg = len(regulars_ordered)
        
        rel_pos_map = {}
        rel_index = 1
        for pos_full, s_id, w_before in regulars_ordered:
            rel_pos_map[s_id] = rel_index
            rel_index += 1
        
        if sid in rel_pos_map:
            relp = rel_pos_map[sid]
            cur_w = db.get_student_current_weight(sid)
            new_w = calculate_new_weight(cur_w, relp, total_reg)
            pos_in_queue = next((itm[0] for itm in fq_items if itm[1]==sid), None)
            if pos_in_queue is not None:
                set_queue_item_weights(fq, pos_in_queue, cur_w, new_w)
                db.update_weight(sid, new_w, place_info=f"очередь {fq}: место {relp}/{total_reg} (каскад после удаления)")
    
    return sid

def add_new_student_to_queue_and_penalize(queue_id: int, student_id: int, is_priority: int = 0, is_late: int = 0) -> int:
    import database as db
    q = db.get_queue(queue_id)
    if not q:
        raise ValueError("Очередь не найдена")
    if any(it[1]==student_id for it in q["items"]):
        raise ValueError("Студент уже в очереди")
    cur_w = db.get_student_current_weight(student_id)
    pos, w_before = db.add_student_to_existing_queue(queue_id, student_id, is_priority, is_late)
    set_queue_item_weights(queue_id, pos, w_before, cur_w)
    update_queue_timestamp_and_log(queue_id, f"Добавлен студент {db.get_student_name(student_id)} в конец очереди")
    return pos

def get_latest_queue() -> Optional[Tuple[int, str, str, str, str]]:
    recent = get_recent_queues(1)
    return recent[0] if recent else None