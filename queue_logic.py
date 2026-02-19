import random
import math
from config import K_FACTOR
from database import update_weight

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

def update_weights(queue):
    N = len(queue)
    if N == 0: return

    for position, student in enumerate(queue, start=1):
        student_id, name, weight = student
        delta = (position - (N + 1) / 2) / N
        new_weight = weight * math.exp(K_FACTOR * delta)
        new_weight = max(0.1, min(new_weight, 10))
        update_weight(student_id, new_weight)