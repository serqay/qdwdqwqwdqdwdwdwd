import time
from bot.vip_check import check_is_vip

def put_task(queue, user_id, is_admin, task_dict):
    prio = 0 if check_is_vip(user_id) or is_admin else 1
    queue.put((prio, time.time(), task_dict))
