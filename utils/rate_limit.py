"""进程内登录失败限速：按（客户端 IP + 用户名）维度计数与临时锁定。

轻量防爆破：同一 key 在滑动窗口内连续失败达上限即锁定一段时间，
成功登录即清零。仅适用于单实例部署（多实例需外置存储如 Redis，
当前架构为单服务单进程）。
"""

import time

from exception.bad_except import bad_except

# 滑动窗口内允许的最大连续失败次数
_MAX_FAILURES = 5
# 失败计数滑动窗口（秒）
_WINDOW_SECONDS = 300
# 触发上限后的锁定时长（秒）
_LOCKOUT_SECONDS = 600
# 追踪表容量上限：超过时清理已过期条目，防止长期运行内存无界增长
_MAX_TRACKED_KEYS = 10_000

# {key: [fail_count, window_start_monotonic, lock_until_monotonic | None]}
_attempts: "dict[str, list]" = {}


def _cleanup_expired(now: float) -> None:
    """容量超限时清理已过期（未锁定且窗口已滑出）的条目。"""
    if len(_attempts) < _MAX_TRACKED_KEYS:
        return
    for key, entry in list(_attempts.items()):
        locked = entry[2] is not None and now < entry[2]
        in_window = now - entry[1] < _WINDOW_SECONDS
        if not locked and not in_window:
            _attempts.pop(key, None)


def check_locked(key: str) -> None:
    """命中锁定则拒绝并提示剩余等待时间；未锁定放行。"""
    entry = _attempts.get(key)
    if entry is None or entry[2] is None:
        return
    remain = entry[2] - time.monotonic()
    if remain > 0:
        bad_except(f"失败次数过多，账号已临时锁定，请约 {int(remain) // 60 + 1} 分钟后重试")


def record_failure(key: str) -> None:
    """记录一次登录失败：窗口内累计达上限即进入锁定（计数清零、开始锁定计时）。"""
    now = time.monotonic()
    _cleanup_expired(now)
    entry = _attempts.get(key)
    if entry is None or now - entry[1] >= _WINDOW_SECONDS:
        entry = [0, now, None]
        _attempts[key] = entry
    entry[0] += 1
    if entry[0] >= _MAX_FAILURES:
        entry[2] = now + _LOCKOUT_SECONDS
        entry[0] = 0


def reset(key: str) -> None:
    """登录成功后清除该 key 的失败记录。"""
    _attempts.pop(key, None)
