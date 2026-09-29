"""표 묶음 스냅샷 — 버퍼가 비워져도 비교할 수 있게 묶음을 파일로 남긴다.

버퍼는 메모리에만 있다. 뷰어를 다시 켜거나 로그가 쌓이면 지난 묶음은 밀려난다.
그래서 "어제 로그인 vs 오늘 로그인" 같은 비교는 버퍼만으로는 할 수 없다.

묶음 하나 = 파일 하나. 같은 묶음을 다시 저장하면 덮어쓴다 (묶음 id 로 이름을 짓는다).
읽기는 절대 예외를 던지지 않는다 — 깨진 파일 하나 때문에 표 전체가 안 열리면 안 된다.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from typing import List, Optional


class SnapshotStore:
    def __init__(self, root: str):
        self.root = os.path.abspath(os.path.expanduser(root))

    def _dir(self, table_id: str) -> str:
        return os.path.join(self.root, _safe(table_id))

    def _path(self, table_id: str, group_id: str) -> str:
        # 묶음 id 에 파일명에 못 쓰는 글자가 섞여도 서로 겹치지 않게 해시를 붙인다
        h = hashlib.sha1(group_id.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self._dir(table_id), f"{_safe(group_id)[:40]}-{h}.json")

    def save(self, table_id: str, group: dict) -> Optional[str]:
        """묶음 하나를 저장한다. 실패하면 None (저장 실패가 로그 수신을 멈추면 안 된다)."""
        try:
            os.makedirs(self._dir(table_id), exist_ok=True)
            path = self._path(table_id, str(group.get("id", "")))
            body = {"table": table_id,
                    "savedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "group": {k: v for k, v in group.items() if k not in ("saved", "savedAt")}}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            os.replace(tmp, path)        # 쓰다 만 파일이 남지 않게
            return path
        except (OSError, TypeError, ValueError):
            return None

    def load(self, table_id: str, limit: int = 100) -> List[dict]:
        """저장된 묶음을 오래된 것부터. 너무 많으면 최근 limit 개만."""
        d = self._dir(table_id)
        if not os.path.isdir(d):
            return []
        out = []
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    body = json.load(f)
                g = dict(body["group"])
                g["saved"] = True
                g["savedAt"] = body.get("savedAt")
                out.append(g)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        out.sort(key=lambda g: g.get("savedAt") or "")
        return out[-limit:]


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s) or "_"
