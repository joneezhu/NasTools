#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# nt-backup.sh - NasTools 备份与恢复 CLI
#
# 用法：
#   nt-backup.sh backup  [--config <dir>] [--out <dir>] [--full]
#   nt-backup.sh restore --file <zip> [--config <dir>] [--mode replace|merge]
#                         [--keep-config-yaml]
#   nt-backup.sh inspect --file <zip>
#
# 默认 --config：
#   - 容器/Linux：/config（与 docker 镜像一致）
#   - 否则当前工作目录的 ./config
#
# 适用场景：
#   1. 命令行/计划任务自动备份
#   2. 跨主机迁移：A 机执行 backup，将 zip 复制到 B 机执行 restore
#   3. 跨分支迁移：从其他人的 NasTools 分支取 zip，用 --mode merge 合并业务数据
# -----------------------------------------------------------------------------
set -euo pipefail

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  for c in python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PYTHON="$c"; break; fi
  done
fi

# 默认 config 路径
default_config_dir() {
  if [ -d "/config" ]; then
    echo "/config"
  else
    echo "$(pwd)/config"
  fi
}

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

CMD="${1:-}"
[ -z "$CMD" ] && usage 1
shift || true

CONFIG_DIR="$(default_config_dir)"
OUT_DIR=""
FULL=0
ZIP_FILE=""
MODE="replace"
KEEP_CONFIG_YAML=0

while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG_DIR="$2"; shift 2;;
    --out)    OUT_DIR="$2"; shift 2;;
    --full)   FULL=1; shift;;
    --file)   ZIP_FILE="$2"; shift 2;;
    --mode)   MODE="$2"; shift 2;;
    --keep-config-yaml) KEEP_CONFIG_YAML=1; shift;;
    -h|--help) usage 0;;
    *) echo "未知参数：$1" >&2; usage 1;;
  esac
done

[ -d "$CONFIG_DIR" ] || { echo "config 目录不存在：$CONFIG_DIR" >&2; exit 2; }

case "$CMD" in
  backup)
    OUT_DIR="${OUT_DIR:-$CONFIG_DIR/backup_file}"
    mkdir -p "$OUT_DIR"
    "$PYTHON" - "$CONFIG_DIR" "$OUT_DIR" "$FULL" <<'PYEOF'
import json, os, shutil, sqlite3, sys, time, zipfile
from pathlib import Path
config_dir, out_dir, full = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
ts = time.strftime("%Y%m%d%H%M%S")
work = Path(out_dir) / f"bk_{ts}"
work.mkdir(parents=True, exist_ok=True)
for fn in ("config.yaml", "default-category.yaml", "user.db"):
    src = Path(config_dir) / fn
    if src.exists():
        shutil.copy(src, work / fn)
    elif fn == "user.db":
        print(f"❌ 缺少必需文件：{src}", file=sys.stderr); sys.exit(3)
# 裁剪非业务表
if not full:
    drop_tables = [
        "SEARCH_RESULT_INFO", "RSS_TORRENTS", "DOUBAN_MEDIAS",
        "TRANSFER_HISTORY", "TRANSFER_UNKNOWN", "TRANSFER_BLACKLIST",
        "SYNC_HISTORY", "DOWNLOAD_HISTORY", "alembic_version",
    ]
    conn = sqlite3.connect(work / "user.db")
    cur = conn.cursor()
    for t in drop_tables:
        cur.execute(f'DROP TABLE IF EXISTS "{t}"')
    conn.commit(); conn.close()
# metadata
app_version = "unknown"
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent if __file__ != "<stdin>" else "."))
    from version import APP_VERSION
    app_version = APP_VERSION
except Exception:
    pass
alembic = None
try:
    conn = sqlite3.connect(work / "user.db"); cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
    row = cur.fetchone(); alembic = row[0] if row else None; conn.close()
except Exception:
    pass
meta = {
    "app_version": app_version,
    "alembic_version": alembic,
    "full_backup": bool(full),
    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "schema_format": "nastools-backup-v1",
}
(work / "backup_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
zip_path = str(work) + ".zip"
shutil.make_archive(str(work), "zip", str(work))
shutil.rmtree(work)
print(zip_path)
PYEOF
    ;;

  inspect)
    [ -z "$ZIP_FILE" ] && { echo "缺少 --file <zip>" >&2; exit 1; }
    [ -f "$ZIP_FILE" ] || { echo "文件不存在：$ZIP_FILE" >&2; exit 1; }
    "$PYTHON" - "$ZIP_FILE" "$CONFIG_DIR" <<'PYEOF'
import json, os, shutil, sqlite3, sys, tempfile, zipfile
zip_path, config_dir = sys.argv[1], sys.argv[2]
tmp = tempfile.mkdtemp(prefix="nt_inspect_")
try:
    with zipfile.ZipFile(zip_path) as z: z.extractall(tmp)
    has_db = os.path.exists(os.path.join(tmp, "user.db"))
    print("=== Backup 文件信息 ===")
    meta_path = os.path.join(tmp, "backup_meta.json")
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path, encoding="utf-8"))
        print(f"  来源版本   : {meta.get('app_version')}")
        print(f"  alembic    : {meta.get('alembic_version')}")
        print(f"  创建时间   : {meta.get('created_at')}")
        print(f"  完整备份   : {meta.get('full_backup')}")
    else:
        print("  (无 backup_meta.json，可能是旧版本备份)")
    print(f"  config.yaml         : {'✓' if os.path.exists(os.path.join(tmp, 'config.yaml')) else '✗'}")
    print(f"  default-category.yaml: {'✓' if os.path.exists(os.path.join(tmp, 'default-category.yaml')) else '✗'}")
    print(f"  user.db             : {'✓' if has_db else '✗'}")
    if has_db:
        conn = sqlite3.connect(os.path.join(tmp, "user.db")); cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
        print(f"\n  数据表（{len(tables)} 张）：")
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                print(f"    - {t:<35} {cur.fetchone()[0]:>8} 行")
            except Exception:
                print(f"    - {t:<35}     N/A")
        conn.close()
    cur_db = os.path.join(config_dir, "user.db")
    if os.path.exists(cur_db):
        try:
            conn = sqlite3.connect(cur_db); cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            row = cur.fetchone(); print(f"\n  本机 alembic        : {row[0] if row else '无'}")
            conn.close()
        except Exception:
            pass
finally:
    shutil.rmtree(tmp, ignore_errors=True)
PYEOF
    ;;

  restore)
    [ -z "$ZIP_FILE" ] && { echo "缺少 --file <zip>" >&2; exit 1; }
    [ -f "$ZIP_FILE" ] || { echo "文件不存在：$ZIP_FILE" >&2; exit 1; }
    case "$MODE" in replace|merge) ;; *) echo "--mode 仅支持 replace|merge" >&2; exit 1;; esac
    "$PYTHON" - "$ZIP_FILE" "$CONFIG_DIR" "$MODE" "$KEEP_CONFIG_YAML" <<'PYEOF'
import os, shutil, sqlite3, sys, tempfile, time, zipfile
zip_path, config_dir, mode, keep_yaml = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"
restore_yaml = (mode == "replace") and (not keep_yaml) or (mode == "merge" and keep_yaml is False and False)
# replace 默认覆盖 yaml；merge 默认不覆盖；--keep-config-yaml 可在 replace 模式下保留本机 yaml
if mode == "replace":
    restore_yaml = not keep_yaml
else:
    restore_yaml = False  # merge 默认不动 yaml；如需覆盖请用 web UI 的"同时覆盖"选项

tmp = tempfile.mkdtemp(prefix="nt_restore_")
rollback = os.path.join(config_dir, "backup_file", f"rollback_{time.strftime('%Y%m%d%H%M%S')}")
os.makedirs(rollback, exist_ok=True)
try:
    with zipfile.ZipFile(zip_path) as z: z.extractall(tmp)
    src_db = os.path.join(tmp, "user.db")
    if not os.path.exists(src_db):
        print("❌ 备份缺少 user.db", file=sys.stderr); sys.exit(3)

    # 回滚备份
    for fn in ("config.yaml", "default-category.yaml", "user.db"):
        fp = os.path.join(config_dir, fn)
        if os.path.exists(fp):
            shutil.copy(fp, rollback)

    if mode == "replace":
        shutil.copy(src_db, os.path.join(config_dir, "user.db"))
        if restore_yaml:
            for fn in ("config.yaml", "default-category.yaml"):
                sp = os.path.join(tmp, fn)
                if os.path.exists(sp): shutil.copy(sp, config_dir)
        print(f"✓ 整库覆盖完成。回滚备份：{rollback}")
    else:
        dst_db = os.path.join(config_dir, "user.db")
        if not os.path.exists(dst_db):
            # 本机无 db 则直接 copy（首次部署场景）
            shutil.copy(src_db, dst_db)
            print(f"✓ 本机无 user.db，已直接拷贝。回滚备份：{rollback}")
        else:
            src = sqlite3.connect(src_db); dst = sqlite3.connect(dst_db)
            try:
                def cols(c, t):
                    c.execute(f'PRAGMA table_info("{t}")')
                    return [r[1] for r in c.fetchall()]
                sc, dc = src.cursor(), dst.cursor()
                sc.execute("SELECT name FROM sqlite_master WHERE type='table'")
                src_tables = {r[0] for r in sc.fetchall() if not r[0].startswith("sqlite_")}
                dc.execute("SELECT name FROM sqlite_master WHERE type='table'")
                dst_tables = {r[0] for r in dc.fetchall() if not r[0].startswith("sqlite_")}
                common = (src_tables & dst_tables) - {"alembic_version"}
                total_t = total_r = 0
                dst.execute("BEGIN")
                for t in sorted(common):
                    inter = [c for c in cols(dc, t) if c in cols(sc, t)]
                    if not inter: continue
                    cq = ",".join(f'"{c}"' for c in inter)
                    sc.execute(f'SELECT {cq} FROM "{t}"')
                    rows = sc.fetchall()
                    try: dc.execute(f'DELETE FROM "{t}"')
                    except Exception: continue
                    if rows:
                        ph = ",".join(["?"] * len(inter))
                        try:
                            dc.executemany(f'INSERT INTO "{t}" ({cq}) VALUES ({ph})', rows)
                        except Exception as e:
                            print(f"  ⚠️ 表 {t} 合并失败：{e}", file=sys.stderr)
                            continue
                    total_t += 1; total_r += len(rows)
                    print(f"  ✓ {t:<35} {len(rows):>8} 行")
                dst.commit()
                print(f"\n✓ 智能合并完成：{total_t} 张表 / {total_r} 行。回滚备份：{rollback}")
            finally:
                src.close(); dst.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
PYEOF
    echo "提示：恢复后请重启 NasTools 服务（容器执行 docker restart 或在 UI 重启）。"
    ;;

  *) usage 1;;
esac
