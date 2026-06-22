from __future__ import annotations

from ulid import ULID


def _gen_id(prefix: str) -> str:
    """生成带前缀的 ULID，符合 HLP spec §3.1。

    例: gen_task_id() -> "task_01HXY8KQ3JF0DZ6V1Q9M1ZRQM"
    """
    return f"{prefix}_{ULID()}"


def gen_task_id() -> str:
    return _gen_id("task")


def gen_checkpoint_id() -> str:
    return _gen_id("ckpt")


def gen_review_id() -> str:
    return _gen_id("rev")


def gen_artifact_id() -> str:
    return _gen_id("art")


def gen_ledger_id() -> str:
    return _gen_id("led")


def gen_audit_id() -> str:
    return _gen_id("aud")
