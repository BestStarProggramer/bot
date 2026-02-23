import random
import math
from config import K_FACTOR
from database import update_weight

def calculate_new_weight(current_weight, position, total_n):
    if total_n <= 1:
        return current_weight
    
    delta = (position - (total_n + 1) / 2) / total_n
    new_weight = current_weight * math.exp(K_FACTOR * delta)
    return max(0.1, min(new_weight, 10))

def weighted_permutation(students, priority_ids=None, late_ids=None):
    priority_ids = priority_ids or []
    late_ids = late_ids or []
    priority_students = [s for s in students if s[0] in priority_ids]
    late_students = [s for s in students if s[0] in late_ids]
    random_pool = [s for s in students if s[0] not in priority_ids and s[0] not in late_ids]
    
    random_part = []
    pool = random_pool.copy()
    while pool:
        total_weight = sum(s[2] for s in pool)
        r = random.uniform(0, total_weight)
        upto = 0
        for student in pool:
            upto += student[2]
            if upto >= r:
                random_part.append(student)
                pool.remove(student)
                break
    return priority_students + random_part + late_students

def update_weights(queue_list):
    N = len(queue_list)
    if N == 0: return
    for position, student in enumerate(queue_list, start=1):
        student_id, name, weight = student
        new_w = calculate_new_weight(weight, position, N)
        update_weight(student_id, new_w)

def update_swap_weights(s1_data, s2_data, total_n):
    for s_id, pos, weight in [s1_data, s2_data]:
        new_w = calculate_new_weight(weight, pos, total_n)
        update_weight(s_id, new_w)