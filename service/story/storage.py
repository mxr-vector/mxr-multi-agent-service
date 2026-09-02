"""
剧本模块资产文件存储共享工具：目录名清洗、路径规则与安全守卫。

资产文件统一在 UPLOAD_DIR 下按业务名称组织，便于人工查找与外部复用：
- 角色立绘：  story/characters/<user_id>/<角色名>/<角色名>_<序号>.<扩展名>
- 关键帧图片：story/keyframes/<项目名>/<关键帧名>/
立绘文件名携带角色名与序号便于人工查找；序号取目录内同前缀最大值 + 1，
删除后不复用，避免外部既有引用错乱。

立绘目录以 <user_id>（32 位无连字符 hex，不可猜测）作命名空间前缀：
UPLOAD_DIR 经 {BASE_URL}/public/files 无鉴权静态挂载，若仅按角色名组织，
跨租户同名角色（常态）会被枚举 <角色名>_1..n 拿到他人立绘；加用户命名
空间后，路径不可预测，对齐视频/封面的 uuid 命名策略。

安全约定（对齐 service/draw/diagram.py 的 is_relative_to 防护）：
- 一切落库/落盘的相对路径经 resolve_upload_path 做目录包含校验，防路径穿越；
- 客户端提交的路径字段先经 assert_asset_relative 白名单前缀校验；
- 文件删除按 DB 记录的精确路径执行（unlink_quietly），不整目录 rmtree，
  避免同名目录（可能属他人）被误删；空目录用 rmdir_if_empty 收尾；
- 序号文件写入用 O_EXCL 原子创建（write_seq_file），并发/同名不互相覆盖。
"""

import os
import re
import shutil
from pathlib import Path

from exception.bad_except import bad_except
from utils.env import ENV
from utils.logger import logger

# 目录名非法字符（路径分隔符与 Windows 保留字符），统一替换为下划线
_DIR_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')

# 关键帧图片存储根子目录（项目名/关键帧名目录位于其下）
KEYFRAME_IMAGE_ROOT = "story/keyframes"

# 角色立绘存储根子目录（user_id/角色名目录位于其下）
CHARACTER_ART_ROOT = "story/characters"

# 图片扩展名白名单（立绘/关键帧图片/视频封面共用，单处定义防分叉）
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def sanitize_dir_name(name: str, fallback: str) -> str:
    """业务名称转目录名：清洗非法字符；清洗后为空时回落 fallback（通常为业务 id）。"""
    cleaned = _DIR_UNSAFE_RE.sub("_", (name or "").strip()).strip(". ")
    return cleaned or fallback


def character_art_dir(user_id: str, character_name: str, character_id_hex: str) -> str:
    """角色立绘目录相对路径：story/characters/<user_id>/<角色名>。

    <user_id> 命名空间隔离跨用户枚举（详见模块 docstring 安全约定）。
    """
    name_dir = sanitize_dir_name(character_name, character_id_hex)
    return f"{CHARACTER_ART_ROOT}/{user_id}/{name_dir}"


def keyframe_image_dir(
    project_title: str,
    project_id_hex: str,
    keyframe_name: str,
    keyframe_fallback: str,
) -> str:
    """关键帧图片目录相对路径：story/keyframes/<项目名>/<关键帧名>。"""
    project_dir = sanitize_dir_name(project_title, project_id_hex)
    keyframe_dir = sanitize_dir_name(keyframe_name, keyframe_fallback)
    return f"{KEYFRAME_IMAGE_ROOT}/{project_dir}/{keyframe_dir}"


def art_filename_seq(filename: str, dir_name: str) -> int | None:
    """从 `<dir_name>_<序号>.<扩展名>` 形式的文件名提取序号；不匹配返回 None。"""
    match = re.match(rf"^{re.escape(dir_name)}_(\d+)\.[A-Za-z0-9]+$", filename)
    return int(match.group(1)) if match else None


def used_art_seqs(directory: Path, dir_name: str) -> set[int]:
    """目录内 `<dir_name>_<序号>.*` 文件已占用的序号集合。"""
    used: set[int] = set()
    if directory.is_dir():
        for entry in directory.iterdir():
            seq = art_filename_seq(entry.name, dir_name)
            if seq is not None:
                used.add(seq)
    return used


def resolve_upload_path(relative: str) -> Path:
    """解析 UPLOAD_DIR 下相对路径为绝对路径；越界（绝对路径/../逃逸）抛业务异常。

    所有对 story 资产文件的读写/删除/迁移都必须经过本函数，
    防止客户端可写路径字段造成路径穿越（对齐 draw 模块 is_relative_to 防护）。
    """
    if not relative or not str(relative).strip():
        bad_except("非法的资源路径")
    candidate = (ENV.upload_dir / str(relative)).resolve()
    if not candidate.is_relative_to(ENV.upload_dir.resolve()):
        bad_except("非法的资源路径")
    return candidate


def assert_asset_relative(
    relative: str | None, allowed_prefixes: tuple[str, ...]
) -> None:
    """校验客户端提交的资产相对路径：必须相对、无 ..、以允许前缀开头。"""
    if relative is None:
        return
    text = str(relative).strip()
    if not text:
        bad_except("非法的资源路径")
    if text.startswith(("/", "\\")) or ".." in Path(text).parts:
        bad_except("非法的资源路径")
    if not text.startswith(allowed_prefixes):
        bad_except("非法的资源路径")


def write_seq_file(directory: Path, prefix: str, ext: str, data: bytes) -> str:
    """以 `<prefix>_<序号>.<ext>` 原子写入文件（O_EXCL），返回文件名。

    序号从目录内同前缀最大序号 + 1 起，创建冲突（并发/同名角色共享目录）
    时自动顺延，杜绝互相覆盖。须在同步上下文（如 asyncio.to_thread）中调用。
    """
    directory.mkdir(parents=True, exist_ok=True)
    seq = max(used_art_seqs(directory, prefix), default=0) + 1
    while True:
        filename = f"{prefix}_{seq}.{ext}"
        target = directory / filename
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            seq += 1
            continue
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return filename


def move_without_overwrite(src: Path, dst: Path) -> None:
    """把 src 移动到 dst；dst 已存在时抛 FileExistsError（拒绝静默覆盖）。

    改名迁移等 rename 路径专用：与 write_seq_file 的 O_EXCL 保护对齐，
    避免并发上传/改名交错时覆盖刚落盘的文件。须在同步上下文
    （如 asyncio.to_thread）中调用，调用方负责先建好 dst 父目录。
    """
    if dst.exists():
        raise FileExistsError(f"目标已存在，拒绝覆盖: {dst}")
    shutil.move(str(src), str(dst))


def unlink_quietly(relative: str) -> None:
    """按 DB 记录的相对路径精确删除单个文件；路径越界或失败仅告警不抛出。"""
    try:
        resolve_upload_path(relative).unlink(missing_ok=True)
    except Exception as exc:  # 清理尽力而为，不阻断主流程
        logger.warning(f"[STORY] 文件清理失败: {relative}: {exc}")


def rmdir_if_empty(relative_dir: str) -> None:
    """目录为空时移除（精确清理后的收尾）；非空/越界/失败静默跳过。"""
    try:
        target = resolve_upload_path(relative_dir)
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
    except Exception:
        pass
